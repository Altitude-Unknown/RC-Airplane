#include <stdint.h>
#include <string.h>
#include <assert.h>
const uint16_t RC_MIN=1000, RC_MAX=2000;
const uint8_t SBUS_CHANNEL_COUNT=16, SBUS_CHANNEL_PAYLOAD_SIZE=22;
static uint16_t rcMicrosecondsToSbus(uint16_t microseconds) {
  if (microseconds < RC_MIN) microseconds = RC_MIN;
  if (microseconds > RC_MAX) microseconds = RC_MAX;
  return (uint16_t)(200UL + ((uint32_t)(microseconds - RC_MIN) * 8UL) / 5UL);
}

static void packSbusChannels(const uint16_t channels[SBUS_CHANNEL_COUNT],
                             uint8_t payload[SBUS_CHANNEL_PAYLOAD_SIZE]) {
  memset(payload, 0, SBUS_CHANNEL_PAYLOAD_SIZE);

  uint32_t accumulator = 0;
  uint8_t accumulatorBits = 0;
  uint8_t outputIndex = 0;

  for (uint8_t channel = 0; channel < SBUS_CHANNEL_COUNT; ++channel) {
    accumulator |= ((uint32_t)channels[channel] & 0x07FFUL) << accumulatorBits;
    accumulatorBits += 11;

    while (accumulatorBits >= 8) {
      payload[outputIndex++] = (uint8_t)(accumulator & 0xFF);
      accumulator >>= 8;
      accumulatorBits -= 8;
    }
  }
}

int main() {
for (int run=0; run<1000; run++) {
uint16_t channels[16]; uint8_t payload[22];
for (int i=0;i<16;i++) channels[i]=rcMicrosecondsToSbus(1000+(run*73+i*137)%1001);
packSbusChannels(channels,payload);
for (int i=0;i<16;i++) {
unsigned decoded=0;
for(int bit=0;bit<11;bit++) decoded |= ((payload[(i*11+bit)/8]>>((i*11+bit)%8))&1)<<bit;
assert(decoded==channels[i]);
unsigned us=(decoded*5)/8+875;
assert(us>=1000 && us<=2000);
}
}
assert(rcMicrosecondsToSbus(1000)==200);
assert(rcMicrosecondsToSbus(1500)==1000);
assert(rcMicrosecondsToSbus(2000)==1800);
}
