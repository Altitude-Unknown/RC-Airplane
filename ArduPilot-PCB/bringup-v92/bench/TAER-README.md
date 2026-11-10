# BOREALIS v92 TAER pass-through bench image

Prepared 2026-09-29 for the next lab session. **Built but not flashed or
hardware-tested.** The PCB remains on the normal diagnostic ArduPlane image.
This image is a temporary test aid for the board with its BMI088 IMU still
absent; never use it for flight.

The FlySky FS-iA6B i-BUS SERVO output is connected to J4 pin 28 (USART6
RX), pin 29 (5 V servo rail), and pin 30 (GND). `SERIAL2_PROTOCOL=23` was
set and verified on the PCB in the previous receiver test. The ESC/BEC
supplies the 5 V rail. Keep the propeller removed and motor secured.

| FlySky input | PCB PWM output | Bench range |
| --- | --- | --- |
| CH3 throttle | J4 THROTTLE, pin 1 | 1000–1150 µs |
| CH1 aileron | J4 AILERON, pin 4 | 1300–1700 µs |
| CH2 elevator | J4 ELEVATOR, pin 7 | 1300–1700 µs |
| CH4 rudder | J4 RUDDER, pin 10 | 1300–1700 µs |

AUX1 and AUX2 stay disabled. Passive captures showed CH5 and CH6 fixed
at 1000 µs even after transmitter menu changes; they are outside this
TAER-only test. The first four channels moved during the earlier input
check, and CH3 read about 1006 µs at low throttle.

All outputs start disabled. The firmware accepts only a special MAVLink
`DO_SET_SERVO` token on virtual channel 7: 1500 starts or renews the
test; 1000 stops it. It rejects ordinary servo-set commands in the
missing-IMU error loop. Starting requires at least one second of valid
receiver frames with CH3 at or below 1050 µs. The test is one-shot per
boot and has a 90-second absolute limit. It stops if valid receiver
frames cease for 250 ms, ArduPilot flags receiver failsafe, or USB
renewal ceases for 2 seconds. On stop, it commands throttle to 1000 µs
and centers the three servos for one second, then disables their PWM
channels. These safety paths are code-reviewed and compiled; they have
not yet been verified on the PCB.

The control program is `../taer_bench.py`. It checks both the TAER
firmware identity and missing-IMU status, waits for low throttle, sends
the start token, renews it during the session, and sends stop on exit.
It requires `--enable-outputs --prop-removed --motor-secured`; it will
run for 60 seconds by default. From the `bringup-v92` directory, the
lab sequence is:

```sh
/tmp/arduplane-build-venv/bin/python ../../../ardupilot/Tools/scripts/uploader.py \
  --port /dev/cu.usbmodem101 bench/arduplane-taer-bench.apj
/tmp/arduplane-build-venv/bin/python bench_mavlink.py /dev/cu.usbmodem101 \
  --seconds 8 --output /tmp/borealis-taer-preflight.json
/tmp/arduplane-build-venv/bin/python taer_bench.py /dev/cu.usbmodem101 \
  --enable-outputs --prop-removed --motor-secured \
  --seconds 60 --output /tmp/borealis-taer-test.json
/tmp/arduplane-build-venv/bin/python ../../../ardupilot/Tools/scripts/uploader.py \
  --port /dev/cu.usbmodem101 arduplane.apj
```

Use the actual USB port name if it changes. Keep QGroundControl closed
while the uploader or script owns the port. If anything moves
unexpectedly, lower throttle and disconnect ESC/BEC power.
Move the sticks by hand; do not use the FS-i6X Display channel-sweep
function while the ESC is powered.

Before starting, use read-only telemetry to confirm the TAER image
reports `BOREALIS TAER TEST: USB start required`, CH3 is low, and no
physical output moves. During the session, move each
stick separately and confirm the corresponding servo or propeller-free
motor responds. Afterward, restore `../arduplane.apj` with the USB
bootloader and verify the TAER status is gone. Normal diagnostic
firmware does not map these PWM pins to outputs.

Artifacts: `arduplane-taer-bench.apj` (board ID 65092, decoded image
size 1,329,852 bytes, SHA-256
`58a4d5f275a1476c6e0f763cfd210845adea362804b2d058ac64c291155103fc`),
`hwdef-taer.dat`, and `ardupilot-taer.patch`. The bootloader is the
same verified v92 bootloader.
