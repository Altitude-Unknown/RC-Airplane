/*
  Transmitter V3 ESP32-C3 buddy-box bridge.

  Configure through the ESP native USB console at 115200 baud:
    ROLE MASTER
    ROLE STUDENT
    ROLE CLEAR
    STATUS

  The role is stored in ESP32 NVS. Both roles use ESP-NOW broadcast frames;
  frames include a protocol magic/version and sender role. The SAMD21 remains
  the only processor that can command the airplane.
*/

#include <Arduino.h>
#include <Preferences.h>
#include <WiFi.h>
#include <esp_now.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEHIDDevice.h>
#include <BLESecurity.h>
#include <esp_mac.h>
#if defined(CONFIG_BLUEDROID_ENABLED)
#include <esp_gap_ble_api.h>
#endif
#if defined(CONFIG_NIMBLE_ENABLED)
#include <host/ble_store.h>
#endif

static constexpr int SAMD_RX_PIN = 20;  // ESP RX <- SAMD PB22 TX
static constexpr int SAMD_TX_PIN = 21;  // ESP TX -> SAMD PB23 RX
static constexpr uint32_t LINK_BAUD = 115200;
static constexpr uint8_t ESPNOW_CHANNEL = 1;
static constexpr uint32_t FRAME_MAGIC = 0x33585654UL; // "TVX3"
static constexpr uint8_t FRAME_VERSION = 1;
// 100 Hz matches a typical RC control-frame rate. The master forwards each
// newly received frame immediately rather than adding a second timing gate.
static constexpr uint32_t TX_INTERVAL_MS = 10;
static constexpr uint8_t BLE_HID_REPORT_ID = 1;

// Apple requires the standard Gamepad/Pointer collection shape for a BLE HID
// controller to be published through IOHID. Flight Lab handles the resulting
// macOS axis mapping separately from its USB joystick mapping.
static const uint8_t BLE_HID_REPORT_MAP[] = {
  0x05, 0x01,                    // Usage Page (Generic Desktop)
  0x09, 0x05,                    // Usage (Gamepad)
  0xA1, 0x01,                    // Collection (Application)
  0x85, BLE_HID_REPORT_ID,       //   Report ID
  0x09, 0x01,                    //   Usage (Pointer)
  0xA1, 0x00,                    //   Collection (Physical)
  0x05, 0x01,                    //   Usage Page (Generic Desktop)
  0x09, 0x30,                    //   Usage (X: aileron)
  0x09, 0x31,                    //   Usage (Y: elevator)
  0x09, 0x33,                    //   Usage (Rx: rudder)
  0x09, 0x34,                    //   Usage (Ry: throttle)
  0x15, 0x81,                    //   Logical Minimum (-127)
  0x25, 0x7F,                    //   Logical Maximum (127)
  0x75, 0x08,                    //   Report Size (8)
  0x95, 0x04,                    //   Report Count (4)
  0x81, 0x02,                    //   Input (Data, Variable, Absolute)
  0xC0,                          //   End Physical Collection
  0x05, 0x09,                    //   Usage Page (Button)
  0x19, 0x01,                    //   Usage Minimum (1)
  0x29, 0x08,                    //   Usage Maximum (8)
  0x15, 0x00,                    //   Logical Minimum (0)
  0x25, 0x01,                    //   Logical Maximum (1)
  0x75, 0x01,                    //   Report Size (1)
  0x95, 0x08,                    //   Report Count (8)
  0x81, 0x02,                    //   Input (Data, Variable, Absolute)
  0xC0                           // End Collection
};

struct __attribute__((packed)) BleGamepadReport {
  int8_t aileron;
  int8_t elevator;
  int8_t rudder;
  int8_t throttle;
  uint8_t buttons;
};

enum Role : uint8_t { ROLE_UNCONFIGURED = 0, ROLE_MASTER = 1, ROLE_STUDENT = 2 };

struct __attribute__((packed)) BuddyFrame {
  uint32_t magic;
  uint8_t version;
  uint8_t role;
  uint16_t sequence;
  uint16_t rudder;
  uint16_t aileron;
  uint16_t elevator;
  uint16_t throttle;
  uint8_t auxFlags;
  uint8_t reserved;
  uint16_t crc;
};

static constexpr uint16_t SAMD_PACKET_MAGIC = 0xB358;
static constexpr uint8_t SAMD_PACKET_TYPE_STUDENT = 1;
struct __attribute__((packed)) SamdStudentPacket {
  uint16_t magic;
  uint8_t version;
  uint8_t type;
  uint16_t sequence;
  uint16_t rudder;
  uint16_t aileron;
  uint16_t elevator;
  uint16_t throttle;
  uint8_t auxFlags;
  uint8_t reserved;
  uint16_t crc;
};

HardwareSerial samdLink(1);
Preferences preferences;
Role role = ROLE_UNCONFIGURED;
BuddyFrame localFrame{};
BuddyFrame receivedStudent{};
volatile bool receivedStudentPending = false;
volatile uint32_t receivedStudentAtMs = 0;
portMUX_TYPE receiveMux = portMUX_INITIALIZER_UNLOCKED;
char samdLine[96];
size_t samdLength = 0;
String usbLine;
uint32_t lastTransmitMs = 0;
uint32_t sentFrames = 0;
uint32_t receivedFrames = 0;
uint32_t samdLinesReceived = 0;
uint32_t roleRepliesSent = 0;
uint32_t studentFramesForwarded = 0;
bool samdReady = false;
const char *samdAuthority = "UNKNOWN";
const char *samdMode = "UNKNOWN";
uint32_t samdModeAtMs = 0;
BLEHIDDevice *bleHid = nullptr;
BLECharacteristic *bleInputReport = nullptr;
bool bleHidStarted = false;
volatile bool bleConnected = false;
uint16_t lastBleSequence = 0;
volatile uint32_t bleConnectCount = 0;
volatile uint32_t bleDisconnectCount = 0;
volatile int bleAuthStatus = -1;
volatile bool bleReportSubscribed = false;
bool bleFilterInitialized = false;
uint16_t filteredAileron = 1500;
uint16_t filteredElevator = 1500;
uint16_t filteredRudder = 1500;
uint16_t filteredThrottle = 1000;

class HidServerCallbacks final : public BLEServerCallbacks {
  void onConnect(BLEServer *) override {
    bleConnected = true;
    bleAuthStatus = -1;
    bleReportSubscribed = false;
    ++bleConnectCount;
  }

  void onDisconnect(BLEServer *) override {
    bleConnected = false;
    bleReportSubscribed = false;
    ++bleDisconnectCount;
    BLEDevice::startAdvertising();
  }
};

class HidReportCallbacks final : public BLECharacteristicCallbacks {
#if defined(CONFIG_NIMBLE_ENABLED)
  void onSubscribe(BLECharacteristic *, ble_gap_conn_desc *, uint16_t value) override {
    bleReportSubscribed = value != 0;
  }
#endif
};

class HidSecurityCallbacks final : public BLESecurityCallbacks {
  bool onSecurityRequest() override {
    return true;
  }

#if defined(CONFIG_BLUEDROID_ENABLED)
  void onAuthenticationComplete(esp_ble_auth_cmpl_t result) override {
    bleAuthStatus = result.success ? 0 : result.fail_reason;
  }
#elif defined(CONFIG_NIMBLE_ENABLED)
  void onAuthenticationComplete(ble_gap_conn_desc *result) override {
    bleAuthStatus = result != nullptr && result->sec_state.encrypted ? 0 : 1;
  }
#endif
};

static int8_t pulseToBleAxis(uint16_t pulseUs) {
  const int32_t bounded = constrain(static_cast<int32_t>(pulseUs), 1000L, 2000L);
  return static_cast<int8_t>(map(bounded, 1000L, 2000L, -127L, 127L));
}

static uint16_t filterBlePulse(uint16_t previous, uint16_t current) {
  // Four-sample IIR at the 100 Hz control rate removes ADC chatter while
  // retaining a quick (~40 ms) control response.
  return static_cast<uint16_t>((3UL * previous + current + 2UL) / 4UL);
}

static void beginBleHid() {
  if (bleHidStarted) return;

  // Simulator mode persists until reboot. Stop the unused buddy radio before
  // starting BLE so Wi-Fi/ESP-NOW cannot compete for airtime or power.
  esp_now_deinit();
  WiFi.mode(WIFI_OFF);

  // Keep the name short enough that flags, HID appearance, name, and the 1812
  // service UUID all fit in the 31-byte primary advertising packet. macOS uses
  // that UUID to classify the device as BLE HID before connecting.
  BLEDevice::init("Walach Tx2");
#if defined(CONFIG_BLUEDROID_ENABLED)
  // Changing the public BLE identity while retaining the previous LTK makes
  // macOS attempt encryption with a stale key and disconnect with a MIC
  // failure. Clear bonds once when the HID identity version changes.
  static constexpr uint8_t BLE_IDENTITY_VERSION = 2;
  if (preferences.getUChar("ble-id", 0) != BLE_IDENTITY_VERSION) {
    int bondCount = esp_ble_get_bond_device_num();
    if (bondCount > 0) {
      esp_ble_bond_dev_t *bonds = static_cast<esp_ble_bond_dev_t *>(
          malloc(sizeof(esp_ble_bond_dev_t) * bondCount));
      if (bonds != nullptr && esp_ble_get_bond_device_list(&bondCount, bonds) == ESP_OK) {
        for (int i = 0; i < bondCount; ++i) esp_ble_remove_bond_device(bonds[i].bd_addr);
      }
      free(bonds);
    }
    preferences.putUChar("ble-id", BLE_IDENTITY_VERSION);
  }
#endif
#if defined(CONFIG_NIMBLE_ENABLED)
  // Version 3 retries the cleanup attempted by version 2.  The old code
  // advanced this marker even when ble_store_clear() failed, leaving the ESP
  // and macOS with different LTKs and causing an immediate MIC failure.
  static constexpr uint8_t BLE_IDENTITY_VERSION = 3;
  if (preferences.getUChar("ble-id", 0) != BLE_IDENTITY_VERSION) {
    const int clearResult = ble_store_clear();
    Serial.printf("BLE bond cleanup result=%d\n", clearResult);
    if (clearResult == 0) {
      preferences.putUChar("ble-id", BLE_IDENTITY_VERSION);
    } else {
      Serial.println("BLE bond cleanup will retry on next simulator-mode boot");
    }
  }
#endif
  BLESecurity *security = new BLESecurity();
  security->setCapability(ESP_IO_CAP_NONE);
  security->setAuthenticationMode(true, false, true); // Bonded Just Works pairing.
  BLEDevice::setSecurityCallbacks(new HidSecurityCallbacks());

  BLEServer *server = BLEDevice::createServer();
  server->setCallbacks(new HidServerCallbacks());
  bleHid = new BLEHIDDevice(server);
  bleHid->manufacturer()->setValue("Walach Aviation");
  // Arduino-ESP32 3.3.x serializes these 16-bit PnP fields big-endian,
  // although Bluetooth DIS defines them little-endian. Pass byte-swapped
  // constants so hosts receive VID=0x1209, PID=0x5247, version=0x0101.
  // PID 0x5247 identifies the four-axis report and avoids the cached two-axis
  // diagnostic descriptor (PID 0x5246).
  bleHid->pnp(0x02, 0x0912, 0x4752, 0x0101);
  bleHid->hidInfo(0x00, 0x01);
  bleHid->reportMap(const_cast<uint8_t *>(BLE_HID_REPORT_MAP), sizeof(BLE_HID_REPORT_MAP));
  bleInputReport = bleHid->inputReport(BLE_HID_REPORT_ID);
  bleInputReport->setCallbacks(new HidReportCallbacks());
  bleHid->setBatteryLevel(100); // No battery-voltage divider is fitted yet.
  bleHid->startServices();

  BLEAdvertising *advertising = BLEDevice::getAdvertising();
  // macOS only publishes a generic HOGP controller through IOHID when it uses
  // the Gamepad appearance. The report map itself remains the USB-style RC
  // joystick layout, without a Pointer collection.
  advertising->setAppearance(0x03C4); // HID gamepad appearance
  advertising->addServiceUUID(bleHid->hidService()->getUUID());
  advertising->setScanResponse(true);
  advertising->setMinPreferred(0x06);
  advertising->setMaxPreferred(0x12);
  BLEDevice::startAdvertising();
  bleHidStarted = true;
}

static void sendBleHidReport() {
  // Match Espressif's HID examples: once the link is connected, publish fresh
  // reports and let the BLE stack decide whether a subscribed client receives
  // them. bleReportSubscribed is only updated by NimBLE's optional onSubscribe
  // callback and otherwise stays false even after macOS enables the CCCD.
  // Bonded reconnects can likewise skip a new authentication callback.
  if (!bleHidStarted || !bleConnected || bleInputReport == nullptr ||
      localFrame.magic != FRAME_MAGIC || localFrame.sequence == lastBleSequence) return;
  lastBleSequence = localFrame.sequence;
  if (!bleFilterInitialized) {
    filteredAileron = localFrame.aileron;
    filteredElevator = localFrame.elevator;
    filteredRudder = localFrame.rudder;
    filteredThrottle = localFrame.throttle;
    bleFilterInitialized = true;
  } else {
    filteredAileron = filterBlePulse(filteredAileron, localFrame.aileron);
    filteredElevator = filterBlePulse(filteredElevator, localFrame.elevator);
    filteredRudder = filterBlePulse(filteredRudder, localFrame.rudder);
    filteredThrottle = filterBlePulse(filteredThrottle, localFrame.throttle);
  }
  // The Report Reference descriptor on this characteristic already supplies
  // BLE_HID_REPORT_ID. The notification value contains report data only;
  // including the ID here shifts every axis and drops throttle from the
  // four-axis portion of the report.
  const BleGamepadReport report = {
    pulseToBleAxis(filteredAileron),
    pulseToBleAxis(filteredElevator),
    pulseToBleAxis(filteredRudder),
    pulseToBleAxis(filteredThrottle),
    localFrame.auxFlags
  };
  bleInputReport->setValue(reinterpret_cast<const uint8_t *>(&report), sizeof(report));
  bleInputReport->notify();
}

static uint16_t crc16(const uint8_t *data, size_t length) {
  uint16_t crc = 0xFFFF;
  while (length--) {
    crc ^= static_cast<uint16_t>(*data++) << 8;
    for (uint8_t i = 0; i < 8; ++i)
      crc = (crc & 0x8000) ? static_cast<uint16_t>((crc << 1) ^ 0x1021)
                           : static_cast<uint16_t>(crc << 1);
  }
  return crc;
}

static const char *roleName(Role value) {
  if (value == ROLE_MASTER) return "MASTER";
  if (value == ROLE_STUDENT) return "STUDENT";
  return "UNCONFIGURED";
}

static void printStatus() {
  const uint32_t modeAge = samdModeAtMs ? millis() - samdModeAtMs : 0xFFFFFFFFUL;
  Serial.printf("STATUS role=%s authority=%s mode=%s mode_age_ms=%lu mac=%s ble=%s ble_conn=%lu ble_disc=%lu ble_auth=%d ble_sub=%s sent=%lu received=%lu forwarded=%lu samd_lines=%lu role_replies=%lu\n", roleName(role), samdAuthority, samdMode,
                static_cast<unsigned long>(modeAge),
                WiFi.macAddress().c_str(), bleConnected ? "connected" : (bleHidStarted ? "advertising" : "off"),
                static_cast<unsigned long>(bleConnectCount),
                static_cast<unsigned long>(bleDisconnectCount), bleAuthStatus,
                bleReportSubscribed ? "yes" : "no",
                static_cast<unsigned long>(sentFrames),
                static_cast<unsigned long>(receivedFrames),
                static_cast<unsigned long>(studentFramesForwarded),
                static_cast<unsigned long>(samdLinesReceived),
                static_cast<unsigned long>(roleRepliesSent));
}

static void setRole(Role next) {
  role = next;
  preferences.putUChar("role", static_cast<uint8_t>(role));
  Serial.printf("OK role=%s reset_recommended\n", roleName(role));
  samdLink.printf("ROLE %s\n", roleName(role));
}

static bool roleChangeAllowed() {
  if (!samdModeAtMs || millis() - samdModeAtMs > 1500) return false;
  return !strcmp(samdMode, "CONFIG") || !strcmp(samdMode, "SIMULATOR") || !strcmp(samdMode, "SETUP");
}

static bool samdFlightActive() {
  return samdModeAtMs && millis() - samdModeAtMs <= 1500 && !strcmp(samdMode, "FLIGHT");
}

static void processUsbLine(String line) {
  line.trim();
  line.toUpperCase();
  if (line == "ROLE MASTER") { if (roleChangeAllowed()) setRole(ROLE_MASTER); else Serial.printf("ERR role_locked mode=%s\n", samdMode); }
  else if (line == "ROLE STUDENT" || line == "ROLE SLAVE") { if (roleChangeAllowed()) setRole(ROLE_STUDENT); else Serial.printf("ERR role_locked mode=%s\n", samdMode); }
  else if (line == "ROLE CLEAR") { if (roleChangeAllowed()) setRole(ROLE_UNCONFIGURED); else Serial.printf("ERR role_locked mode=%s\n", samdMode); }
  else if (line == "STATUS") printStatus();
  else if (line == "HELP") Serial.println("ROLE MASTER | ROLE STUDENT | ROLE CLEAR | STATUS");
  else if (line.length()) Serial.println("ERR unknown_command");
}

static void processSamdLine(const char *line) {
  ++samdLinesReceived;
  unsigned seq, rud, ail, ele, thr, aux;
  if (sscanf(line, "LOCAL %u %u %u %u %u %u", &seq, &rud, &ail, &ele, &thr, &aux) == 6) {
    samdReady = true;
    localFrame.magic = FRAME_MAGIC;
    localFrame.version = FRAME_VERSION;
    localFrame.role = role;
    localFrame.sequence = static_cast<uint16_t>(seq);
    localFrame.rudder = constrain(rud, 800U, 2200U);
    localFrame.aileron = constrain(ail, 800U, 2200U);
    localFrame.elevator = constrain(ele, 800U, 2200U);
    localFrame.throttle = constrain(thr, 800U, 2200U);
    localFrame.auxFlags = static_cast<uint8_t>(aux);
  } else if (!strcmp(line, "ROLE?")) {
    // A role query means the SAMD has (re)started safe boot negotiation.
    // Pause binary forwarding until it acknowledges the role with READY.
    samdReady = false;
    samdLink.printf("ROLE %s\n", roleName(role));
    ++roleRepliesSent;
  } else if (!strcmp(line, "READY")) {
    samdReady = true;
  } else if (!strcmp(line, "AUTHORITY STUDENT")) {
    samdReady = true;
    samdAuthority = "STUDENT";
  } else if (!strcmp(line, "AUTHORITY INSTRUCTOR")) {
    samdReady = true;
    samdAuthority = "INSTRUCTOR";
  } else if (!strncmp(line, "MODE ", 5)) {
    const char *value = line + 5;
    if (!strcmp(value, "FLIGHT")) samdMode = "FLIGHT";
    else if (!strcmp(value, "CONFIG")) samdMode = "CONFIG";
    else if (!strcmp(value, "SIMULATOR")) samdMode = "SIMULATOR";
    else if (!strcmp(value, "SETUP")) samdMode = "SETUP";
    else if (!strcmp(value, "BIND")) samdMode = "BIND";
    else samdMode = "UNKNOWN";
    samdModeAtMs = millis();
  }
}

static void onReceive(const esp_now_recv_info_t *, const uint8_t *data, int length) {
  if (role != ROLE_MASTER || length != static_cast<int>(sizeof(BuddyFrame))) return;
  BuddyFrame frame;
  memcpy(&frame, data, sizeof(frame));
  const uint16_t expected = frame.crc;
  frame.crc = 0;
  if (frame.magic != FRAME_MAGIC || frame.version != FRAME_VERSION ||
      frame.role != ROLE_STUDENT || crc16(reinterpret_cast<const uint8_t *>(&frame), sizeof(frame)) != expected) return;
  portENTER_CRITICAL(&receiveMux);
  memcpy(&receivedStudent, &frame, sizeof(frame));
  receivedStudentAtMs = millis();
  receivedStudentPending = true;
  portEXIT_CRITICAL(&receiveMux);
  ++receivedFrames;
}

static bool beginEspNow() {
  WiFi.mode(WIFI_STA);
  WiFi.setChannel(ESPNOW_CHANNEL);
  if (esp_now_init() != ESP_OK) return false;
  esp_now_register_recv_cb(onReceive);
  esp_now_peer_info_t peer{};
  memset(peer.peer_addr, 0xFF, 6);
  peer.channel = ESPNOW_CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  return esp_now_add_peer(&peer) == ESP_OK || esp_now_is_peer_exist(peer.peer_addr);
}

void setup() {
  Serial.begin(115200);
  samdLink.begin(LINK_BAUD, SERIAL_8N1, SAMD_RX_PIN, SAMD_TX_PIN);
  // Derive a stable, unique locally administered base address from this
  // chip's factory address. macOS keys its BLE GATT cache by address and can
  // retain a rejected HID descriptor even after "Forget This Device". The
  // local-address bit gives the corrected HID identity a clean cache entry
  // without giving multiple transmitters the same address.
  uint8_t localBaseMac[6];
  if (esp_read_mac(localBaseMac, ESP_MAC_EFUSE_FACTORY) == ESP_OK) {
    localBaseMac[0] = static_cast<uint8_t>((localBaseMac[0] | 0x02) ^ 0x08);
    esp_base_mac_addr_set(localBaseMac);
  }
  preferences.begin("txv3-buddy", false);
  const uint8_t stored = preferences.getUChar("role", ROLE_UNCONFIGURED);
  role = stored <= ROLE_STUDENT ? static_cast<Role>(stored) : ROLE_UNCONFIGURED;
  const bool radioOk = beginEspNow();
  delay(300);
  Serial.printf("TXV3_BUDDY_ESP_READY espnow=%s\n", radioOk ? "OK" : "FAIL");
  printStatus();
  samdLink.printf("ROLE %s\n", roleName(role));
}

void loop() {
  while (Serial.available()) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\r') continue;
    if (c == '\n') { processUsbLine(usbLine); usbLine = ""; }
    else if (usbLine.length() < 80) usbLine += c;
  }

  while (samdLink.available()) {
    const char c = static_cast<char>(samdLink.read());
    if (c == '\r') continue;
    if (c == '\n') {
      if (samdLength) { samdLine[samdLength] = 0; processSamdLine(samdLine); samdLength = 0; }
    } else if (samdLength < sizeof(samdLine) - 1) samdLine[samdLength++] = c;
    else samdLength = 0;
  }

  if (!strcmp(samdMode, "SIMULATOR")) {
    beginBleHid();
    sendBleHidReport();
  }

  const uint32_t now = millis();
  if (role == ROLE_STUDENT && samdFlightActive() && localFrame.magic == FRAME_MAGIC && now - lastTransmitMs >= TX_INTERVAL_MS) {
    lastTransmitMs = now;
    localFrame.role = ROLE_STUDENT;
    localFrame.crc = 0;
    localFrame.crc = crc16(reinterpret_cast<const uint8_t *>(&localFrame), sizeof(localFrame));
    const uint8_t broadcast[6] = {0xFF,0xFF,0xFF,0xFF,0xFF,0xFF};
    if (esp_now_send(broadcast, reinterpret_cast<const uint8_t *>(&localFrame), sizeof(localFrame)) == ESP_OK) ++sentFrames;
  }

  if (role == ROLE_MASTER && samdFlightActive() && samdReady && receivedStudentPending) {
    BuddyFrame frame;
    portENTER_CRITICAL(&receiveMux);
    memcpy(&frame, &receivedStudent, sizeof(frame));
    const uint32_t receivedAt = receivedStudentAtMs;
    receivedStudentPending = false;
    portEXIT_CRITICAL(&receiveMux);
    (void)receivedAt;
    SamdStudentPacket packet{};
    packet.magic=SAMD_PACKET_MAGIC;
    packet.version=FRAME_VERSION;
    packet.type=SAMD_PACKET_TYPE_STUDENT;
    packet.sequence=frame.sequence;
    packet.rudder=frame.rudder;
    packet.aileron=frame.aileron;
    packet.elevator=frame.elevator;
    packet.throttle=frame.throttle;
    packet.auxFlags=frame.auxFlags;
    packet.crc=0;
    packet.crc=crc16(reinterpret_cast<const uint8_t *>(&packet),sizeof(packet));
    samdLink.write(reinterpret_cast<const uint8_t *>(&packet),sizeof(packet));
    ++studentFramesForwarded;
  }

  delay(1);
}
