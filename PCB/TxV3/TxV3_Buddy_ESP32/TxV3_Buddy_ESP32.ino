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

static constexpr int SAMD_RX_PIN = 20;  // ESP RX <- SAMD PB22 TX
static constexpr int SAMD_TX_PIN = 21;  // ESP TX -> SAMD PB23 RX
static constexpr uint32_t LINK_BAUD = 115200;
static constexpr uint8_t ESPNOW_CHANNEL = 1;
static constexpr uint32_t FRAME_MAGIC = 0x33585654UL; // "TVX3"
static constexpr uint8_t FRAME_VERSION = 1;
// 100 Hz matches a typical RC control-frame rate. The master forwards each
// newly received frame immediately rather than adding a second timing gate.
static constexpr uint32_t TX_INTERVAL_MS = 10;

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
  Serial.printf("STATUS role=%s authority=%s mode=%s mode_age_ms=%lu mac=%s sent=%lu received=%lu forwarded=%lu samd_lines=%lu role_replies=%lu\n", roleName(role), samdAuthority, samdMode,
                static_cast<unsigned long>(modeAge),
                WiFi.macAddress().c_str(), static_cast<unsigned long>(sentFrames),
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
