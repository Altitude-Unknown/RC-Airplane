# ArduPilot PCB Schematic Audit

**Date:** August 23, 2026  
**Schematic reviewed:** `Arduplane-FC v38.pdf`  
**Design notes reviewed:** `STM32H743_ArduPilot_Flight_Controller_2026-08-23.md`

## Audit conclusion

The STM32H743, BMI088, MS5611, USB-C, SWD, and external GPS/compass
architecture is a reasonable starting point. Schematic v38 is not ready for
PCB layout or fabrication. It is presently an incomplete MCU-and-sensor
development board rather than a complete ArduPlane flight controller.

The power architecture and complete MCU pin allocation should be finalized
before additional schematic wiring or PCB layout.

## RC receiver and Pixhawk communication decision

The Receiver V4 to flight-controller connection will use CRSF over a full,
uninverted 3.3 V TTL UART at 416666 baud.

The production harness should contain both UART directions:

```text
Flight controller TX  -> Receiver V4 RX / PB23
Flight controller RX  <- Receiver V4 TX / PB22
Flight controller GND -- Receiver V4 GND
Flight controller 5 V -> Receiver VIN only if the selected VIN accepts 5 V
```

TX and RX must be crossed. CTS and RTS are not required. A conventional
single-wire SBUS/PPM RCIN connection is not appropriate for the planned CRSF
interface.

For ArduPilot, reserve a full UART, preferably with suitable DMA support, and
configure its corresponding serial port as:

```text
SERIALx_PROTOCOL = 23
SERIALx_OPTIONS  = 0
RSSI_TYPE        = 3
```

The existing `rx_pixhawk_crsf` prototype sends packed RC-channel frames but
does not yet consume or implement traffic returned by the flight controller.
The hardware should nevertheless include both directions so that full-duplex
CRSF can be implemented and tested without changing the harness.

## Critical schematic findings

### 1. MCU VDD_1 appears unconnected

STM32H743 pin 11, `VDD_1`, appears unconnected in schematic v38 even though
the design notes state that all five VDD pins connect to +3V3.

Required correction:

- Connect pin 11 to +3V3.
- Add a dedicated 100 nF ceramic capacitor close to the pin.
- Confirm all five VDD/VSS pairs during ERC and layout review.

### 2. The VBAT input must not be treated as raw aircraft battery input

The present input feeds a TLV1117LV33 regulator. Its recommended input range
is 2 V to 5.5 V and its absolute maximum input is 6 V. A 2S or higher LiPo
would exceed the device rating and could destroy it.

If this connector is intended for regulated flight-controller power, rename
the net and connector to something explicit, for example:

```text
FC_5V_IN
Allowed input: 4.5 V to 5.5 V
```

If raw aircraft battery input is required, replace this architecture with an
appropriately rated buck supply and input protection. Raw battery voltage
should normally reach the MCU only through a protected ADC measurement
divider.

### 3. USB power net-name mismatch

The USB-C connector uses `USB_5V`, while the power circuit uses `VBUS`. These
are separate nets, so USB power does not presently reach the regulator.

Do not fix this by blindly merging the net names. First define the complete
power-mux or power-OR behavior, including prevention of backfeeding into the
computer, flight power source, and peripherals.

### 4. USB VBUS sensing is incomplete

PA9 is labeled `USB_VBUS_SENSE`, but the net is not connected to USB VBUS.
Add the circuit recommended for the selected STM32H743 USB operating mode and
silicon revision.

### 5. Flight-controller interfaces are still absent

Schematic v38 does not yet include:

- CRSF receiver UART and connector
- telemetry UART connector(s)
- PWM/servo outputs
- CAN transceiver and connector
- battery voltage and current sensing
- protected and current-rated peripheral 5 V power
- GPS power/protection details
- buzzer or safety/status indication
- SD storage, if onboard logging is required

## High-priority design findings

### HSE oscillator

The HSE crystal circuit is absent. Select the exact crystal, calculate its
load capacitors, follow the STM32 oscillator recommendations, and keep the
crystal network close to PH0/PH1. Complete this before PCB routing.

### Power architecture

Document and design the following before layout:

- regulated flight-power input range
- USB versus flight-power priority
- reverse-current and backfeed blocking
- reverse-polarity protection
- surge and transient protection
- brownout behavior
- 3.3 V regulator current and thermal margin
- external 5 V peripheral budget
- separation of servo power from flight-controller power
- grounding strategy for servos, radios, digital logic, and sensors

Create a current budget covering the STM32H743, both sensors, LEDs, pull-ups,
CRSF receiver, GPS/compass, CAN, and any other powered peripherals.

### Complete pin allocation before layout

Allocate every UART, timer/PWM channel, CAN interface, ADC input, SPI chip
select, interrupt, and DMA-sensitive function before routing the board. The
eventual ArduPilot `hwdef.dat` must exactly match these assignments.

### IMU redundancy

One BMI088 can support an experimental prototype, but it provides no inertial
redundancy. Consider a second independently connected IMU for a Pixhawk-class
controller, preferably on another SPI peripheral with independent chip-select
and interrupt signals.

### External I2C ownership

Define where the GPS/compass I2C pull-ups live, their voltage and resistance,
the expected cable length/capacitance, bus speed, and connector ESD
protection. Avoid unintentionally placing strong parallel pull-ups on both
boards.

## Sensor review

### BMI088

The basic SPI topology is reasonable:

- separate accelerometer and gyroscope chip selects
- shared SCK, MOSI, and MISO
- PS held low for gyroscope SPI mode
- separate interrupt signals

Firmware must account for BMI088 initialization behavior. The accelerometer
starts in I2C mode, requires an SPI transaction to enter SPI mode, and must be
explicitly enabled from suspend.

Use carefully placed local decoupling for VDD and VDDIO, even though both are
powered from 3.3 V.

### MS5611

The shown SPI connections appear consistent with the selected symbol,
including its paired CSB pads. The 3.3 V supply is within the sensor's stated
1.8 V to 3.6 V range.

### IST8310

The notes place the IST8310 on the external GPS/compass PCB, but an unconnected
IST8310 remains on the main schematic. Remove it or clearly mark it as
`DNP / REFERENCE ONLY` so it cannot enter the main-board BOM accidentally.

## Documentation discrepancies

- The notes say all MCU VDD pins connect to +3V3, but VDD_1 appears open.
- USB-powered boot is described as a goal, but the USB and power nets are not
  connected in v38.
- The proposed GPS/compass interface is described as one eight-pin connector,
  while v38 depicts multiple two-pin headers.
- The power section already exists in v38 but is not adequately documented in
  the session notes.
- Statements that portions are "substantially defined" should not be
  interpreted as approval for layout or fabrication.

Recommended status wording:

```text
Architecture draft / incomplete schematic
Not approved for layout or fabrication
```

## Recommended work order

1. Correct VDD_1 and run a complete MCU power-pin audit.
2. Define input-power requirements and redesign the full power tree.
3. Complete USB power selection, backfeed protection, VBUS sensing, and ESD.
4. Create the complete MCU peripheral and DMA allocation table.
5. Add CRSF, telemetry, PWM, CAN, ADC monitoring, and protected connectors.
6. Finalize the HSE oscillator.
7. Resolve GPS/compass connector and I2C pull-up ownership.
8. Decide whether a second IMU and SD logging are required.
9. Create the initial ArduPilot `hwdef.dat` and verify every assigned pin.
10. Run ERC, manufacturer-datasheet review, power-budget review, and a second
    independent schematic audit before PCB layout.

## Primary references checked

- STMicroelectronics, STM32H742xI/G and STM32H743xI/G datasheet:
  <https://www.st.com/resource/en/datasheet/stm32h743vi.pdf>
- Texas Instruments, TLV1117LV datasheet:
  <https://www.ti.com/lit/ds/symlink/tlv1117lv.pdf>
- Bosch Sensortec, BMI088 datasheet:
  <https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi088-ds001.pdf>
- TE Connectivity, MS5611-01BA03 product documentation:
  <https://www.te.com/en/product-MS561101BA03-50.html>
- ArduPilot, Crossfire and ELRS RC systems:
  <https://ardupilot.org/sub/docs/common-tbs-rc.html>

