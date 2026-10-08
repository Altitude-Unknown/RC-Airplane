#pragma once
#include <Arduino.h>

// Small open-drain software I2C master for experimental sensors. Every complete
// register transaction has a 5 ms deadline, including clock stretching. Servo
// and radio interrupts stay enabled. Never drives a bus line HIGH.
class BoundedI2c {
 public:
  BoundedI2c(uint8_t sda, uint8_t scl) : sda_(sda), scl_(scl) {}
  void begin() { release(); }
  bool writeRegister(uint8_t address, uint8_t reg, uint8_t value) {
    beginDeadline();
    bool ok = start() && send(address << 1) && send(reg) && send(value);
    return finish(ok);
  }
  bool readRegisters(uint8_t address, uint8_t reg, uint8_t *data, uint8_t count) {
    if (!count) return false;
    beginDeadline();
    bool ok = start() && send(address << 1) && send(reg) &&
              start() && send((address << 1) | 1);
    for (uint8_t i = 0; ok && i < count; ++i) ok = receive(data[i], i + 1 < count);
    return finish(ok);
  }
  bool probe(uint8_t address) {
    beginDeadline();
    return finish(start() && send(address << 1));
  }
 private:
  uint8_t sda_, scl_;
  uint32_t started_ = 0;
  static void low(uint8_t pin) { digitalWrite(pin, LOW); pinMode(pin, OUTPUT); }
  static void high(uint8_t pin) { pinMode(pin, INPUT_PULLUP); }
  static void pause() { delayMicroseconds(3); }
  bool expired() const { return (uint32_t)(micros() - started_) >= 5000; }
  void release() { high(sda_); high(scl_); }
  void beginDeadline() { started_ = micros(); }
  bool raiseClock() {
    high(scl_);
    while (digitalRead(scl_) == LOW) if (expired()) return false;
    pause();
    return !expired();
  }
  bool start() {
    high(sda_); pause();
    if (!raiseClock() || digitalRead(sda_) == LOW) return false;
    low(sda_); pause(); low(scl_); pause();
    return !expired();
  }
  bool finish(bool ok) {
    low(scl_); low(sda_); pause();
    bool clockOk = raiseClock();
    high(sda_); pause();
    bool stopped = digitalRead(sda_) == HIGH;
    release();
    return ok && clockOk && stopped && !expired();
  }
  bool send(uint8_t value) {
    for (uint8_t mask = 0x80; mask; mask >>= 1) {
      if (value & mask) high(sda_); else low(sda_);
      pause(); if (!raiseClock()) return false;
      low(scl_); pause();
    }
    high(sda_); pause(); if (!raiseClock()) return false;
    bool ack = digitalRead(sda_) == LOW;
    low(scl_); pause();
    return ack && !expired();
  }
  bool receive(uint8_t &value, bool ack) {
    value = 0; high(sda_);
    for (uint8_t bit = 0; bit < 8; ++bit) {
      pause(); if (!raiseClock()) return false;
      value = (value << 1) | (digitalRead(sda_) == HIGH);
      low(scl_); pause();
    }
    if (ack) low(sda_); else high(sda_);
    pause(); if (!raiseClock()) return false;
    low(scl_); pause(); high(sda_);
    return !expired();
  }
};
