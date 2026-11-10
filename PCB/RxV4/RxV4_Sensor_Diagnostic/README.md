# Rx V4 sensor diagnostic — 2026-10-07

USB-only bench diagnostic; no servo or radio outputs. Replaces receiver firmware.
Built and upload-verified using `adafruit:samd:adafruit_feather_m0` on `/dev/cu.usbmodem101`.
Derived from I2C_Sensor_ID_Test; adds repeated identity and raw pressure/PROM output.
Uses the existing Wire driver; not a bounded-bus flight implementation.

Initial capture: `capture-2026-10-07.txt`.
- IMU responds at 0x6A, WHO_AM_I 0x6C. Exact fitted variant unconfirmed.
- Acceleration norm about 0.5 g using the old 0.000061 g/LSB scale.
  Capture contains large gyro/motion changes; stationary test pending.
  Do not change scale merely to force 1 g; confirm part and register configuration.
- Pressure device responds at 0x76; no response at 0x77 (normal single-device arrangement).
- PROM: 112,40017,35608,24918,24469,33769,27465,35439.
- PROM CRC4 calculated 15, stored 15: matches on all six records.
- Host conversion using MS5607 datasheet yields 856.884–856.994 hPa,
  28.496–30.807 C across six records. Above 20 C, second-order corrections are zero.
- These readings demonstrate communication and plausible conversions, not calibrated accuracy.

Pressure calculation reference: https://www.cdiweb.com/datasheets/te/eng_ds_ms5607-02ba03_b.pdf
Next: stationary capture, exact IMU identification, configuration readback,
and controlled orientation/motion checks. Receiver/autolevel not restored yet.

Stationary follow-up (user confirmed resting): 32 IMU samples, mean norm 0.4973 g (range 0.4961–0.4982) with old scale. Gyro raw values stable near (97,26,30). Pressure 856.903–856.940 hPa; temperature 25.856–25.940 C. Exact part number pending user lookup. Raw capture: stationary-2026-10-07.txt.

## Confirmed IMU and corrected scale
User identified installed part as LSM6DSO32TR via DigiKey product 11694177.
ST datasheet https://www.st.com/resource/en/datasheet/lsm6dso32.pdf
specifies FS bits 00 = +/-4 g with 0.122 mg/LSB (not 0.061).
Diagnostic scale corrected to 0.000122 g/LSB; gyro sensitivity stays 0.00875 dps/LSB at +/-250 dps.
Recompiled and upload-verified. Fresh register reads: WHO_AM_I=0x6C,
CTRL1_XL=0x40, CTRL2_G=0x40, CTRL3_C=0x44.
32 fresh samples: mean 0.99257 g, range 0.9802–0.9976 g.
See corrected-scale-2026-10-07.txt. This resolves this board's half-scale reading.
At the time of this capture, autolevel still used the old 0.000061 scale. It was
corrected later on 2026-10-07 before the current experimental firmware was
uploaded. This does not establish the cause of every historical flight issue or
old board reading.

## Post-miswire functional retest — 2026-10-07

After a four-position TAER connector offset briefly heated the IMU and pressure
sensor, the diagnostic was rerun with USB power only and all aircraft leads
removed. Repeated results were:

- LSM6DSO32 WHO_AM_I 0x6C and expected CTRL1_XL 0x40, CTRL2_G 0x40,
  CTRL3_C 0x44 readback.
- Stationary acceleration magnitude 0.991–0.995 g with stable raw gyro data.
- MS5607 at 0x76 with the exact earlier eight PROM words and matching CRC4 15.
- Converted pressure 857.24–857.32 hPa and a smooth temperature cooldown from
  30.98 C to 28.76 C.

These checks found no functional damage. They do not certify absolute sensor
accuracy or exclude latent damage from the heating event. The corrected-scale
autolevel firmware was restored after the diagnostic.
