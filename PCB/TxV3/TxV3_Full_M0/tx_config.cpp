#include "tx_config.h"
#include <string.h>

// Compile the flash implementation exactly once, in this translation unit.
// flight_core.h uses the declaration-only .hpp for its legacy bind record.
#include <FlashStorage_SAMD.h>
#define TXCF_HAVE_INTERNAL_FLASH 1

#if TXCF_HAVE_INTERNAL_FLASH
struct TxcfInternalImage {
  uint8_t bytes[TXCF_INTERNAL_SIZE];
};
staticFlashStorage(txcfInternalStorage, TxcfInternalImage);
static TxcfInternalImage txcfInternalCache;
static bool txcfInternalLoaded = false;
#endif

static bool txcfUseFram = true;

static bool framPresent() {
  Wire.beginTransmission(TXCF_FRAM_ADDR);
  return Wire.endTransmission() == 0;
}

// -------- Low-level FRAM I2C --------
static bool framWrite(uint16_t addr, const uint8_t *data, size_t len) {
  if (addr + len > TXCF_FRAM_SIZE) return false;
  size_t off = 0;
  while (off < len) {
    size_t chunk = min((size_t)28, len - off); // 32B Wire buffer - 2B addr margin
    Wire.beginTransmission(TXCF_FRAM_ADDR);
    Wire.write((uint8_t)((addr >> 8) & 0xFF));
    Wire.write((uint8_t)(addr & 0xFF));
    Wire.write(data + off, chunk);
    if (Wire.endTransmission() != 0) return false;
    addr += chunk; off += chunk;
  }
  return true;
}
static bool framRead(uint16_t addr, uint8_t *data, size_t len) {
  if (addr + len > TXCF_FRAM_SIZE) return false;
  size_t off = 0;
  while (off < len) {
    size_t chunk = min((size_t)30, len - off);
    Wire.beginTransmission(TXCF_FRAM_ADDR);
    Wire.write((uint8_t)((addr >> 8) & 0xFF));
    Wire.write((uint8_t)(addr & 0xFF));
    if (Wire.endTransmission(false) != 0) return false; // repeated start
    size_t got = Wire.requestFrom((int)TXCF_FRAM_ADDR, (int)chunk);
    if (got != chunk) return false;
    for (size_t i=0;i<chunk;i++) data[off+i] = Wire.read();
    addr += chunk; off += chunk;
  }
  return true;
}

static bool internalRead(uint16_t addr, uint8_t *data, size_t len) {
#if TXCF_HAVE_INTERNAL_FLASH
  if ((uint32_t)addr + len > TXCF_INTERNAL_SIZE) return false;
  if (!txcfInternalLoaded) {
    txcfInternalStorage.read(txcfInternalCache);
    txcfInternalLoaded = true;
  }
  memcpy(data, txcfInternalCache.bytes + addr, len);
  return true;
#else
  (void)addr; (void)data; (void)len;
  return false;
#endif
}

static bool internalWrite(uint16_t addr, const uint8_t *data, size_t len) {
#if TXCF_HAVE_INTERNAL_FLASH
  if ((uint32_t)addr + len > TXCF_INTERNAL_SIZE) return false;
  if (!txcfInternalLoaded) {
    txcfInternalStorage.read(txcfInternalCache);
    txcfInternalLoaded = true;
  }
  memcpy(txcfInternalCache.bytes + addr, data, len);
  // Config writes are infrequent. Commit the complete small image so a reset
  // cannot leave RAM and flash with different model maps.
  txcfInternalStorage.write(txcfInternalCache);
  return true;
#else
  (void)addr; (void)data; (void)len;
  return false;
#endif
}

static bool storageRead(uint16_t addr, uint8_t *data, size_t len) {
  return txcfUseFram ? framRead(addr, data, len) : internalRead(addr, data, len);
}

static bool storageWrite(uint16_t addr, const uint8_t *data, size_t len) {
  return txcfUseFram ? framWrite(addr, data, len) : internalWrite(addr, data, len);
}
static uint16_t crc16_ccitt(const uint8_t *d, size_t n,
                            uint16_t init=0xFFFF, uint16_t poly=0x1021) {
  uint16_t crc = init;
  for (size_t i=0;i<n;i++) {
    crc ^= (uint16_t)d[i] << 8;
    for (uint8_t b=0;b<8;b++) {
      crc = (crc & 0x8000) ? (uint16_t)((crc<<1) ^ poly) : (uint16_t)(crc<<1);
    }
  }
  return crc;
}
static bool readHeaderRaw(txcf_header_t &h){ return storageRead(TXCF_HEADER_ADDR,(uint8_t*)&h,sizeof(h)); }
static bool writeHeaderRaw(const txcf_header_t &h){ return storageWrite(TXCF_HEADER_ADDR,(const uint8_t*)&h,sizeof(h)); }
static uint16_t slotAddr(uint16_t s){ return TXCF_MODELS_BASE + s*TXCF_MODEL_SIZE; }
static bool readModelRaw(uint16_t s, txcf_model_v1_t &m){ return storageRead(slotAddr(s),(uint8_t*)&m,sizeof(m)); }
static bool writeModelRaw(uint16_t s, const txcf_model_v1_t &m){ return storageWrite(slotAddr(s),(const uint8_t*)&m,sizeof(m)); }

namespace TXCF {

bool begin(bool initWire) {
  if (initWire) { Wire.begin(); Wire.setClock(400000); }
  txcfUseFram = framPresent();
#if !TXCF_HAVE_INTERNAL_FLASH
  if (!txcfUseFram) return false;
#endif
  txcf_header_t h{};
  if (!readHeaderRaw(h) ||
      h.magic != TXCF_MAGIC || h.version != TXCF_VERSION ||
      h.total_slots == 0 || h.total_slots > TXCF_MAX_SLOTS) {
    memset(&h, 0, sizeof(h));
    h.magic = TXCF_MAGIC; h.version = TXCF_VERSION;
    h.total_slots = TXCF_MAX_SLOTS; h.active_slot = 0; h.used_bitmap = 0;
    if (!writeHeaderRaw(h)) return false;
  }
  return true;
}

bool readHeader(txcf_header_t &out) {
  txcf_header_t h{};
  if (!readHeaderRaw(h)) return false;
  if (h.magic != TXCF_MAGIC || h.version != TXCF_VERSION) return false;
  out = h; return true;
}

bool loadActiveModel(txcf_model_v1_t &out) {
  txcf_header_t h{}; if (!readHeader(h)) return false;
  uint16_t slot = (h.active_slot < h.total_slots) ? h.active_slot : 0;
  txcf_model_v1_t m{}; if (!readModelRaw(slot, m)) return false;
  if (crc16_ccitt((const uint8_t*)&m, sizeof(m) - sizeof(m.crc16)) != m.crc16) return false;
  out = m; return true;
}

bool saveActiveModel(txcf_model_v1_t &model) {
  txcf_header_t h{}; if (!readHeader(h)) return false;
  uint16_t slot = (h.active_slot < h.total_slots) ? h.active_slot : 0;
  model.crc16 = crc16_ccitt((const uint8_t*)&model, sizeof(model) - sizeof(model.crc16));
  return writeModelRaw(slot, model);
}

bool setActiveSlot(uint16_t slot) {
  txcf_header_t h{}; if (!readHeader(h)) return false;
  if (slot >= h.total_slots) return false;
  h.active_slot = slot; return writeHeaderRaw(h);
}

int16_t channelToUs(float x, int ch, const txcf_model_v1_t &m, bool highRates) {
  if (ch < 0 || ch > 3) ch = 0;
  // If reserved[0] bit for channel is set, reverse the input direction
  if (m.reserved[0] & (1 << ch)) {
    x = -x;
  }
  int rate = m.rates_pct[ch];
  if (highRates) rate = 100;
  float r = constrain(rate, 0, 100) / 100.0f;

  float xExpo   = applyExpo(x, m.expo_pct[ch]);
  float xScaled = xExpo * r; // [-1..1]

  uint16_t mn = m.endpoints_us[ch][0];
  uint16_t mx = m.endpoints_us[ch][1];
  if (mn > mx) { uint16_t t=mn; mn=mx; mx=t; }

  float mid  = (mn + mx) * 0.5f;
  float half = (mx - mn) * 0.5f;
  int16_t out = (int16_t)roundf(mid + xScaled * half);

  int16_t sub = m.subtrim_us[ch];
  long tmp = (long)out + (long)sub;
  if (tmp < mn) tmp = mn;
  if (tmp > mx) tmp = mx;
  return (int16_t)tmp;
}

// ---------- Raw active-storage access used by USB Config Mode ----------
bool rawRead(uint16_t addr, uint8_t* data, size_t len)  { return storageRead(addr, data, len); }
bool rawWrite(uint16_t addr, const uint8_t* data, size_t len) { return storageWrite(addr, data, len); }
uint32_t storageSize() { return txcfUseFram ? TXCF_FRAM_SIZE : TXCF_INTERNAL_SIZE; }
const char* storageName() { return txcfUseFram ? "fram" : "internal_flash"; }
bool usingFram() { return txcfUseFram; }

} // namespace TXCF
