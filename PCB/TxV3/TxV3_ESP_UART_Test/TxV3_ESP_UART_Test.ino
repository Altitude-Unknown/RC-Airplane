/*
  Transmitter V3 ESP32-C3 <-> SAMD21 UART responder.

  GPIO20: ESP RX <- SAMD PB22 TX
  GPIO21: ESP TX -> SAMD PB23 RX

  Responds to "M0_PING n" with "ESP_PONG n". No LoRa or FRAM access.
*/

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>

static constexpr int SAMD_RX_PIN = 20;
static constexpr int SAMD_TX_PIN = 21;
static constexpr uint32_t SAMD_BAUD = 115200;
static constexpr char DEVICE_NAME[] = "TxV3 UART Test";
static constexpr char SERVICE_UUID[] = "7d2a00fe-8f45-4f3c-bc1d-5f91b7a6c301";

HardwareSerial samdLink(1);
static char receiveLine[64];
static size_t receiveLength = 0;

static void processLine(const char *line) {
  unsigned long sequence = 0;
  if (sscanf(line, "M0_PING %lu", &sequence) == 1) {
    samdLink.printf("ESP_PONG %lu\n", sequence);
  } else {
    samdLink.print("ESP_ERROR BAD_COMMAND\n");
  }
}

void setup() {
  samdLink.begin(SAMD_BAUD, SERIAL_8N1, SAMD_RX_PIN, SAMD_TX_PIN);

  BLEDevice::init(DEVICE_NAME);
  BLEServer *server = BLEDevice::createServer();
  BLEService *service = server->createService(SERVICE_UUID);
  service->start();
  BLEAdvertising *advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->setScanResponse(true);
  advertising->start();
}

void loop() {
  while (samdLink.available()) {
    const char byte = static_cast<char>(samdLink.read());
    if (byte == '\r') continue;
    if (byte == '\n') {
      if (receiveLength) {
        receiveLine[receiveLength] = '\0';
        processLine(receiveLine);
        receiveLength = 0;
      }
    } else if (receiveLength < sizeof(receiveLine) - 1) {
      receiveLine[receiveLength++] = byte;
    } else {
      receiveLength = 0;
    }
  }
  delay(1);
}
