// SPDX-License-Identifier: GPL-3.0-or-later
// AI-assisted local bench driver; ST LSM6DSO32 datasheet DocID032891 Rev 1.
#include "AP_InertialSensor_LSM6DSO32.h"
#if defined(HAL_BOREALIS_V2_DIAGNOSTIC) && HAL_BOREALIS_V2_DIAGNOSTIC
#include <AP_HAL/AP_HAL.h>
#include <utility>

extern const AP_HAL::HAL &hal;
char AP_InertialSensor_LSM6DSO32::diagnostic[50] = "V2 IMU: probe not reached";

AP_InertialSensor_LSM6DSO32::AP_InertialSensor_LSM6DSO32(AP_InertialSensor &imu,
    AP_HAL::OwnPtr<AP_HAL::SPIDevice> dev, Rotation rotation)
    : AP_InertialSensor_Backend(imu), _dev(std::move(dev)), _rotation(rotation)
{
}

AP_InertialSensor_Backend *AP_InertialSensor_LSM6DSO32::probe(AP_InertialSensor &imu,
    AP_HAL::OwnPtr<AP_HAL::SPIDevice> dev, Rotation rotation)
{
    if (!dev) {
        return nullptr;
    }
    auto *sensor = NEW_NOTHROW AP_InertialSensor_LSM6DSO32(imu, std::move(dev), rotation);
    if (sensor == nullptr || !sensor->init()) {
        delete sensor;
        return nullptr;
    }
    return sensor;
}

bool AP_InertialSensor_LSM6DSO32::init()
{
    // Speaker test runs even when sensor probing fails.
    hal.gpio->pinMode(91, HAL_GPIO_OUTPUT);
    for (uint8_t chirp = 0; chirp < 2; chirp++) {
        for (uint16_t cycle = 0; cycle < 300; cycle++) {
            hal.gpio->write(91, 1);
            hal.scheduler->delay_microseconds(500);
            hal.gpio->write(91, 0);
            hal.scheduler->delay_microseconds(500);
        }
        hal.scheduler->delay(300);
    }
    WITH_SEMAPHORE(_dev->get_semaphore());
    _dev->set_read_flag(0x80);
    _dev->set_speed(AP_HAL::Device::SPEED_LOW);
    uint8_t id = 0;
    const bool read_ok = _dev->read_registers(0x0f, &id, 1);
    hal.util->snprintf(diagnostic, sizeof(diagnostic), "V2 IMU: SPI=%u WHO_AM_I=0x%02x", unsigned(read_ok), unsigned(id));
    if (!read_ok || id != 0x6c) {
        return false;
    }
    if (!_dev->write_register(0x12, 0x01)) {
        hal.util->snprintf(diagnostic, sizeof(diagnostic), "V2 IMU: reset write failed");
        return false;
    }
    hal.util->snprintf(diagnostic, sizeof(diagnostic), "V2 IMU: reset timeout/read failure");
    bool reset_done = false;
    for (uint8_t i = 0; i < 100; i++) {
        hal.scheduler->delay(1);
        uint8_t ctrl = 0;
        if (!_dev->read_registers(0x12, &ctrl, 1)) {
            return false;
        }
        if ((ctrl & 1) == 0) {
            reset_done = true;
            break;
        }
    }
    if (!reset_done || !_dev->setup_checked_registers(5, 20)) {
        return false;
    }
    hal.util->snprintf(diagnostic, sizeof(diagnostic), "V2 IMU: configuration write failed");
    // BDU + address increment; SPI-only; FIFO bypass; 833 Hz, +/-4 g and 2000 dps.
    if (!_dev->write_register(0x12, 0x44, true) ||
        !_dev->write_register(0x13, 0x04, true) ||
        !_dev->write_register(0x18, 0x02, true) ||
        !_dev->write_register(0x0a, 0x00) ||
        !_dev->write_register(0x10, 0x70, true) ||
        !_dev->write_register(0x11, 0x7c, true)) {
        return false;
    }
    const uint8_t registers[] = {0x12, 0x13, 0x18, 0x10, 0x11};
    for (const auto reg : registers) {
        uint8_t value = 0;
        const uint8_t expected = reg == 0x12 ? 0x44 : reg == 0x13 ? 0x04 :
                                 reg == 0x18 ? 0x02 : reg == 0x10 ? 0x70 : 0x7c;
        if (!_dev->read_registers(reg, &value, 1) || value != expected) {
            hal.util->snprintf(diagnostic, sizeof(diagnostic), "V2 IMU: reg %02x got %02x expected %02x", unsigned(reg), unsigned(value), unsigned(expected));
            return false;
        }
    }
    _dev->set_speed(AP_HAL::Device::SPEED_HIGH);
    hal.util->snprintf(diagnostic, sizeof(diagnostic), "V2 IMU: ID/config OK");
    return true;
}

void AP_InertialSensor_LSM6DSO32::start()
{
    // Private local device type; calibration must never be reused for another sensor.
    constexpr uint8_t local_devtype = 0xf0;
    if (!_imu.register_accel(accel_instance, 833, _dev->get_bus_id_devtype(local_devtype)) ||
        !_imu.register_gyro(gyro_instance, 833, _dev->get_bus_id_devtype(local_devtype))) {
        return;
    }
    set_accel_orientation(accel_instance, _rotation);
    set_gyro_orientation(gyro_instance, _rotation);
    _start_ms = AP_HAL::millis();
    hal.gpio->pinMode(91, HAL_GPIO_OUTPUT);
    hal.gpio->write(91, 0);
    _dev->register_periodic_callback(500, FUNCTOR_BIND_MEMBER(&AP_InertialSensor_LSM6DSO32::poll, void));
}

void AP_InertialSensor_LSM6DSO32::poll()
{
    uint8_t status = 0;
    if (!_dev->read_registers(0x1e, &status, 1)) {
        _inc_gyro_error_count(gyro_instance);
        _inc_accel_error_count(accel_instance);
        return;
    }
    if ((status & 3) != 0) {
        uint8_t data[14];
        if (!_dev->read_registers(0x20, data, sizeof(data))) {
            _inc_gyro_error_count(gyro_instance);
            _inc_accel_error_count(accel_instance);
            return;
        }
        auto axis = [&data](uint8_t offset) -> int16_t {
            return int16_t(uint16_t(data[offset]) | (uint16_t(data[offset + 1]) << 8));
        };
        if ((status & 2) != 0) {
            Vector3f gyro(axis(2), axis(4), axis(6));
            gyro *= radians(0.070f);
            _rotate_and_correct_gyro(gyro_instance, gyro);
            _notify_new_gyro_raw_sample(gyro_instance, gyro);
        }
        if ((status & 1) != 0) {
            Vector3f accel(axis(8), axis(10), axis(12));
            accel *= GRAVITY_MSS * 0.000122f;
            _rotate_and_correct_accel(accel_instance, accel);
            _notify_new_accel_raw_sample(accel_instance, accel);
        }
        _publish_temperature(accel_instance, 25.0f + axis(0) / 256.0f);
    }
    AP_HAL::Device::checkreg reg;
    if (!_dev->check_next_register(reg)) {
        _inc_gyro_error_count(gyro_instance);
        _inc_accel_error_count(accel_instance);
    }
}

bool AP_InertialSensor_LSM6DSO32::update()
{
    update_accel(accel_instance);
    update_gyro(gyro_instance);
    return true;
}
#endif
