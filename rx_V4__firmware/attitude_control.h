#pragma once
#include <math.h>
#include <stdint.h>

namespace AttitudeControl {
inline float bound(float value, float low, float high) {
  return value < low ? low : (value > high ? high : value);
}
inline float approach(float previous, float target, float step) {
  return previous + bound(target - previous, -step, step);
}
inline float stick(uint16_t us, uint16_t neutral, uint16_t low,
                   uint16_t high, uint16_t deadband) {
  float offset = (int)us - (int)neutral;
  if (fabsf(offset) <= deadband) return 0;
  const float range = offset > 0 ? high - neutral : neutral - low;
  if (range <= deadband) return 0;
  return bound((offset > 0 ? offset - deadband : offset + deadband) /
               (range - deadband), -1, 1);
}

struct RateResult { float output; float requested; bool limited; };
inline RateResult rate(float target, float measured, float ff, float kp, float ki,
                       float dt, float low, float high, float previous,
                       float scale, float &integrator, float iLimit,
                       bool integrate) {
  const float error = target - measured;
  const float base = ff * target + kp * error;
  const float candidate = integrate
      ? bound(integrator + ki * error * dt, -iLimit, iLimit) : integrator;
  const float requested = base + candidate;
  const float limited = bound(requested, low, high) * scale;
  // Preserve the old short output filter in seconds, plus a 6000 us/s slew.
  const float alpha = dt / (0.005385f + dt);
  const float output = bound(approach(previous, previous + alpha * (limited - previous),
                                      12.0f * dt), low, high);
  // Conditional integration uses the applied command, including ramp, slew,
  // filter and mechanical limits. Unwinding remains allowed.
  if (integrate && (error * (requested - output) <= 0.002f || error * integrator < 0))
    integrator = candidate;
  return {output, requested, fabsf(requested - output) > 0.002f};
}

// Rows transform the fixed PCB frame into an airframe frame. Gravity sets Z;
// the projection of PCB X defines forward (mounting yaw must be aligned).
struct Mount {
  float m[3][3] = {{1,0,0}, {0,1,0}, {0,0,1}};
  bool setGravity(float x, float y, float z) {
    const float n = sqrtf(x*x + y*y + z*z);
    const float yz = sqrtf(y*y + z*z);
    if (!isfinite(n) || n < 0.5f || yz < 0.25f) return false;
    m[2][0] = x/n; m[2][1] = y/n; m[2][2] = z/n;
    m[1][0] = 0; m[1][1] = z/yz; m[1][2] = -y/yz;
    m[0][0] = m[1][1]*m[2][2] - m[1][2]*m[2][1];
    m[0][1] = m[1][2]*m[2][0];
    m[0][2] = -m[1][1]*m[2][0];
    return true;
  }
  void rotate(float &x, float &y, float &z) const {
    const float a=x,b=y,c=z;
    x=m[0][0]*a+m[0][1]*b+m[0][2]*c;
    y=m[1][0]*a+m[1][1]*b+m[1][2]*c;
    z=m[2][0]*a+m[2][1]*b+m[2][2]*c;
  }
};
} // namespace AttitudeControl
