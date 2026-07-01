# RC Receiver V4 PCB

Bring-up notes for the V4 receiver PCB.

## 2026-06-28 LSM6DS gyro test

Initial partial-population test:

- Only the LSM6DS gyro/accelerometer and I2C pullups were soldered to the RxV4 PCB.
- The unbuilt RxV4 PCB was jumpered to a known-working PCB with I2C headers.
- The LSM6DS address-select / SA0 pin was pulled to ground, so the expected I2C address was `0x6A`.
- The diagnostic sketch compiled and uploaded to an Adafruit Feather M0 target.
- The sensor responded on `0x6A` and streamed live gyro/accelerometer data.

Example captured output:

```text
0x6A G raw x/y/z: 138, -154, -55 | A raw x/y/z: 975, 213, -5105
0x6A G raw x/y/z: 137, -158, -51 | A raw x/y/z: 988, 230, -5089
```

Result: LSM6DS I2C communication and raw sensor streaming are working on the partially populated RxV4 PCB.

## 2026-06-28 second RxV4 PCB gyro test

Second partial-population test using the same jumper setup and diagnostic sketch:

- SDA and SCL both idled high, so the I2C bus was not stuck low.
- The LSM6DS did not acknowledge at `0x6A`.
- The LSM6DS did not acknowledge at `0x6B`.

Captured output:

```text
Lines now: SDA=1 SCL=1
Probe 0x6A -> no response
Probe 0x6B -> no response
```

Result: second RxV4 PCB gyro is not currently responding on I2C. Check LSM6DS power, ground, SDA/SCL continuity, solder joints, chip orientation, and SA0/address-select connection.

## Files

- `LSM6DS_Gyro_Test/LSM6DS_Gyro_Test.ino` - no-library Arduino diagnostic for checking the LSM6DS at `0x6A` or `0x6B`.
