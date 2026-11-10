/*
  Transmitter V3 ESP32-C3 bring-up diagnostic.

  Safe scope: native USB serial, chip/flash identification, and BLE advertising.
  This sketch does not touch the SAMD UART, FRAM, or LoRa radio.
*/

#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>

static constexpr char DEVICE_NAME[] = "TxV3 ESP Test";
static constexpr char SERVICE_UUID[] = "7d2a00ff-8f45-4f3c-bc1d-5f91b7a6c301";

void setup() {
  Serial.begin(115200);
  delay(1500);

  Serial.println();
  Serial.println("TXV3_ESP_DIAGNOSTIC_START");
  Serial.printf("chip_model=%s\n", ESP.getChipModel());
  Serial.printf("chip_revision=%u\n", ESP.getChipRevision());
  Serial.printf("cpu_mhz=%u\n", ESP.getCpuFreqMHz());
  Serial.printf("flash_bytes=%u\n", ESP.getFlashChipSize());
  Serial.printf("heap_bytes=%u\n", ESP.getFreeHeap());

  BLEDevice::init(DEVICE_NAME);
  BLEServer *server = BLEDevice::createServer();
  BLEService *service = server->createService(SERVICE_UUID);
  service->start();

  BLEAdvertising *advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->setScanResponse(true);
  advertising->start();

  Serial.printf("ble_name=%s\n", DEVICE_NAME);
  Serial.println("ble_advertising=OK");
  Serial.println("TXV3_ESP_DIAGNOSTIC_READY");
}

void loop() {
  static uint32_t lastHeartbeat = 0;
  if (millis() - lastHeartbeat >= 2000) {
    lastHeartbeat = millis();
    Serial.printf("heartbeat_ms=%lu heap_bytes=%u\n",
                  static_cast<unsigned long>(lastHeartbeat),
                  ESP.getFreeHeap());
  }
  delay(10);
}
