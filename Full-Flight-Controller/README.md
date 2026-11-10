# Full Flight Controller

Custom fixed-wing flight controller and autopilot project, initially planned around the STM32H743VIT6.

The intended capabilities include:

- Manual and stabilized flight
- Fly-by-wire modes such as FBWA
- Attitude estimation and automatic leveling
- GPS waypoint navigation
- Return-to-home and configurable failsafes
- Camera and external-device triggering
- Flight-data logging and telemetry

This directory will hold the hardware requirements, architecture decisions, PCB interface definitions, firmware, tests, and bring-up records. See [DESIGN_NOTES.md](DESIGN_NOTES.md) for the initial technical assessment and design checklist.

## Status

Concept and requirements phase. No schematic pinout or firmware implementation has been committed yet.

## Proposed future layout

```text
Full-Flight-Controller/
├── README.md
├── DESIGN_NOTES.md
├── docs/            Hardware and interface specifications
├── firmware/        Embedded source and board configuration
├── hardware/        Schematic, PCB, BOM, and manufacturing outputs
├── tests/           Host, unit, integration, and HIL tests
└── tools/           Configuration, flashing, and log utilities
```

The additional directories should be created when their formats and toolchains are selected.
