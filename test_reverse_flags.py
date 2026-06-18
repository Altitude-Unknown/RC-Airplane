#!/usr/bin/env python3
"""
Test script: verify reverse flags are correctly persisted in TX FRAM.
Usage: python3 test_reverse_flags.py /dev/cu.usbmodem101
(Put TX in Config Mode: hold D9+D5 at boot, should show slow LED blink + USB ready)
"""
import sys, serial, struct, binascii, time

BAUD = 115200
TXCF_MAGIC = 0x54584346
TXCF_VERSION = 0x0001
MODELS_BASE = 0x0100
MODEL_SLOT_SIZE = 64
MODEL_BIN_SIZE = 60
MODEL_FMT_NOCRC = "<16s H 4b 4b B B 4h 8H 6s"  # 58 bytes
MODEL_FMT = MODEL_FMT_NOCRC + " H"              # +2 = 60

def crc16_ccitt(data: bytes, poly=0x1021, init=0xFFFF) -> int:
    crc = init
    for b in data:
        crc ^= (b << 8) & 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF

def to_hex(b: bytes) -> str:
    return binascii.hexlify(b).decode("ascii").upper()

def from_hex(s: str) -> bytes:
    s = s.strip().replace(" ", "")
    return binascii.unhexlify(s)

def send_cmd(ser, cmd):
    """Send a command and read response."""
    print(f">> {cmd}")
    ser.write((cmd + "\n").encode("ascii"))
    resp = ser.readline().decode("ascii", errors="ignore").strip()
    print(f"<< {resp}")
    return resp

def test_tx_config_mode(port):
    """Test reading/writing a model with reverse flags."""
    try:
        ser = serial.Serial(port=port, baudrate=BAUD, timeout=2)
        print(f"[OK] Connected to {port}")
        time.sleep(0.5)
        
        # Test 1: PING
        print("\n=== TEST 1: PING ===")
        resp = send_cmd(ser, "PING")
        if "PONG" not in resp:
            print("[FAIL] No PING response; TX may not be in Config Mode.")
            print("Put TX in Config Mode: hold D9 + D5 at boot (slow LED blink, USB ready).")
            ser.close()
            return False
        
        # Test 2: Check FRAM range
        print("\n=== TEST 2: RANGE ===")
        resp = send_cmd(ser, "RANGE")
        print(f"FRAM size: {resp.split()[-1] if 'RANGE' in resp else 'unknown'} bytes")
        
        # Test 3: Write a test model with reverse flags
        print("\n=== TEST 3: WRITE TEST MODEL (with reverse flags) ===")
        slot = 0
        name = "TestRev00"
        name_bytes = name.encode("utf-8")[:15] + b"\x00"
        name_bytes = name_bytes.ljust(16, b"\x00")
        
        # Build model with reverse flags: bit0=ch0 reversed, bit1=ch1 reversed
        bind_code = 12345
        rates = [100, 100, 100, 100]
        expo = [0, 0, 0, 0]
        dr_switch = 0
        active_rates = 0
        subtrim = [0, 0, 0, 0]
        endpoints = [1000, 2000, 1000, 2000, 1000, 2000, 1000, 2000]
        
        # Set reverse flags: channels 0 and 1 reversed (0b0011 = 0x03)
        rev_mask = 0x03  # ch0 and ch1 reversed
        reserved = bytes([rev_mask]) + b"\x00"*5
        
        packed_no_crc = struct.pack(MODEL_FMT_NOCRC, name_bytes, bind_code,
                                    *rates, *expo, dr_switch, active_rates,
                                    *subtrim, *endpoints, reserved)
        crc = crc16_ccitt(packed_no_crc)
        model_bin = packed_no_crc + struct.pack("<H", crc)
        model_bin_padded = model_bin + b"\x00" * (MODEL_SLOT_SIZE - MODEL_BIN_SIZE)
        
        addr = MODELS_BASE + slot * MODEL_SLOT_SIZE
        hexblob = to_hex(model_bin_padded)
        resp = send_cmd(ser, f"WRITE {addr} {hexblob}")
        if "OK" not in resp:
            print("[FAIL] WRITE failed")
            ser.close()
            return False
        print("[OK] Model written")
        
        # Test 4: Read it back
        print("\n=== TEST 4: READ TEST MODEL ===")
        resp = send_cmd(ser, f"READ {addr} {MODEL_SLOT_SIZE}")
        if not resp.startswith("DATA "):
            print("[FAIL] READ failed")
            ser.close()
            return False
        
        hexblob = resp.split(" ", 1)[1].strip()
        read_bin = from_hex(hexblob)
        read_bin = read_bin[:MODEL_BIN_SIZE]
        
        # Unpack and verify
        tup = struct.unpack(MODEL_FMT, read_bin)
        name_read = tup[0].split(b'\x00',1)[0].decode('utf-8', errors='ignore')
        bind_read = tup[1]
        reserved_read = tup[24]
        crc_stored = tup[25]
        
        crc_calc = crc16_ccitt(read_bin[:58])
        
        print(f"Name: {name_read} (expected: {name})")
        print(f"Bind Code: {bind_read} (expected: {bind_code})")
        print(f"Reserved[0] (reverse mask): 0x{reserved_read[0]:02x} (expected: 0x{rev_mask:02x})")
        print(f"CRC stored: 0x{crc_stored:04x}")
        print(f"CRC calculated: 0x{crc_calc:04x}")
        
        # Verify
        success = (
            name_read == name and
            bind_read == bind_code and
            reserved_read[0] == rev_mask and
            crc_stored == crc_calc
        )
        
        if success:
            print("\n[PASS] All checks passed!")
            # Extract reverse flags
            rev_flags = [bool((reserved_read[0] >> i) & 1) for i in range(4)]
            print(f"Reverse flags: ch0={rev_flags[0]}, ch1={rev_flags[1]}, ch2={rev_flags[2]}, ch3={rev_flags[3]}")
        else:
            print("\n[FAIL] Some checks failed")
        
        ser.close()
        return success
        
    except Exception as e:
        print(f"[ERROR] {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 test_reverse_flags.py <serial_port>")
        print("Example: python3 test_reverse_flags.py /dev/cu.usbmodem101")
        sys.exit(1)
    
    port = sys.argv[1]
    success = test_tx_config_mode(port)
    sys.exit(0 if success else 1)
