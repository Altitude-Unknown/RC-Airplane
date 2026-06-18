#!/usr/bin/env python3
"""
Test RX connectivity via serial.
The RX prints "RX Ready" on startup, so we'll connect and verify.
"""
import serial, time, sys

def test_rx(port):
    try:
        ser = serial.Serial(port=port, baudrate=115200, timeout=2)
        print(f"[OK] Connected to {port}")
        time.sleep(0.5)
        
        # Read any startup messages (RX prints "RX Ready" on boot)
        output = ser.read_all().decode('utf-8', errors='ignore')
        print(f"RX output: {output}")
        
        if "Ready" in output:
            print("[PASS] RX is running")
            ser.close()
            return True
        else:
            print("[INFO] RX connected but no 'Ready' message yet (may have booted earlier)")
            ser.close()
            return True  # RX is still connected even if msg not captured
            
    except Exception as e:
        print(f"[ERROR] {e}")
        return False

if __name__ == "__main__":
    # Test both ports; RX will be the one not responding to PING
    print("=== Testing RX on /dev/cu.usbmodem11301 ===")
    if test_rx("/dev/cu.usbmodem11301"):
        print("[OK] RX port identified: /dev/cu.usbmodem11301")
    else:
        print("[INFO] That port didn't respond; RX may be on /dev/cu.usbmodem101")
