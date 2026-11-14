# ASCEND FC Rev.2: first flight, 2026-11-03

This is the first reported flight of the ASCEND FC Rev.2 board, which combines the ArduPlane flight controller and the LoRa receiver. It flew with Mike's custom transmitter. Bring-up history is in `ArduPilot-PCB/bringup-ascend-rev2/README.md`.

## What Mike reported

- Took off and landed in MANUAL.
- In the air, switched to AUTOTUNE and flew it in short bursts.
- AUTOTUNE turned very conservatively, too little to turn the airplane. Mike switched back to MANUAL to turn, then back to AUTOTUNE.

## Known setup before the flight (from the 2026-11-01 parameter capture)

- FLTMODE_CH=5. The Tx Aux 1 switch is two-position, so only FLTMODE1 (low) and FLTMODE6 (high) are reachable. On 11-01 these were FBWA and MANUAL. Mike replaced FBWA with AUTOTUNE, so AUTOTUNE is on the low position (FLTMODE1). On the earlier Tx model slot that position had full 100% rates. If the slot is unchanged, reduced Tx rates are not the cause.
- Stock gains, never tuned:
  - Roll: RLL_RATE_P 0.08, I 0.15, FF 0.345.
  - Pitch: PTCH_RATE_P 0.04, I 0.15, FF 0.345.
- Limits: ROLL_LIMIT_DEG 45, PTCH_LIM_MAX_DEG 20, PTCH_LIM_MIN_DEG −25.
- AUTOTUNE_LEVEL 6, AUTOTUNE_AXES 7.
- Servos 1100–1900. SCALING_SPEED 15.
- No airspeed sensor and no GPS (GPS1_TYPE=0).
- RC calibration: RC1 1036/1522/2000, RC2 1000/1353/1857. The elevator trim centre (1353) is well off-centre.
- No SD card on this board, so there is no onboard log. A MAVLink telemetry log exists only if a ground station was connected.

## Not yet known

- Whether AUTOTUNE changed or saved any gains. Read the parameters over USB and compare them with `ArduPilot-PCB/bringup-ascend-rev2/2026-11-01/params-after-rotation-fix.json`.
- Whether "conservative" meant a slow roll rate or a shallow bank. Left/right turning felt even on this short flight (Mike, provisional; more flights are needed to confirm). The V2 board showed an asymmetry on 2026-10-20.

No parameter changes were made in this session. No flight-ready claim is made.

## 2026-11-04 bench: "won't arm" explained

- Mike was using the PCB ARM button. The board's custom button code (`Plane::update_board_arm_button`, from 2026-10-10) only accepts a press in **MANUAL or FBWA**. It also needs healthy RC, throttle at zero, not flying, and a 2-second hold. FBWA had been replaced by AUTOTUNE on the switch-low position, so the button is ignored there.
- In MANUAL (switch high) the button armed the board normally: "Throttle armed" at 34 s in `ArduPilot-PCB/bringup-ascend-rev2/2026-11-04/armwatch-1.txt`. Pre-arm checks all pass (`prearm-1.txt`).
- Side observation: in MANUAL, full right rudder reads 1698 (RC4 max 1947), which matches the Tx's 50% Manual rudder rate. It was not used for arming.
- **Option, not done:** add AUTOTUNE to the button's allowed modes in firmware. Until then, arm in MANUAL, then switch to AUTOTUNE in the air.
- **Backup:** full parameter set saved 2026-11-04 before the second AUTOTUNE flight (`ArduPilot-PCB/bringup-ascend-rev2/2026-11-04/params-before-autotune-flight2.json`).
- **Day-1 AUTOTUNE changed no gains.** Compared with Nov 1, the only tuning-related difference is FLTMODE1 5 → 8 (Mike's AUTOTUNE switch change). All RLL_/PTCH_ rate gains are still stock. YAW_RATE_ENABLE=0, so yaw is not tuned even though the message says "roll pitch yaw".

## 2026-11-04 bench stick/servo test (`2026-11-04/stick-servo-bench.txt`, disarmed, prop off)

- **Tx in the AUTOTUNE position (switch low) sends full range:** aileron 1036–2000, elevator 1000–1852. Tx rates are not the cause.
- **AUTOTUNE outputs at full stick, airplane still:**
  - Aileron 1317 / 1655, about 40–46% of the ±400 µs throw.
  - Elevator up 1659–1671 (about 41%).
  - Rudder follows aileron through KFF_RDDRMIX (1409 / 1577).
- **MANUAL (switch high) uses the Tx Manual rates:**
  - Aileron in 1360–1707, out 1367 / 1654 (about 35%).
  - Elevator full: 1100 / 1896.
  - So at the start of a roll, AUTOTUNE gives about as much aileron as Mike flies with in MANUAL.
- **Bench attitude:** the airplane at rest read **pitch about −10° (nose down)** and roll +2–5°. The in-airplane level trim (open item from Nov 1) has never been done. If the airframe was sitting level, AUTOTUNE/FBWA would hold about 10° nose-up as "level", flying slow and mushy with weak turns. **Ask Mike how the airplane was sitting.**
- **Update:** Mike was holding the airplane during that test. Set down level, the board reads pitch −1.0°, roll +0.3° (`2026-11-04/levelcheck-1.txt`; AHRS_TRIM_X 0.0058, AHRS_TRIM_Y −0.0257). The level reference is fine and the −10° hypothesis is ruled out.
- **Proposed, awaiting Mike's go-ahead:** RLL_RATE_FF and PTCH_RATE_FF 0.345 → 0.5 as better AUTOTUNE starting points. Also asked whether the airplane barely banked or banked but turned wide.
