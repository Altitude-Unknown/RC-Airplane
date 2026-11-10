#!/usr/bin/env python3
import argparse
import binascii
import os
import select
import struct
import termios
import time

BAUD = 115200
TXCF_MAGIC = 0x54584346
TXCF_VERSION = 0x0001
HDR_ADDR = 0x0000
MODELS_BASE = 0x0100
MODEL_SLOT_SIZE = 64
MODEL_BIN_SIZE = 60
HDR_FMT = "<I H H H I 18s"
MODEL_FMT_NOCRC = "<16s H 4b 4b B B 4h 8H 6s"
MODEL_FMT = MODEL_FMT_NOCRC + " H"
CHANNELS = ["Rudder", "Aileron", "Elevator", "Throttle"]


class SerialPort:
    def __init__(self, path, baud=BAUD):
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.fd)
        iflag, oflag, cflag, lflag, ispeed, ospeed, cc = attrs
        iflag = 0
        oflag = 0
        lflag = 0
        cflag |= termios.CLOCAL | termios.CREAD
        cflag &= ~termios.PARENB
        cflag &= ~termios.CSTOPB
        cflag &= ~termios.CSIZE
        cflag |= termios.CS8
        cflag &= ~termios.CRTSCTS if hasattr(termios, "CRTSCTS") else cflag
        cc[termios.VMIN] = 0
        cc[termios.VTIME] = 0
        speed = getattr(termios, f"B{baud}")
        termios.tcsetattr(self.fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, speed, speed, cc])
        termios.tcflush(self.fd, termios.TCIOFLUSH)

    def close(self):
        os.close(self.fd)

    def write_line(self, line):
        os.write(self.fd, (line + "\n").encode("ascii"))

    def read_line(self, timeout=1.0):
        deadline = time.time() + timeout
        buf = bytearray()
        while time.time() < deadline:
            r, _, _ = select.select([self.fd], [], [], max(0.0, deadline - time.time()))
            if not r:
                continue
            chunk = os.read(self.fd, 256)
            if not chunk:
                continue
            for b in chunk:
                if b == 10:
                    return buf.decode("ascii", errors="ignore").strip()
                if b != 13:
                    buf.append(b)
        return buf.decode("ascii", errors="ignore").strip()

    def command(self, line, timeout=1.0):
        self.write_line(line)
        return self.read_line(timeout)


def crc16_ccitt(data, poly=0x1021, init=0xFFFF):
    crc = init
    for b in data:
        crc ^= (b << 8) & 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF


def read_bytes(ser, addr, length):
    resp = ser.command(f"READ {addr} {length}", timeout=2.0)
    if not resp.startswith("DATA "):
        raise RuntimeError(f"READ {addr} {length} returned {resp!r}")
    return binascii.unhexlify(resp.split(" ", 1)[1])


def write_bytes(ser, addr, data):
    resp = ser.command(f"WRITE {addr} {binascii.hexlify(data).decode('ascii').upper()}", timeout=2.0)
    if resp != "OK":
        raise RuntimeError(f"WRITE {addr} returned {resp!r}")


def decode_model(raw):
    b = raw[:MODEL_BIN_SIZE]
    tup = struct.unpack(MODEL_FMT, b)
    name = tup[0].split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
    rates = list(tup[2:6])
    expo = list(tup[6:10])
    subtrim = list(tup[12:16])
    ep_flat = list(tup[16:24])
    endpoints = [[ep_flat[i * 2], ep_flat[i * 2 + 1]] for i in range(4)]
    reserved = tup[24]
    reverse = [bool((reserved[0] >> i) & 1) for i in range(4)]
    crc_stored = tup[25]
    crc_calc = crc16_ccitt(b[:58])
    return {
        "name": name,
        "bind_code": tup[1],
        "rates": rates,
        "expo": expo,
        "dr_switch": tup[10],
        "active_rates": tup[11],
        "subtrim": subtrim,
        "endpoints": endpoints,
        "reverse": reverse,
        "crc_stored": crc_stored,
        "crc_calc": crc_calc,
        "crc_ok": crc_stored == crc_calc,
    }


def main():
    parser = argparse.ArgumentParser(description="Read and decode transmitter FRAM config mode.")
    parser.add_argument("port")
    parser.add_argument("--all-slots", action="store_true")
    parser.add_argument("--set-subtrim", nargs=3, metavar=("SLOT", "CHANNEL", "US"),
                        help="Set one model subtrim and rewrite the slot with a fresh CRC.")
    parser.add_argument("--clear-unused-slot", type=int, metavar="SLOT",
                        help="Zero one slot only when its used-bitmap bit is clear.")
    args = parser.parse_args()

    ser = SerialPort(args.port)
    try:
        time.sleep(0.25)
        resp = ser.command("PING", timeout=1.0)
        if resp != "PONG":
            raise SystemExit(
                f"No PONG from {args.port}; got {resp!r}. "
                "Put the Tx in USB config mode by booting while holding D9 + D5."
            )
        print(f"PING: {resp}")
        print(f"INFO: {ser.command('INFO', timeout=1.0)}")

        hdr_raw = read_bytes(ser, HDR_ADDR, 32)
        magic, ver, total_slots, active_slot, used_bitmap, _ = struct.unpack(HDR_FMT, hdr_raw)
        print(f"Header: magic=0x{magic:08X} version=0x{ver:04X} total_slots={total_slots} active_slot={active_slot} used_bitmap=0x{used_bitmap:08X}")
        if magic != TXCF_MAGIC or ver != TXCF_VERSION:
            raise SystemExit("Header magic/version is not the current TXCF format.")

        if args.clear_unused_slot is not None:
            slot = args.clear_unused_slot
            if not (0 <= slot < total_slots):
                raise SystemExit(f"Slot {slot} is outside 0..{total_slots - 1}.")
            if (used_bitmap >> slot) & 1:
                raise SystemExit(f"Refusing to clear slot {slot}: header marks it used.")
            address = MODELS_BASE + slot * MODEL_SLOT_SIZE
            write_bytes(ser, address, bytes(MODEL_SLOT_SIZE))
            verify = read_bytes(ser, address, MODEL_SLOT_SIZE)
            if verify != bytes(MODEL_SLOT_SIZE):
                raise SystemExit(f"Slot {slot} clear verification failed.")
            print(f"Cleared unused slot {slot}; read-back is all zeroes.")
            return

        if args.set_subtrim:
            slot = int(args.set_subtrim[0], 0)
            ch = int(args.set_subtrim[1], 0)
            us = int(args.set_subtrim[2], 0)
            if not (0 <= slot < total_slots):
                raise SystemExit(f"Slot {slot} is outside 0..{total_slots - 1}.")
            if not (0 <= ch <= 3):
                raise SystemExit("Channel must be 0..3.")
            if not (-500 <= us <= 500):
                raise SystemExit("Subtrim must be -500..500 us.")

            raw = bytearray(read_bytes(ser, MODELS_BASE + slot * MODEL_SLOT_SIZE, MODEL_SLOT_SIZE))
            model = decode_model(raw)
            print(f"Before: slot={slot} name={model['name']!r} {CHANNELS[ch]} subtrim={model['subtrim'][ch]:+d} crc_ok={model['crc_ok']}")
            if not model["crc_ok"]:
                raise SystemExit("Refusing to write a model with bad CRC.")

            # Layout offset: name16 + bind2 + rates4 + expo4 + dr1 + active1 = 28.
            subtrim_offset = 28 + ch * 2
            raw[subtrim_offset:subtrim_offset + 2] = struct.pack("<h", us)
            crc = crc16_ccitt(raw[:58])
            raw[58:60] = struct.pack("<H", crc)
            write_bytes(ser, MODELS_BASE + slot * MODEL_SLOT_SIZE, bytes(raw))

            verify = read_bytes(ser, MODELS_BASE + slot * MODEL_SLOT_SIZE, MODEL_SLOT_SIZE)
            verified = decode_model(verify)
            print(f"After:  slot={slot} name={verified['name']!r} {CHANNELS[ch]} subtrim={verified['subtrim'][ch]:+d} crc_ok={verified['crc_ok']}")
            return

        slots = range(total_slots) if args.all_slots else [active_slot]
        for slot in slots:
            raw = read_bytes(ser, MODELS_BASE + slot * MODEL_SLOT_SIZE, MODEL_SLOT_SIZE)
            model = decode_model(raw)
            used = bool((used_bitmap >> slot) & 1)
            print()
            print(f"Slot {slot}: used={used} name={model['name']!r} bind={model['bind_code']} crc_ok={model['crc_ok']}")
            print(f"  rates={model['rates']} expo={model['expo']} active_rates={model['active_rates']} dr_switch={model['dr_switch']}")
            for ch, label in enumerate(CHANNELS):
                mn, mx = model["endpoints"][ch]
                print(
                    f"  {ch}:{label:8s} subtrim={model['subtrim'][ch]:+4d} "
                    f"endpoint={mn:4d}-{mx:4d} reverse={model['reverse'][ch]}"
                )
            if not model["crc_ok"]:
                print(f"  CRC stored=0x{model['crc_stored']:04X} calc=0x{model['crc_calc']:04X}")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
