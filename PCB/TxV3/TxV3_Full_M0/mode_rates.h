#pragma once

#include "aux_channels.h"

// Model reserved[5] bits4..5: 0=off, 1=full surfaces at CH5 low,
// 2=full surfaces at CH5 high. Value3 is invalid and leaves rates unchanged.
namespace ModeRates {
inline bool fullSurfaces(uint8_t config, uint8_t auxFlags, bool student) {
  const uint8_t buttonMode = AuxChannels::mode(config, 0);
  if (student || buttonMode == 0 || !(auxFlags & AuxChannels::MARKER)) return false;
  const uint8_t profile = (config >> 4) & 3;
  const bool high = (auxFlags & AuxChannels::CH5) != 0;
  return (profile == 1 && !high) || (profile == 2 && high);
}
} // namespace ModeRates
