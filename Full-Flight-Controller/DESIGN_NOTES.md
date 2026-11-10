# Initial Design Notes

Updated: 2026-07-11

## Processor assessment

The STM32H743VIT6 is suitable as the sole **main flight processor** for the planned fixed-wing autopilot. Its Cortex-M7 core, hardware floating-point and DSP support, 2 MB of internal flash, 1 MB of RAM, timers, DMA, and communication peripherals are sufficient for:

- High-rate IMU sampling and attitude estimation
- Stabilization and servo control loops
- FBWA and related assisted modes
- GPS navigation, waypoint missions, and return-to-home
- RC input, telemetry, CAN devices, and payload control
- Parameter storage and flight logging to external media

Commercial and open flight controllers already run full autopilot stacks on this processor class. Compute capacity is not expected to be the primary design constraint.

## Recommended processor architecture

Use the STM32H743 as the main flight-management unit. Strongly consider a small, independent safety/I/O MCU for a production-quality design. The second MCU would not run navigation; it could:

- Generate or supervise servo outputs
- Monitor a heartbeat from the H743
- Put outputs into predetermined safe states after a main-CPU failure
- Read an independent RC/failsafe input
- Enforce output limits and startup inhibit behavior
- Control a safety switch or independent recovery device

Possible families include STM32G0, STM32G4, STM32F3, or another well-supported MCU with enough independent timers and communication channels. The actual part should be selected after the output count and safety requirements are defined.

### Selected safety/I/O controller

The current selection is **STM32G071KBT6**, DigiKey part **497-18355-ND**. It is a 64 MHz Cortex-M0+ in a 32-pin LQFP package with 128 KB flash, 36 KB RAM, multiple timers and watchdogs, four USARTs, and substantially more pin flexibility than the initially considered 20-pin STM32G030F6P6. Its planned responsibilities remain servo/output supervision, H743 heartbeat monitoring, independent failsafe handling, and selected power or RC monitoring. It is not intended to run navigation or attitude estimation.

## Preliminary hardware architecture

```text
Power inputs and monitors
          |
          v
   +---------------+       +------------------+
   | STM32H743 FMU |<----->| Safety / I/O MCU |
   +---------------+       +------------------+
     |   |   |   |                   |
     |   |   |   +-- GPS/telemetry   +-- Servo/actuator outputs
     |   |   +------ CAN and payloads
     |   +---------- SD/external flash
     +-------------- Redundant flight sensors
```

Suggested interfaces, subject to pin and DMA analysis:

- Primary IMU on a dedicated SPI bus
- Secondary IMU on another SPI bus or independently managed chip select
- Barometer on SPI or I2C, with careful physical placement
- External compass/GPS interfaces; prefer an external compass away from power wiring
- SDMMC or SPI storage for flight logs
- Dual CAN where connector and pin budgets permit
- UARTs for primary GPS, secondary GPS, telemetry, RC receiver, payload, and debug
- ADC channels for battery voltage, battery current, analog airspeed, and optional analog inputs
- USB for development, configuration, logs, and firmware update
- SWD connector or test pads that remain accessible after assembly

## Important STM32H743VIT6 constraint

The `VI` device uses the 100-pin package. The MCU contains more peripheral functions than can be exposed at the same time. Before schematic capture is finalized, create a complete pin-allocation table that includes:

- Every peripheral signal and alternate-function mapping
- DMA controller, stream, and request assignments
- Timer channels for PWM, capture, DShot, or other actuator protocols
- Interrupt priorities and expected data rates
- Boot straps, clocks, SWD, USB, and reserved test signals
- Pins required to enter or recover the bootloader

Pin and DMA conflicts are a larger practical risk than CPU load.

## Sensor and PCB priorities

- Use at least two independently powered or isolatable IMUs if practical.
- Avoid using I2C for the primary IMU.
- Isolate sensor supplies from noisy servo, radio, and switching-regulator loads.
- Keep high-current and fast switching return paths away from sensor grounds.
- Plan mechanical vibration isolation and locate IMUs near the aircraft rotation center when possible.
- Protect the barometer from direct airflow, prop wash, light, and heat sources while allowing static pressure equalization.
- Expect the onboard magnetometer to be compromised by power wiring; support an external compass.
- Separate flight-controller power from the servo power rail and design for servo brownout/transient events.
- Provide redundant protected power inputs if the reliability target warrants them.
- Monitor each important supply and define deterministic brownout behavior.

## Preliminary sensor selection

Availability was checked at DigiKey on 2026-07-11, but stock must be checked again before ordering or freezing the BOM.

### Inertial sensors

The current practical choice is **two Bosch BMI270 six-axis IMUs**. Each includes a three-axis accelerometer and three-axis gyroscope and supports SPI. Use separate SPI buses where the H743 pin and DMA allocation permits.

- BMI270 #1: primary IMU on dedicated SPI with its own data-ready interrupt
- BMI270 #2: redundant IMU on another SPI bus with its own data-ready interrupt
- Provide local supply filtering and independent power isolation or switching where practical
- Consider mounting the devices in different orientations, with the orientation recorded in the board definition
- Reserve an interface or footprint strategy for a future third IMU from a different manufacturer

Two identical IMUs protect against individual device, solder-joint, power-branch, and SPI-bus failures, but they do not provide model diversity. The BMI270 is also less specifically optimized for severe vibration than the BMI088, making PCB placement, vibration testing, filtering, and mechanical mounting especially important.

### Static-pressure altitude

Use a **Bosch BMP581** absolute-pressure sensor as the initial barometer. It supports I2C and SPI. Place it away from regulators, processors, and other heat sources; shield it from direct light and propeller airflow; and use suitable open-cell foam without sealing the pressure path.

Reserve space or an interface for a second barometer, preferably from a different manufacturer. The first prototype can populate only one if space or cost requires it.

### GNSS

Waypoint flight and return-to-home require GNSS. The current onboard candidate is the **u-blox MAX-M10S-00B**, but the preferred first-version architecture is an external GPS/compass module so the antenna and magnetometer can be placed away from electrical noise.

Provide at least one external GNSS connector with:

- UART transmit and receive
- PPS input to the H743
- I2C for an external compass
- Protected power and ground
- Both voltage levels only if the connector design makes accidental misuse unlikely

Consider a second GNSS or spare navigation UART connector if the pin budget allows. An onboard GNSS implementation would additionally require controlled-impedance RF routing, antenna protection and matching, clean power, antenna keep-out, and backup-power provisions.

### Magnetometer

The **Memsic MMC5983MA** is the current magnetometer candidate. It supports I2C and SPI and may be populated onboard as a backup. The primary compass should normally be external, commonly integrated with the GPS module, because battery wiring, motors, ESCs, servos, inductors, and high-current PCB paths can make an onboard compass unreliable.

### Airspeed

A differential-pressure airspeed sensor is strongly recommended for fixed-wing operation. It improves stall protection, FBWA consistency, wind estimation, energy-based speed/altitude control, return-to-home, and approach behavior.

The exact sensor is not selected. The MS4525DO family is established, but its pressure range must match the aircraft. A 30 PSI part is far too insensitive for normal RC-aircraft pitot measurements. Select the part only after defining minimum and maximum flight speeds; likely candidates will be approximately ±0.5 PSI for slower aircraft or ±1 PSI for faster aircraft. An external I2C, SPI, or CAN airspeed module may be preferable to routing long pitot tubes to the controller.

### Electrical and system health measurements

Include measurement channels for:

- Main battery voltage and current
- Primary and backup flight-controller input voltage
- Main 5 V and 3.3 V rails
- Servo-rail voltage
- Board temperature
- Optional motor, ESC, or engine temperature
- Optional ESC RPM or tachometer input
- RC receiver link-quality telemetry where supported
- Optional pitot-heater current

Battery current measurement should use an appropriately rated precision shunt and current-sense amplifier. Protect and filter all ADC inputs. These measurements are part of the failsafe system, not merely telemetry.

### Preliminary sensor topology

```text
Onboard
├── BMI270 #1 — dedicated SPI and data-ready interrupt
├── BMI270 #2 — independent SPI and data-ready interrupt
├── BMP581 — static-pressure altitude
├── Optional second barometer footprint/interface
├── Optional MMC5983MA backup compass
├── Battery voltage/current sensing
├── Flight and servo power-rail sensing
└── Board temperature sensing

External
├── Primary GNSS + compass + PPS
├── Optional second GNSS/navigation UART
├── Differential-pressure airspeed sensor
├── CAN sensor and actuator buses
├── Optional analog airspeed input
├── RPM/tachometer input
└── External temperature inputs
```

## Storage and memory

- Do not use internal program flash for routine flight logging.
- Include microSD or suitable external flash for logs.
- Consider external QSPI NOR for update images, recovery, assets, or future firmware growth.
- Reserve nonvolatile parameter storage with wear management and schema/version migration.
- Define how firmware updates recover from interrupted power before choosing the final flash layout.

## Firmware direction

The firmware strategy remains an open design decision:

1. **ArduPilot-based board:** Fastest path to mature control, navigation, failsafe, mission, and telemetry behavior. Hardware should follow a supported H743 board architecture where possible, and a board hardware definition will be required.
2. **PX4-based board:** Another mature autopilot base with its own supported-hardware and RTOS conventions.
3. **Custom firmware:** Maximum ownership and flexibility, but attitude estimation, navigation, control, parameter management, drivers, failsafes, logging, update recovery, and validation all become project responsibilities.

Writing completely new flight-critical software is a much larger task than writing device drivers. Reusing a mature autopilot stack is the recommended initial approach unless novel control behavior or licensing requirements rule it out. Custom application features can be layered on a mature base.

If custom firmware is selected, use an RTOS and isolate responsibilities into testable modules. A preliminary task split could include:

- Sensor acquisition and timestamping
- State estimation
- Inner attitude/rate control loops
- Outer navigation and guidance loops
- Mode and mission management
- RC input and pilot override
- Actuator allocation and output
- Safety and failsafe supervision
- Telemetry and command handling
- Parameter management
- Logging and health reporting

All flight-critical loops need explicit deadlines, execution-time measurements, watchdog coverage, and overload behavior.

## Failsafe philosophy

Failsafe behavior must be designed as a state machine, not added at the end. Define responses for:

- Loss or corruption of RC input
- GPS degradation or loss
- Airspeed sensor failure
- One or more IMU failures
- Excessive estimator disagreement
- Low battery and critical battery
- Main processor lockup or missed control deadline
- Servo power failure
- Telemetry loss (normally not itself a flight emergency)
- Geofence breach
- Invalid mission data
- Interrupted startup or firmware update

Return-to-home is only safe when the estimator, position source, altitude source, actuator system, and stored home position remain trustworthy. Some failures should instead command a simpler stabilized mode or independent recovery output.

## Requirements to settle before schematic pin assignment

- Aircraft types and control surfaces to support
- Maximum number and type of actuator outputs
- PWM versus DShot or other output protocols
- Required RC input protocols and redundant RC expectations
- Number and models of onboard IMUs and barometers
- GPS, compass, and airspeed interfaces
- Required CAN, UART, I2C, and external SPI connectors
- Camera/payload triggering electrical requirements
- Telemetry radios and companion-computer requirements
- Input voltage range and redundant power-source design
- Environmental, vibration, temperature, and size constraints
- Logging duration and rate
- Desired autopilot software base and licensing constraints
- Safety integrity target: experimental, routine hobby operation, or higher reliability

## Recommended next design artifacts

1. System requirements and supported flight-mode list
2. Connector and I/O budget
3. Sensor and power architecture
4. MCU pin/alternate-function/DMA matrix
5. Failure-mode and failsafe table
6. Block diagram and power tree
7. Preliminary schematic review
8. Firmware platform proof-of-concept on an H743 development board
9. Board bring-up and hardware-in-the-loop test plan

## Initial conclusion

One STM32H743VIT6 is enough to execute the planned flight functions. The best use of additional silicon is not another equal flight computer at this stage, but a small independent safety/I/O controller, redundant sensors, robust power supervision, and external log storage. Final suitability of the 100-pin package depends on completing the I/O and DMA allocation before the PCB is committed.
