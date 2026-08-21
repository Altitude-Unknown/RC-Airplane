#pragma once

#include <Arduino.h>
#include <HID.h>

// Four signed 16-bit joystick axes plus eight buttons. The descriptor is
// installed before setup() so the SAMD21 enumerates as a CDC + HID composite
// USB device. Reports are sent only while the transmitter is in simulator mode.
static const uint8_t TXV3_HID_REPORT_DESCRIPTOR[] PROGMEM = {
  0x05, 0x01,                    // Usage Page (Generic Desktop)
  0x09, 0x04,                    // Usage (Joystick)
  0xA1, 0x01,                    // Collection (Application)
  0x85, 0x04,                    //   Report ID (4)
  0x05, 0x01,                    //   Usage Page (Generic Desktop)
  0x09, 0x30,                    //   Usage (X: aileron)
  0x09, 0x31,                    //   Usage (Y: elevator)
  0x09, 0x32,                    //   Usage (Z: rudder)
  0x09, 0x35,                    //   Usage (Rz: throttle)
  0x16, 0x01, 0x80,              //   Logical Minimum (-32767)
  0x26, 0xFF, 0x7F,              //   Logical Maximum (32767)
  0x75, 0x10,                    //   Report Size (16)
  0x95, 0x04,                    //   Report Count (4)
  0x81, 0x02,                    //   Input (Data, Variable, Absolute)
  0x05, 0x09,                    //   Usage Page (Button)
  0x19, 0x01,                    //   Usage Minimum (1)
  0x29, 0x08,                    //   Usage Maximum (8)
  0x15, 0x00,                    //   Logical Minimum (0)
  0x25, 0x01,                    //   Logical Maximum (1)
  0x75, 0x01,                    //   Report Size (1)
  0x95, 0x08,                    //   Report Count (8)
  0x81, 0x02,                    //   Input (Data, Variable, Absolute)
  0xC0                           // End Collection
};

struct __attribute__((packed)) TxV3HidReport {
  int16_t aileron;
  int16_t elevator;
  int16_t rudder;
  int16_t throttle;
  uint8_t buttons;
};

class TxV3UsbHid {
public:
  TxV3UsbHid() : descriptor(TXV3_HID_REPORT_DESCRIPTOR, sizeof(TXV3_HID_REPORT_DESCRIPTOR)) {
    HID().AppendDescriptor(&descriptor);
  }

  void send(uint16_t rudderUs, uint16_t aileronUs, uint16_t elevatorUs,
            uint16_t throttleUs, uint8_t buttons = 0) {
    TxV3HidReport report = {
      pulseToAxis(aileronUs),
      pulseToAxis(elevatorUs),
      pulseToAxis(rudderUs),
      pulseToAxis(throttleUs),
      buttons
    };
    HID().SendReport(4, &report, sizeof(report));
  }

private:
  HIDSubDescriptor descriptor;

  static int16_t pulseToAxis(uint16_t pulseUs) {
    int32_t bounded = constrain((int32_t)pulseUs, 1000L, 2000L);
    return (int16_t)map(bounded, 1000L, 2000L, -32767L, 32767L);
  }
};

static TxV3UsbHid txv3UsbHid;

