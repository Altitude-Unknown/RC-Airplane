#!/usr/bin/env python3
"""
Test: Use the updated GUI module to write/read a model via serial and verify reverse flags.
"""
import argparse
import os, sys, serial, time, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fram_gui_models as gui

def test_gui_reverse_flags(port):
    """Test GUI serialization of reverse flags."""
    try:
        # Create a worker and connect
        worker = gui.SerialWorker()
        worker.open(port)
        print("[OK] Connected to TX")
        time.sleep(0.2)
        
        # Create store
        store = gui.ModelsStore(worker)
        
        # Test 1: Read header
        print("\n=== TEST 1: Read Header ===")
        hdr = store.read_header()
        print(f"Magic: 0x{hdr['magic']:08x} (expect 0x54584346)")
        print(f"Version: 0x{hdr['ver']:04x} (expect 0x0001)")
        print(f"Total slots: {hdr['total_slots']}")
        print(f"Active slot: {hdr['active_slot']}")
        
        # Test 2: Create a model with reverse flags
        print("\n=== TEST 2: Create Model with Reverse Flags ===")
        model = dict(
            name="GuiRevTest",
            bind_code=54321,
            rates=[100, 100, 100, 100],
            expo=[0, 0, 0, 0],
            dr_switch=0,
            active_rates=False,
            subtrim=[0, 0, 0, 0],
            endpoints=[[1000, 2000], [1000, 2000], [1000, 2000], [1000, 2000]],
            reverse=[True, False, True, False]  # ch0 and ch2 reversed
        )
        print(f"Model name: {model['name']}")
        print(f"Reverse flags: {model['reverse']}")
        
        # Test 3: Write model to slot 1
        print("\n=== TEST 3: Write Model to transmitter storage ===")
        slot = 1
        store.write_model(slot, model)
        print(f"[OK] Model written to slot {slot}")
        
        # Test 4: Read it back
        print("\n=== TEST 4: Read Model from transmitter storage ===")
        read_model = store.read_model(slot)
        expected_bind = model['bind_code'] & 0x7FFF  # bind_code is 15-bit
        print(f"Name: {read_model['name']} (expect: GuiRevTest)")
        print(f"Bind code: {read_model['bind_code']} (expect: {expected_bind}, original: {model['bind_code']})")
        print(f"Reverse flags: {read_model['reverse']} (expect: [True, False, True, False])")
        print(f"CRC OK: {read_model['crc_ok']}")
        
        # Test 5: Verify
        # Note: bind_code is masked to 15 bits (0x7FFF) when stored
        expected_bind = model['bind_code'] & 0x7FFF
        success = (
            read_model['name'] == model['name'] and
            read_model['bind_code'] == expected_bind and
            read_model['reverse'] == model['reverse'] and
            read_model['crc_ok']
        )
        
        if success:
            print("\n[PASS] GUI reverse flags test passed!")
        else:
            print("\n[FAIL] GUI reverse flags mismatch!")
        
        worker.close()
        return success
        
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise GUI model serialization against a transmitter in config mode.")
    parser.add_argument("port", nargs="?", default="/dev/cu.usbmodem101")
    args = parser.parse_args()
    success = test_gui_reverse_flags(args.port)
    sys.exit(0 if success else 1)
