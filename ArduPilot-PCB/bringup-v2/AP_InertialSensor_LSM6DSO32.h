#pragma once

#include "AP_InertialSensor_Backend.h"

// Local bench-only driver. Polling, axis mounting and flight timing are unvalidated.
#if defined(HAL_BOREALIS_V2_DIAGNOSTIC) && HAL_BOREALIS_V2_DIAGNOSTIC
#include <AP_HAL/SPIDevice.h>

class AP_InertialSensor_LSM6DSO32 : public AP_InertialSensor_Backend {
public:
    static char diagnostic[50];
    static char diagnostic_extra[50];
    static char diagnostic_gpio[50];
    static AP_InertialSensor_Backend *probe(AP_InertialSensor &imu,
                                          AP_HAL::OwnPtr<AP_HAL::SPIDevice> dev,
                                          Rotation rotation);
    void start() override;
    bool update() override;
private:
    AP_InertialSensor_LSM6DSO32(AP_InertialSensor &imu,
                              AP_HAL::OwnPtr<AP_HAL::SPIDevice> dev,
                              Rotation rotation);
    bool init();
    void poll();
    AP_HAL::OwnPtr<AP_HAL::SPIDevice> _dev;
    Rotation _rotation;
    uint32_t _start_ms {};
    bool _speaker_high {};
};
#endif
