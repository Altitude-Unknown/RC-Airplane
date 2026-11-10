# STM32H743 ArduPilot Flight Controller -- Design Session Notes

**Date:** August 23, 2026

This file captures the flight-controller PCB design work from today's
conversation so the project can be resumed later.

## Project goal

Build a custom ArduPilot/ArduPlane flight controller around the
**STM32H743VIT6 (LQFP100)** that can function similarly to a
Pixhawk-class controller and communicate with Mission Planner.

## Major components selected

-   MCU: STM32H743VIT6
-   IMU: Bosch BMI088
-   Barometer: TE Connectivity MS561101BA03-50 (MS5611)
-   External GPS: u-blox M9 family
-   External magnetometer: IST8310, to be placed on the separate
    GPS/compass PCB
-   USB: USB-C, USB 2.0 device connection

------------------------------------------------------------------------

# 1. BMI088 IMU

The BMI088 is connected using SPI2.

## BMI088 power

-   VDD pin 3 -\> +3V3
-   VDDIO pin 11 -\> +3V3
-   GNDA pin 4 -\> GND
-   GNDIO pin 6 -\> GND
-   PS pin 7 -\> GND for SPI mode
-   NC pin 2 -\> no connection

Decoupling: - 100 nF ceramic on the local 3.3 V supply - 1 uF ceramic
local bulk capacitor

## BMI088 SPI signals

-   SCL/SCK pin 8 -\> SPI2_SCK
-   SDA/SDI pin 9 -\> SPI2_MOSI
-   SDO1 pin 15 -\> SPI2_MISO
-   SDO2 pin 10 -\> SPI2_MISO
-   CSB1 pin 14 -\> ACCEL_CS
-   CSB2 pin 5 -\> GYRO_CS

SDO1 and SDO2 share the SPI MISO line because the accelerometer and gyro
have independent chip-select lines.

## BMI088 interrupts

All four interrupt signals were brought to the MCU for flexibility:

-   INT1 pin 16 -\> IMU_INT1_ACCEL
-   INT2 pin 1 -\> IMU_INT2_ACCEL
-   INT3 pin 12 -\> IMU_INT3_GYRO
-   INT4 pin 13 -\> IMU_INT4_GYRO

## STM32 connections for BMI088

-   PE2, MCU pin 1 -\> IMU_INT1_ACCEL
-   PE3, MCU pin 2 -\> IMU_INT2_ACCEL
-   PE4, MCU pin 3 -\> IMU_INT3_GYRO
-   PE5, MCU pin 4 -\> IMU_INT4_GYRO
-   PC2_C, MCU pin 17 -\> SPI2_MISO
-   PC3_C, MCU pin 18 -\> SPI2_MOSI
-   PD3, MCU pin 84 -\> SPI2_SCK
-   PD4, MCU pin 85 -\> ACCEL_CS
-   PD5, MCU pin 86 -\> GYRO_CS

------------------------------------------------------------------------

# 2. MS5611 Barometer

The MS5611 is connected using SPI1.

## MS5611 connections

-   VDD pin 1 -\> +3V3
-   PS pin 2 -\> GND for SPI
-   GND pin 3 -\> GND
-   CSB pins 4/5 -\> BARO_CS
-   SDO pin 6 -\> SPI1_MISO
-   SDI/SDA pin 7 -\> SPI1_MOSI
-   SCLK pin 8 -\> SPI1_SCK

Decoupling: - One 100 nF ceramic capacitor from VDD to GND, placed close
to the sensor.

## STM32 connections for MS5611

-   PA4, MCU pin 28 -\> BARO_CS
-   PA5, MCU pin 29 -\> SPI1_SCK
-   PA6, MCU pin 30 -\> SPI1_MISO
-   PA7, MCU pin 31 -\> SPI1_MOSI

------------------------------------------------------------------------

# 3. External GPS / Compass

The IST8310 magnetometer will **not** be installed on the main
flight-controller PCB. It will be placed on a separate PCB with the
u-blox M9 GPS.

The main flight controller therefore provides an external GPS/compass
connector.

## Proposed 8-pin GPS/compass header

1.  +5V
2.  GND
3.  USART1_RX
4.  USART1_TX
5.  I2C1_SCL
6.  I2C1_SDA
7.  GPS_PPS
8.  GND

The external GPS/compass PCB should regulate the supplied 5 V to
whatever voltage the M9 and IST8310 require.

## STM32 assignments

-   PB7 pin 93 -\> USART1_RX
-   PB6 pin 92 -\> USART1_TX
-   PB8 pin 95 -\> I2C1_SCL
-   PB9 pin 96 -\> I2C1_SDA
-   PC13 pin 7 -\> GPS_PPS

------------------------------------------------------------------------

# 4. STM32H743VIT6 Core Power

The MCU is the STM32H743VIT6 in the LQFP100 package.

## Digital power

All VDD pins connect to +3V3:

-   Pin 11 VDD_1
-   Pin 27 VDD_2
-   Pin 50 VDD_3
-   Pin 75 VDD_4
-   Pin 100 VDD_5

Each VDD gets a local 100 nF ceramic capacitor.

A 4.7 uF bulk capacitor is also placed on the MCU 3.3 V rail.

## Grounds

-   Pin 10 VSS_1 -\> GND
-   Pin 26 VSS_2 -\> GND
-   Pin 49 VSS_3 -\> GND
-   Pin 74 VSS_4 -\> GND
-   Pin 99 VSS_5 -\> GND

## VCAP

These must NOT be connected to +3V3.

-   Pin 48 VCAP_1 -\> 2.2 uF -\> GND
-   Pin 73 VCAP_2 -\> 2.2 uF -\> GND

The VCAP capacitors should be placed very close to their corresponding
MCU pins.

## Analog supply

-   Pin 19 VSSA -\> GND
-   Pin 20 VREF+ -\> filtered analog 3.3 V
-   Pin 21 VDDA -\> filtered analog 3.3 V

The analog rail is created as:

+3V3 -\> ferrite bead L1 -\> +3V3A

+3V3A supplies VDDA and VREF+.

Local decoupling: - 100 nF to GND - 1 uF to GND

Suggested L1: ferrite bead around 600 ohms @ 100 MHz with low DC
resistance and adequate current rating.

## VBAT

-   VBAT pin 6 -\> +3V3

No backup battery is planned for the first prototype.

------------------------------------------------------------------------

# 5. BOOT, Reset and SWD

## BOOT0

-   BOOT0 pin 94 -\> 10 kOhm pull-down -\> GND
-   Provide an accessible BOOT0 test point.

## NRST

-   NRST pin 14
-   10 kOhm pull-up to +3V3
-   100 nF capacitor to GND
-   Connect NRST to the SWD programming header.

## SWD header

Provide:

-   SWDIO -\> PA13 pin 72
-   SWCLK -\> PA14 pin 76
-   NRST
-   +3V3
-   GND (two grounds are acceptable on the selected 2x3 header)

------------------------------------------------------------------------

# 6. Main Oscillator

Reserved MCU pins:

-   PH0-OSC_IN pin 12 -\> OSC_IN
-   PH1-OSC_OUT pin 13 -\> OSC_OUT

Plan is to use an approximately 8 MHz HSE crystal appropriate for
ArduPilot. The crystal and load capacitors have not yet been selected;
capacitor values should be calculated from the exact crystal
specification.

------------------------------------------------------------------------

# 7. USB

MCU USB assignments:

-   PA12 pin 71 -\> USB_D+
-   PA11 pin 70 -\> USB_D-
-   PA9 pin 68 -\> USB_VBUS_SENSE

## USB-C connector

Selected connector symbol: UJ20-C-H-G-SMT-1-P16-TR.

Connections:

-   VBUS pins -\> USB_5V
-   A6 DP1 + B6 DP2 -\> USB_D+
-   A7 DN1 + B7 DN2 -\> USB_D-
-   A5 CC1 -\> 5.1 kOhm -\> GND
-   B5 CC2 -\> 5.1 kOhm -\> GND
-   A8 SBU1 -\> NC
-   B8 SBU2 -\> NC
-   USB ground pins -\> GND
-   Shield -\> GND for this prototype

The separate 5.1 kOhm CC1 and CC2 resistors are required for USB-C
device/sink operation.

## USB protection

Next step is to add a low-capacitance two-channel USB ESD protection
device, such as USBLC6-2SC6 or equivalent, physically close to the USB-C
connector.

Routing concept:

USB-C D+/D- -\> ESD protection -\> STM32 PA12/PA11

Do not add arbitrary USB series resistors until the exact STM32H743 USB
PHY recommendations are checked.

## USB power

USB_5V has intentionally been kept as its own net.

The design goal is to allow the flight controller to boot from USB for
Mission Planner configuration/flashing without aircraft power.

The next design task is therefore the 5 V power architecture / power
OR-ing and the final USB VBUS sensing arrangement.

------------------------------------------------------------------------

# 8. Current MCU Signal Allocation

## SPI1 -- MS5611

-   PA4 -\> BARO_CS
-   PA5 -\> SPI1_SCK
-   PA6 -\> SPI1_MISO
-   PA7 -\> SPI1_MOSI

## SPI2 -- BMI088

-   PC2_C -\> SPI2_MISO
-   PC3_C -\> SPI2_MOSI
-   PD3 -\> SPI2_SCK
-   PD4 -\> ACCEL_CS
-   PD5 -\> GYRO_CS

## BMI088 interrupts

-   PE2 -\> IMU_INT1_ACCEL
-   PE3 -\> IMU_INT2_ACCEL
-   PE4 -\> IMU_INT3_GYRO
-   PE5 -\> IMU_INT4_GYRO

## GPS / compass

-   PB6 -\> USART1_TX
-   PB7 -\> USART1_RX
-   PB8 -\> I2C1_SCL
-   PB9 -\> I2C1_SDA
-   PC13 -\> GPS_PPS

## USB

-   PA11 -\> USB_D-
-   PA12 -\> USB_D+
-   PA9 -\> USB_VBUS_SENSE

## Debug

-   PA13 -\> SWDIO
-   PA14 -\> SWCLK

------------------------------------------------------------------------

# 9. Design status at end of session

Completed or substantially defined:

-   STM32H743 core power network
-   VCAP circuitry
-   analog VDDA/VREF supply
-   BOOT0
-   reset circuit
-   SWD programming header
-   BMI088 schematic and MCU assignments
-   MS5611 schematic and MCU assignments
-   external GPS/compass header concept
-   USB MCU pins
-   USB-C connector and CC resistors

Still to do:

-   USB ESD protection
-   USB_5V / main 5 V power OR-ing and regulation
-   final USB VBUS sense circuit
-   HSE crystal selection and load capacitors
-   telemetry UART(s)
-   RC receiver input
-   CAN
-   servo/PWM outputs
-   battery voltage/current ADC inputs
-   main power input and regulators
-   buzzer / status LEDs as desired
-   SD card if desired
-   ArduPilot hwdef.dat
-   bootloader build and flashing procedure
-   PCB placement/routing review

## Recommended point to resume

**Resume with the USB ESD device and 5 V power architecture.**

After power and USB are finalized, continue allocating telemetry, RC,
CAN, and servo outputs before PCB layout.
