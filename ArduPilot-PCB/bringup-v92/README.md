# Arduplane-FC v92 bring-up

Date: 2026-09-28. Board assembled without BMI088 IMU or MS5611 barometer.
Schematic: `../Arduplane-FC v92.pdf`.

## Confirmed

- User reports power LED L2 illuminated and measures 3.28 V on the 3.3 V rail.
- User tested ESC/BEC 5 V into the servo rail with USB disconnected and
  measured approximately 3.3 V at the regulator output. This verifies
  that supply path under the tested bench load, not ESC signal control.
- STM32 ROM USB DFU enumerated as `0483:df11`, product `DFU in FS Mode`,
  serial `200364500000`.
- DFU advertises 16 x 128 KiB internal flash sectors (2 MiB).
- Read all 2 MiB into `original-flash.bin`; every byte was `0xff`.
- Original flash SHA-256:
  `4bda3a28f4ffe603c0ec1258c0034d65a1a0d35ab7bd523a834608adabf03cc5`.
- Custom bootloader compiled, 18,564 bytes, initial SP `0x20000600`,
  reset vector `0x080002e1`.
- DFU reported bootloader download successful at `0x08000000`.
  The leave request ended with a get_status error. After a normal USB
  power cycle, the custom bootloader enumerated as `BOREALISv92-BL` at
  `/dev/cu.usbmodem1101` and responded to the ArduPilot uploader.
- Bootloader identity: protocol 5, board 65092 / revision 0,
  MCU family STM32H743/753/750 revision V,
  silicon serial `005300393034510c33393834`, source hash
  `dbe792162d06cab6`, application flash capacity 1,703,936 bytes.
- Initial firmware incorrectly mapped L3 to PC10 and the button to PA15.
  Enlarged v92 schematic inspection confirms BLINK/L3 = PC12 (pin 80),
  ARMING_BUTTON = PC10 (pin 78), BUZZER = PC11 (pin 79).
  Application and bootloader have been corrected, rebuilt and flashed.
  The user's L3 reflow did not change the initial symptom.
- Initial ArduPlane compiled successfully: 1,311,948 bytes flash use and
  391,984 bytes free; packaged image size 1,311,952 bytes.
- Uploaded `arduplane.apj` through the custom bootloader. Programming
  and CRC verification both completed successfully; uploader exited 0.
- Following a normal USB power cycle, application USB enumerated as
  `BOREALISv92` at `/dev/cu.usbmodem1101`.
- Read-only MAVLink check passed: 42 heartbeats in 15.18 seconds,
  firmware `ArduPlane V4.7.1 (dbe79216)`, ChibiOS `d103983f`, and all
  879 advertised parameters downloaded. Board remained disarmed.
- Observed `Config Error: Baro: unable to initialise driver` and
  `Config Error: fix problem then reboot`. This is expected with A1
  intentionally absent. Startup is in the diagnostic error loop, not
  normal flight operation. IMU initialization has not been validated.
- Opened installed QGroundControl 5.1. `lsof` confirms QGroundControl
  has `/dev/cu.usbmodem1101` open. User confirmed the vehicle is connected
  and the expected barometer/configuration error is displayed.
- Corrected LED build: 1,311,952 bytes application flash use, 391,984
  bytes free. Combined bootloader/application image: 1,443,024 bytes
  starting at `0x08000000`, ending before parameter storage at `0x081c0000`.
- Corrected image written via DFU, then read back in full. Every byte
  matched. SHA-256:
  `acc0884844424ba2527a26c1ddb4c88e0f38aabf889a37c4144445060692058e`.
- After power-cycling, user confirmed L3 is blinking. This validates the
  corrected PC12 LED mapping on hardware; the initial symptom was caused
  by the firmware assignment, not an established LED assembly fault.
- Post-correction MAVLink check passed: 38 heartbeats in 15.08 seconds,
  all 879 parameters received, firmware identity unchanged, board disarmed,
  and only the expected missing-barometer configuration messages observed.
  QGroundControl was reopened after the diagnostic released the USB port.

## Barometer installation check (2026-09-29)

- User installed the MS5611. After power-up, the previous barometer error
  disappeared. A direct MAVLink read reported `Config Error: INS: unable to
  initialise driver`, consistent with the still-absent BMI088 IMU.
- `BARO1_DEVID` is nonzero (`721162`, hex `0x000B010A`); the absolute-pressure
  sensor is reported present and enabled. The MS5611 driver registers a
  sensor only after its SPI calibration PROM read and CRC check pass. This
  confirms basic SPI communication and sensor recognition.
- Absolute-pressure health remains false. All 43 `SCALED_PRESSURE` samples
  obtained in the configuration-error loop had zero pressure and temperature.
  ArduPilot stops normal startup at the missing IMU, before the regular
  barometer update/calibration loop runs. These zeros do not establish a
  barometer fault. A later bench-only image produced live pressure and
  temperature readings; normal flight-stack calibration still awaits the
  IMU's installation and successful initialization.
- The read-only capture helper is `check_baro.py`; evidence JSON is in
  `/tmp/borealis-baro-params.json` and `/tmp/borealis-baro-readings.json`
  on the test laptop.

## Next bench checks

A separate bench-only ArduPlane variant read live barometer pressure and
temperature and exercised all six bounded PWM outputs while the IMU was
absent. Servo outputs 2–6 moved servos, and output 1 drove the connected
ESC and propeller-free motor. The normal ArduPlane image was restored and
verified after testing. See `bench/README.md` for the pin map, evidence,
and safeguards.
These checks verify the output hardware path. The restored diagnostic
image deliberately configures the PWM pins as inputs; regular ArduPlane
output control still needs a production hwdef after the IMU is installed
and its orientation is verified.
The Spektrum receiver pictured by the user appears to be an AR6210;
its documented outputs are individual servo channels rather than a
combined RC UART stream. Its BIND/DATA port is not a documented RC
channel serial output.
A bound FlySky FS-iA6B was then connected to USART6 via its i-BUS SERVO
port. With `SERIAL2_PROTOCOL=23`, ArduPilot decoded 14 channel slots;
the four primary channels changed with stick movement, and CH3 returned
to 1006 us at low throttle. This confirms the serial receiver input path.
The diagnostic image was restored after the test, and its `RC_CHANNELS`
telemetry still showed the receiver connected. Normal flight-stack and
failsafe behavior remain untested until the IMU is installed.

## Firmware source

Local checkout: `../../../ardupilot` relative to this directory
(`Codex-Projects/ardupilot`).

- Release: `Plane-4.7.1`.
- Commit: `dbe792162d06cab66c3475fd5556bf7a120f119e`.
- Local branch: `borealis-v92-bringup`.
- Board: `libraries/AP_HAL_ChibiOS/hwdef/BOREALISv92/`.
- Board ID: 65092, private experimental value, not allocated upstream.
- Compiler: Arm GNU 10.2.1, ArduPilot's macOS 10-2020-q4-major package.
- AI-assisted local board definition; no upstream contribution submitted.

The diagnostic target uses the 8 MHz crystal shown on the schematic,
USB on PA11/PA12, status LED L3 on PC12, and the documented SPI buses.
USART1 PB6/PB7 is shared by J5 and the GPS connector; two transmitters
cannot independently drive that RX net. USART6 uses PC6/PC7.

Servo signal pins PE14, PE13, PE11, PE9, PD12, PD13 are inputs with
pull-downs. No PWM or arming-button function is configured. Buzzer and
health LEDs are held off. UART1/6 protocols default to unused value 0.
No external ADC input or SD card is configured.

Rechecked v92 signal assignments (MCU LQFP100 pin numbers):

| Signal | GPIO | MCU pin |
| --- | --- | --- |
| BLINK / L3 | PC12 | 80 |
| BUZZER | PC11 | 79 |
| ARMING_BUTTON | PC10 | 78 |
| THROTTLE | PE14 | 44 |
| AILERON | PE13 | 43 |
| ELEVATOR | PE11 | 41 |
| RUDDER | PE9 | 39 |
| AUX1 | PD12 | 59 |
| AUX2 | PD13 | 60 |

The earlier LED pin mapping was a firmware transcription error. The
servo pin assignments were rechecked and were already correct.

BMI088 and MS5611 drivers are included, with normal missing-sensor
checks. A configuration error is expected while sensors are absent;
ArduPilot's error loop continues servicing MAVLink. IMU rotation is
an unverified placeholder and must be established before sensor use.

## Remaining checks

- Investigate software-reboot USB behavior; physical power-cycle startup
  worked, while DFU leave and uploader reboot did not enumerate immediately.
- Check remaining power rails/VCAP on hardware.
- IMU installation, sensor orientation and calibration, live barometer
  measurements, I/O tests, and electrical validation are still required;
  this is not flight-ready firmware.

## Recovery

Reliable DFU entry observed on this board: disconnect USB, hold SWBOOT,
reconnect USB, wait about two seconds, then release SWBOOT.
The SWBOOT plus SWRESET sequence did not reliably enumerate DFU during
this session; cold power-on with SWBOOT held did.
For normal application boot, release both buttons and power-cycle USB.
The ROM bootloader is not erased by writing application flash.

Temporary build tools and logs are under `/tmp/arduplane-*` and
`/tmp/gcc-arm-none-eabi-10-2020-q4-major`.

## Saved artifacts

- `arduplane.apj`: application firmware for this board's ArduPilot bootloader.
- `arduplane_with_bl.hex`: combined bootloader/application Intel HEX image.
- `arduplane_with_bl.bin`: combined raw image for DFU at `0x08000000`.
- `BOREALISv92_bl.bin`: bootloader only, flash base `0x08000000`.
- `hwdef.dat`, `hwdef-bl.dat`: exact board definitions used for this build.
- `plane-build.log`, `upload.log`, `sha256.json`: build/upload evidence and hashes.
- `bootloader-build.log`, `readback.log`, `ledfix-flash-verification.json`,
  `ledfix-flash-readback.bin`: corrected bootloader build and exact flash verification.
- `mavlink-check.json`: version, heartbeat, status text, and downloaded parameters.
- `read_mavlink.py`: read-only diagnostic script; requires `pymavlink`/`pyserial`.

The packaged files are for this diagnostic v92 target only. They do not
configure flight controls or validate the sensors. For this bench session,
USB uses MAVLink 2 (`SERIAL0_PROTOCOL=2`). No parameters were changed by
the diagnostic script.

`initial-build-wrong-led-pin/` archives the superseded images and initial
test results. Its firmware drives the wrong pin for L3; do not use it for
new tests. The top-level firmware artifacts contain the corrected mapping.
