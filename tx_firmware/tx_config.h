#pragma once
// === Transmitter FRAM Config (matches Models GUI v2) ===
// FRAM: I2C (e.g., MB85RC256V 32 KiB @ 0x50), 2-byte word addressing.
// Public API used by your Tx sketch (begin / loadActiveModel / channelToUs / raw READ/WRITE).

#include <Arduino.h>
#include <Wire.h>
#include <stdint.h>

#define TXCF_FRAM_ADDR   0x50
#define TXCF_FRAM_SIZE   (32 * 1024UL)

#define TXCF_MAGIC       0x54584346UL  // 'TXCF'
#define TXCF_VERSION     0x0001

#define TXCF_HEADER_ADDR 0x0000
#define TXCF_MODELS_BASE 0x0100
#define TXCF_MODEL_SIZE  64
#define TXCF_MAX_SLOTS   16

// 32-byte header
typedef struct __attribute__((packed)) {
  uint32_t magic;        // 'TXCF'
  uint16_t version;      // 0x0001
  uint16_t total_slots;  // e.g., 16
  uint16_t active_slot;  // 0..total_slots-1
  uint32_t used_bitmap;  // bit i set => slot i used
  uint8_t  reserved[18]; // future
} txcf_header_t;

// 64-byte model
typedef struct __attribute__((packed)) {
  char     name[16];        // UTF-8, zero-terminated if shorter
  uint16_t bind_code;       // 0..0x7FFF
  int8_t   rates_pct[4];    // 0..100
  int8_t   expo_pct[4];     // 0..100
  uint8_t  dr_switch;       // which switch toggles DR (you map it)
  uint8_t  active_rates;    // 0=low, 1=high
  int16_t  subtrim_us[4];   // -500..+500
  uint16_t endpoints_us[4][2]; // [ch][0=min,1=max]
    // reserved[0] bits: bit0..bit3 => channel reverse flags (1 = reversed)
    uint8_t  reserved[6];
  uint16_t crc16;           // CCITT over first 58 bytes
} txcf_model_v1_t;

namespace TXCF {

// Initialize I2C and ensure header exists (creates default if missing)
bool     begin(bool initWire=true);

// Read header; returns false on error
bool     readHeader(txcf_header_t &out);

// Load the active model (uses header.active_slot); CRC-checked
bool     loadActiveModel(txcf_model_v1_t &out);

// Save the active model (uses header.active_slot); refreshes CRC
bool     saveActiveModel(txcf_model_v1_t &model);

// Optionally switch active slot (writes header.active_slot)
bool     setActiveSlot(uint16_t slot);

// Expo helper: y = x*(1-e) + x^3*e
inline float applyExpo(float x, int8_t expoPct) {
  float e = (float)constrain((int)expoPct, 0, 100) / 100.0f;
  return x * (1.0f - e) + x * x * x * e;
}

// Map normalized stick [-1..1] to microseconds, applying rates/expo/subtrim/endpoints
int16_t  channelToUs(float stickNorm, int ch,
                     const txcf_model_v1_t &m, bool highRates);

// ---------- Raw FRAM access for USB Config Mode ----------
bool     rawRead(uint16_t addr, uint8_t* data, size_t len);
bool     rawWrite(uint16_t addr, const uint8_t* data, size_t len);
inline uint32_t framSize() { return TXCF_FRAM_SIZE; }

} // namespace TXCF
