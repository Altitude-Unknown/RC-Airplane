> Current installed firmware is now BOREALISv2Servo, with six PWM outputs.
> See [servo-enabled/README.md](servo-enabled/README.md) for the current
> output mapping and validation. Sensor-only firmware and tests below are
> preserved as the earlier bring-up record.

# V2 LSM6DSO32 board tests — 2026-10-09

## Current result

Bootloader and custom bench ArduPlane firmware are loaded and verified.
After the user reflowed the IMU, cleaned the PCB and allowed it to dry/cool,
IMU initialization succeeds and all three gyro axes respond to movement.
Accelerometer, gyro and barometer health stayed true throughout both captures.
Speaker passed the audible startup test again. Earlier failure diagnostics
below describe the board before reflow and are preserved for comparison.
Board remained disarmed. Servo signals remain inputs with pull-downs;
no PWM is configured. Mounting orientation and calibration remain unverified;
this bench firmware is not flight-ready.

## Successful post-reflow checks

- Stationary capture: 20 seconds; acceleration magnitude approximately
  1.025 g, gyro near zero. Nonzero INS_ACC_ID/INS_GYR_ID 15729170 and
  BARO1_DEVID 721162. No sensor initialization errors observed.
- Live barometer: about 840.86 hPa and 22.4–22.7 C during stationary capture.
- Motion capture: 45 seconds, 440 fresh scaled IMU samples. Gyro X spanned
  -198 to +267 degrees/s, Y -152 to +157 degrees/s, Z -68 to +28 degrees/s.
  Acceleration X/Y varied through positive and negative values with tilting.
- Accelerometer, gyro and barometer remained healthy in all captured status
  samples, and the board remained disarmed throughout.
- Speaker: user heard both startup beeps after reconnecting the dry board.
- Firmware remained the verified GPIO-probe diagnostic build; no further
  firmware change was needed after reflow. Successful initialization requires
  WHO_AM_I 0x6c and correct configuration-register readbacks; successful boot
  does not separately telemeter those raw register bytes.
- Pre-arm messages request accelerometer calibration and report missing
  compass/home/logging/RC readiness; those checks were not bypassed.
- Evidence: post-reflow-sensors.json, post-reflow-motion.json,
  post-reflow-summary.json and current test-summary.json.

## Schematic confirmation

User identifies LSM6DSO32TR and confirms the remaining MCU/pinout match v92.
The sensor and STM32 screenshot sections confirm:

| IMU signal | STM32 signal | MCU LQFP100 pin |
| --- | --- | --- |
| SCK/SCL, sensor pin 13 | PD3 / SPI2_SCK | 83 |
| SDO, sensor pin 1 | PC2_C / SPI2_MISO | 17 |
| SDA/SDI, sensor pin 14 | PC3_C / SPI2_MOSI | 18 |
| CS, sensor pin 12 | PD5 / GYRO_CS | 86 |

IMU INT1/2 go to PE2/PE3 but this polling driver does not use interrupts.
MS5611 uses SPI1 PA5/PA6/PA7 and PA4 chip select. MCU STM32H743VIT6,
8 MHz crystal. IMU SDX/SCX tied to GND is a valid Mode 1 connection.
Source: https://www.st.com/resource/en/datasheet/lsm6dso32.pdf

## Programming

- STM32 ROM DFU 0483:df11, serial 200364500000, 2 MiB flash detected.
- Full original flash saved in preflash-2026-10-09.bin; all bytes were 0xff.
- Corrected v92 bootloader, 18,564 bytes, programmed at 0x08000000.
  Exact readback SHA-256:
  f8509c06d59ff5b61ab32d477b180d936bea55fc2adc7908ff0b18cb4c673ed6.
- Latest application is 1,312,352 bytes at 0x08020000. Build passed with
  Arm GNU 10.2.1; programming and bootloader CRC verification passed.
  See gpio-spi-upload.log, plane-build-gpio-spi.log and test-summary.json.
- Target BOREALISv2Diagnostic, private board ID 65092. Source base
  Plane-4.7.1, dbe792162d06cab66c3475fd5556bf7a120f119e.
- New AI-assisted backend and error-loop diagnostics are guarded by
  HAL_BOREALIS_V2_DIAGNOSTIC. Source snapshot and generated-hwdef.h are saved.

## Before reflow: sensor and speaker results

- Speaker: PC11/GPIO91 drives two nominal 1 kHz chirps before sensor
  probing, each 300 ms, separated by 300 ms. User heard both after power
  cycle. Frequency is nominal, not measured with an instrument.
- Pressure sensor: latest 10-second capture has 88 live measurements,
  841.04–841.14 hPa and 26.16–26.22 C. Earlier captures were near 841.2 hPa
  and 25.5 C. Basic SPI communication and live measurement confirmed.
  Normal flight-stack calibration/health remains incomplete while INS
  blocks startup. The diagnostic error loop updates barometer measurements
  without clearing the INS configuration error.
- IMU: hardware SPI at a confirmed 100 kHz returns 0x80 on all eight
  WHO_AM_I reads, expected 0x6c. CTRL1/2/3 read 0x00/0x00/0x00.
- MCU SYSCFG_PMCR = 0x03000000: PC2/PC3 analog switches are closed,
  connecting PC2_C/PC3_C to their digital pin functions.
- Independent slow GPIO SPI reads on the confirmed pins return 0x00 in
  mode 0 and mode 3. With MISO pull-up, read is 0xff; with pull-down, 0x00.
  Pin modes, pulls and output state are restored after this read-only probe.
  Inference: MISO is not being actively driven. Potential causes include
  missing IMU supply, open SDO/CS connection, assembly/orientation fault,
  or a faulty device. These are hypotheses, not confirmed hardware faults.
- Accel/gyro zero telemetry is invalid while initialization fails. Mounting
  orientation, calibration and motion tests remain pending.
- Next physical check: USB-powered voltage at supply-side pads of C2
  (VDD) and C24 (VDDIO), expected approximately 3.3 V relative to ground.
  If both supplies are correct, check unpowered SDO/CS continuity and IMU
  placement/orientation/soldering.

## Evidence and earlier iterations

check_sensors.py records telemetry and requests message streams. It does
not change parameters, arm, or command servo outputs.
Latest evidence: gpio-spi-sensors.json and test-summary.json.

Initial driver images and exact DFU application readback are in
initial-driver/. First detailed diagnostics are in fast-spi-diagnostics/.
The attempted first SPI slowdown did not regenerate the hardware definition;
that test still ran at 1 MHz and is archived in stale-hwdef-build/. Earlier
claims of 100 kHz for slow-spi-baro-sensors.json are invalid. A full explicit
configure/rebuild generated 100 kHz as confirmed in generated-hwdef.h and
configure-100khz.log; confirmed-100khz-sensors.json and gpio-spi-sensors.json
are the actual slower-clock tests.

source-changes.patch includes the pre-existing v92 bench error-loop patch
in AP_BoardConfig as well as this task's guarded V2 diagnostic additions.
Existing unrelated changes were preserved.

## User supply measurements

User measured 3.28 V at both C2 (VDD) and C24 (VDDIO). Supply voltage at
these capacitors is confirmed; this does not yet verify solder continuity
to the IMU pads. Next check, with all power disconnected: IMU SDO pin 1
to STM32 PC2_C pin 17, and IMU CS pin 12 to STM32 PD5 pin 86.
