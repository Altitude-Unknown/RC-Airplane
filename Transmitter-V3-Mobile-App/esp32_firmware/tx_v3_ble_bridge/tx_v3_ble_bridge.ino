/*
  Walach Aviation Transmitter V3 BLE-to-UART configuration bridge.

  IMPORTANT:
  - Confirm SAMD_RX_PIN and SAMD_TX_PIN against the source schematic before use.
  - The SAMD21 must explicitly enter wireless configuration mode and inhibit
    normal RF transmission before accepting writes.
  - This bridge deliberately does not parse or directly access FRAM.

  Requires the ESP32 Arduino core and its NimBLE library.
*/

#include <Arduino.h>
#include <NimBLEDevice.h>

static constexpr uint32_t SAMD_BAUD = 115200;
static constexpr int SAMD_RX_PIN = 16;  // TODO: confirm from V3 source schematic
static constexpr int SAMD_TX_PIN = 17;  // TODO: confirm from V3 source schematic
static constexpr int CONFIG_ENABLE_PIN = 27; // TODO: connect/confirm physical authorization input
static constexpr uint32_t IDLE_TIMEOUT_MS = 120000;
static constexpr size_t MAX_LINE = 600;

static const char *SERVICE_UUID  = "7d2a0001-8f45-4f3c-bc1d-5f91b7a6c301";
static const char *COMMAND_UUID  = "7d2a0002-8f45-4f3c-bc1d-5f91b7a6c301";
static const char *RESPONSE_UUID = "7d2a0003-8f45-4f3c-bc1d-5f91b7a6c301";

HardwareSerial samdSerial(2);
NimBLECharacteristic *responseCharacteristic = nullptr;
String phoneLine;
String samdLine;
uint32_t lastActivityMs = 0;
bool connected = false;

static bool configurationAuthorized() {
  return digitalRead(CONFIG_ENABLE_PIN) == LOW;
}

static void notifyLine(const String &line) {
  if (!connected || !responseCharacteristic) return;
  // NimBLE fragments notifications according to the negotiated MTU. The app
  // accumulates bytes until newline, so response boundaries remain explicit.
  String framed = line + "\n";
  responseCharacteristic->setValue(
      reinterpret_cast<const uint8_t *>(framed.c_str()), framed.length());
  responseCharacteristic->notify();
}

class ServerCallbacks final : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer *, NimBLEConnInfo &connInfo) override {
    connected = true;
    lastActivityMs = millis();
    NimBLEDevice::getServer()->updateConnParams(connInfo.getConnHandle(), 12, 24, 0, 200);
  }

  void onDisconnect(NimBLEServer *, NimBLEConnInfo &, int) override {
    connected = false;
    phoneLine = "";
    samdLine = "";
    NimBLEDevice::startAdvertising();
  }
};

class CommandCallbacks final : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic *characteristic, NimBLEConnInfo &) override {
    const auto value = characteristic->getValue();
    if (!configurationAuthorized()) {
      notifyLine("ERR NOT_AUTHORIZED");
      return;
    }
    lastActivityMs = millis();
    for (const char byte : value) {
      if (byte == '\r') continue;
      if (byte == '\n') {
        if (!phoneLine.isEmpty()) {
          samdSerial.print(phoneLine);
          samdSerial.print('\n');
          phoneLine = "";
        }
      } else if (phoneLine.length() < MAX_LINE) {
        phoneLine += byte;
      } else {
        phoneLine = "";
        notifyLine("ERR COMMAND_TOO_LONG");
      }
    }
  }
};

void setup() {
  pinMode(CONFIG_ENABLE_PIN, INPUT_PULLUP);
  samdSerial.begin(SAMD_BAUD, SERIAL_8N1, SAMD_RX_PIN, SAMD_TX_PIN);

  NimBLEDevice::init("Walach Transmitter V3");
  NimBLEDevice::setSecurityAuth(true, true, true);
  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_YESNO);

  NimBLEServer *server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());
  NimBLEService *service = server->createService(SERVICE_UUID);
  NimBLECharacteristic *command = service->createCharacteristic(
      COMMAND_UUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_ENC);
  responseCharacteristic = service->createCharacteristic(
      RESPONSE_UUID, NIMBLE_PROPERTY::NOTIFY | NIMBLE_PROPERTY::READ_ENC);
  command->setCallbacks(new CommandCallbacks());
  service->start();

  NimBLEAdvertising *advertising = NimBLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->enableScanResponse(true);
  advertising->start();
}

void loop() {
  while (samdSerial.available()) {
    const char byte = static_cast<char>(samdSerial.read());
    if (byte == '\r') continue;
    if (byte == '\n') {
      notifyLine(samdLine);
      samdLine = "";
      lastActivityMs = millis();
    } else if (samdLine.length() < MAX_LINE) {
      samdLine += byte;
    } else {
      samdLine = "";
      notifyLine("ERR RESPONSE_TOO_LONG");
    }
  }

  if (connected && millis() - lastActivityMs > IDLE_TIMEOUT_MS) {
    if (NimBLEServer *server = NimBLEDevice::getServer()) {
      for (const auto handle : server->getPeerDevices()) server->disconnect(handle);
    }
  }
  delay(1);
}
