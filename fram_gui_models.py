#!/usr/bin/env python3
"""
Desktop RC transmitter and receiver configuration GUI.

This program talks to the SAMD21 transmitter over USB serial while the
transmitter is in Config Mode. The transmitter firmware exposes a tiny text
protocol:

    READ <address> <length>
    WRITE <address> <hex bytes>

    The GUI uses that protocol to read and write model settings stored in the
    transmitter's FRAM or built-in M0 flash fallback.

Important beginner note:
The Python GUI and the Arduino transmitter firmware must agree exactly about
the binary layout of the stored model data. That is why this file has several
struct format strings below. If the firmware struct changes, this file must be
updated to match it byte-for-byte.
"""

import sys, os, binascii, json, time, struct, random, threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import firmware_updater

try:
    import serial
    import serial.tools.list_ports as list_ports
except Exception as e:
    raise SystemExit("This app requires 'pyserial' (or apt python3-serial on Debian).\n" + str(e))

# Basic application-wide settings.
APP_TITLE = "Altitude Unknown RC Configurator"
BAUD = 115200

# The firmware uses four fixed channel indexes internally:
#   0 = Rudder, 1 = Aileron, 2 = Elevator, 3 = Throttle
#
# The GUI lets the user rename these labels, but the underlying channel indexes
# still matter because they determine which firmware array slot gets written.
CHANNEL_DEFAULT_NAMES = ["Rudder", "Aileron", "Elevator", "Throttle"]

# Many RC receivers are labeled TAER. This only changes the order shown in the
# table. The row IDs still stay attached to the original firmware channels.
CHANNEL_DISPLAY_ORDER = [3, 1, 2, 0]  # Show receiver-style TAER order while keeping firmware channel IDs.

# Channel label names are GUI-only metadata. The transmitter's 60-byte model
# struct has no spare room for long names, so custom channel labels live in this
# local JSON preferences file instead of FRAM.
LOCAL_PREFS_PATH = os.path.join(os.path.expanduser("~"), ".altitude_unknown_rc_configurator.json")
LEGACY_PREFS_PATH = os.path.join(os.path.expanduser("~"), ".walach_transmitter_configurator.json")

# Centralized colors for the custom Tk/ttk styling. Keeping them here makes it
# easier to adjust the visual design without searching through the UI code.
COLORS = {
    "bg": "#f3f6f8",
    "panel": "#ffffff",
    "panel_alt": "#eaf0f5",
    "text": "#1e2a33",
    "muted": "#667582",
    "accent": "#0f7f8f",
    "accent_dark": "#0a5f6b",
    "border": "#cfd9e2",
    "success": "#1f8a4c",
}

def resource_path(relative):
    """Resolve bundled PyInstaller assets and normal source-tree assets."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)

# ---- FRAM map constants (mirror of tx_config.h) ----
#
# These addresses and sizes must match the transmitter firmware. Think of FRAM
# as one long byte array. The header starts at address 0, and model slots start
# at MODELS_BASE. Each model gets MODEL_SLOT_SIZE bytes, even though the packed
# model itself currently uses MODEL_BIN_SIZE bytes.
TXCF_MAGIC = 0x54584346
TXCF_VERSION = 0x0001
HDR_ADDR = 0x0000
MODELS_BASE = 0x0100
MODEL_SLOT_SIZE = 64      # slot spacing (matches Tx's TXCF_MODEL_SIZE)
MODEL_BIN_SIZE  = 60      # actual packed model struct size
MAX_SLOTS = 16

# Python's struct module converts between Python values and raw bytes.
#
# The leading "<" means little-endian byte order, which matches the SAMD21 data
# layout used by the firmware.
#
# Quick format guide:
#   I  = unsigned 32-bit integer
#   H  = unsigned 16-bit integer
#   h  = signed 16-bit integer
#   B  = unsigned 8-bit integer
#   b  = signed 8-bit integer
#   16s / 18s / 6s = fixed-length byte strings
HDR_FMT = "<I H H H I 18s"   # 32 bytes header: 4+2+2+2+4+18
# Model (60 bytes total): 16s + H + 4b + 4b + B + B + 4h + 8H + 6s + H(crc)
MODEL_FMT_NOCRC = "<16s H 4b 4b B B 4h 8H 6s"  # 58 bytes
MODEL_FMT       = MODEL_FMT_NOCRC + " H"       # +2 = 60

def validate_model_controls(model: dict) -> dict:
    """Clamp editable controls and reject endpoints that collapse a channel."""
    for i in range(4):
        model["rates"][i] = max(0, min(100, model["rates"][i]))
        model["expo"][i] = max(-100, min(100, model["expo"][i]))
        model["subtrim"][i] = max(-500, min(500, model["subtrim"][i]))
        mn, mx = model["endpoints"][i]
        mn = max(800, min(2200, mn))
        mx = max(800, min(2200, mx))
        if mn >= mx:
            raise ValueError(
                f"{CHANNEL_DEFAULT_NAMES[i]} endpoints must have Min us below Max us"
            )
        model["endpoints"][i] = [mn, mx]
    return model

def crc16_ccitt(data: bytes, poly=0x1021, init=0xFFFF) -> int:
    """Return the CRC used to detect corrupted model bytes in radio storage."""
    crc = init
    for b in data:
        # Move this byte into the top half of the CRC register.
        crc ^= (b << 8) & 0xFFFF
        for _ in range(8):
            # Process one bit at a time using the CCITT polynomial.
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF

def to_hex(b: bytes) -> str:
    """Convert raw bytes to printable hex text for the transmitter protocol."""
    return binascii.hexlify(b).decode("ascii").upper()

def from_hex(s: str) -> bytes:
    """Convert printable hex text from the transmitter back into raw bytes."""
    s = s.strip().replace(" ", "")
    if len(s) % 2 != 0:
        raise ValueError("Hex string must have even length")
    return binascii.unhexlify(s)

class SerialWorker:
    """
    Small wrapper around pyserial.

    Keeping serial communication in this class keeps the GUI code from needing
    to know details like newline endings, ASCII encoding, or how READ/WRITE
    responses are formatted.
    """

    def __init__(self):
        # self.ser is None when disconnected; otherwise it is a serial.Serial.
        self.ser = None
        self.device_info = {}

    def open(self, port):
        # Open the chosen USB serial port at the same baud rate as the firmware.
        try:
            self.ser = serial.Serial(port=port, baudrate=BAUD, timeout=0.5)

            # Give the microcontroller/USB stack a moment to settle, then prove
            # that this is the SAMD21 config service. A V3 transmitter exposes
            # a second USB port from its ESP32; that port accepts role/status
            # commands but cannot access the model FRAM.
            time.sleep(0.2)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            for _ in range(3):
                self.send_line("PING")
                if self.read_line() == "PONG":
                    self.ser.timeout = 1
                    self.send_line("INFO")
                    try:
                        self.device_info = json.loads(self.read_line())
                    except Exception:
                        self.device_info = {}
                    return
            raise RuntimeError(
                "No configurator response. Select the 'Altitude RC TX M0' "
                "port and restart the transmitter while holding Bind (D9) "
                "+ Aileron Trim Right (D5)."
            )
        except Exception:
            self.close()
            raise

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except:
                pass
        self.ser = None

    def send_line(self, line: str):
        # The transmitter command parser expects one ASCII command per line.
        if not self.ser: raise RuntimeError("Not connected")
        self.ser.write((line + "\n").encode("ascii"))

    def read_line(self) -> str:
        # Decode serial bytes into text. errors="ignore" prevents bad bytes from
        # crashing the GUI if the board prints unexpected data.
        if not self.ser: raise RuntimeError("Not connected")
        return self.ser.readline().decode("ascii", errors="ignore").strip()

    def verify_config_mode(self):
        """Prove this SAMD21 is still serving the no-LoRa Config Mode."""
        if not self.ser:
            return False
        self.ser.reset_input_buffer()
        self.send_line("PING")
        return self.read_line() == "PONG"

    # --- Protocol: READ/WRITE ---
    def cmd_read(self, addr: int, length: int) -> bytes:
        # Ask the transmitter for raw persistent-storage bytes.
        self.send_line(f"READ {addr} {length}")
        resp = self.read_line()

        # A successful response looks like:
        #   DATA 00112233AABB...
        if resp == "ERR":
            raise RuntimeError(
                "The transmitter is connected, but its persistent storage did "
                "not answer. Reflash current firmware, then check the FRAM or "
                "M0 internal-flash fallback."
            )
        if not resp.startswith("DATA "):
            raise RuntimeError(f"Unexpected READ response: {resp}")
        hexblob = resp.split(" ", 1)[1].strip()
        return from_hex(hexblob)

    def cmd_write(self, addr: int, data: bytes):
        # Convert bytes into hex because serial commands are plain text.
        hexblob = to_hex(data)
        self.send_line(f"WRITE {addr} {hexblob}")
        resp = self.read_line()
        if resp != "OK":
            raise RuntimeError(f"WRITE failed: {resp}")

class EspRoleWorker:
    """USB-serial client for the V3 transmitter's ESP32-C3 role service."""

    def __init__(self):
        self.ser = None

    def open(self, port):
        try:
            self.ser = serial.Serial(port=port, baudrate=BAUD, timeout=0.25)
            time.sleep(0.35)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            return self.status(timeout=2.0)
        except Exception:
            self.close()
            raise

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def _write(self, command):
        if not self.ser:
            raise RuntimeError("ESP role port is not connected")
        self.ser.write((command + "\n").encode("ascii"))
        self.ser.flush()

    def _read_matching(self, prefixes, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.ser.readline().decode("ascii", errors="ignore").strip()
            if line and any(line.startswith(prefix) for prefix in prefixes):
                return line
        raise RuntimeError("No role-service response from the ESP32-C3")

    @staticmethod
    def parse_status(line):
        if not line.startswith("STATUS "):
            raise ValueError(f"Unexpected ESP response: {line}")
        values = {}
        for field in line.split()[1:]:
            if "=" in field:
                key, value = field.split("=", 1)
                values[key] = value
        for required in ("role", "authority", "mac"):
            if required not in values:
                raise ValueError(f"Incomplete ESP status: {line}")
        return values

    def status(self, timeout=1.5):
        self._write("STATUS")
        return self.parse_status(self._read_matching(("STATUS ",), timeout))

    def set_role(self, role):
        role = role.upper()
        if role not in ("MASTER", "STUDENT"):
            raise ValueError("Role must be MASTER or STUDENT")
        self._write(f"ROLE {role}")
        response = self._read_matching(("OK ", "ERR"), 1.5)
        if not response.startswith(f"OK role={role}"):
            raise RuntimeError(f"Role change failed: {response}")
        verified = self.status()
        if verified.get("role") != role:
            raise RuntimeError(
                f"ESP reported {verified.get('role', 'UNKNOWN')} after writing {role}"
            )
        return verified


class ModelsStore:
    """
    Knows how to turn Python dictionaries into FRAM bytes and back again.

    The rest of the app wants to work with friendly Python data like:

        {"name": "Cub", "rates": [100, 100, 80, 100], ...}

    The transmitter needs a very specific binary layout. This class is the
    translator between those two worlds.
    """

    def __init__(self, worker: SerialWorker):
        # ModelsStore does not talk to serial directly. It uses SerialWorker so
        # all command/response behavior stays in one place.
        self.w = worker

    # --- Header ---
    def read_header(self):
        # The header tells us how many model slots exist, which slots are used,
        # and which slot is currently active on the transmitter.
        b = self.w.cmd_read(HDR_ADDR, 32)

        # struct.unpack returns a tuple of fields in the order described by
        # HDR_FMT. The final "_" field is reserved bytes we do not currently use.
        magic, ver, total_slots, active_slot, used_bitmap, _ = struct.unpack(HDR_FMT, b)
        return dict(magic=magic, ver=ver, total_slots=total_slots,
                    active_slot=active_slot, used_bitmap=used_bitmap)

    def write_header(self, hdr):
        # Pack the Python header dictionary into the exact 32-byte header the
        # firmware expects. Reserved bytes are written as zeroes.
        b = struct.pack(HDR_FMT, hdr["magic"], hdr["ver"],
                        hdr["total_slots"], hdr["active_slot"],
                        hdr["used_bitmap"], b"\x00"*18)
        self.w.cmd_write(HDR_ADDR, b)

    def ensure_header(self):
        # If FRAM is blank or contains an old/incompatible format, create a
        # fresh header instead of letting the rest of the GUI fail mysteriously.
        try:
            hdr = self.read_header()
            if hdr["magic"] != TXCF_MAGIC or hdr["ver"] != TXCF_VERSION:
                raise ValueError("Bad magic/version")
            return hdr
        except Exception:
            hdr = dict(magic=TXCF_MAGIC, ver=TXCF_VERSION,
                       total_slots=MAX_SLOTS, active_slot=0, used_bitmap=0)
            self.write_header(hdr)
            return hdr

    # --- Model slots ---
    def slot_addr(self, slot: int) -> int:
        # Slot addresses are evenly spaced. Example:
        #   slot 0 -> MODELS_BASE
        #   slot 1 -> MODELS_BASE + 64
        #   slot 2 -> MODELS_BASE + 128
        return MODELS_BASE + slot * MODEL_SLOT_SIZE

    def read_model(self, slot: int):
        # Read full 64B slot; unpack the first 60B model
        b_full = self.w.cmd_read(self.slot_addr(slot), MODEL_SLOT_SIZE)
        b = b_full[:MODEL_BIN_SIZE]
        tup = struct.unpack(MODEL_FMT, b)

        # Pull each field out of the unpacked tuple. The indexes here match
        # MODEL_FMT above and the firmware struct layout.
        name_raw, bind_code = tup[0], tup[1]
        rates = list(tup[2:6])
        expo  = list(tup[6:10])
        dr_switch = tup[10]
        active_rates = tup[11]
        subtrim = list(tup[12:16])
        ep_flat = list(tup[16:24])  # 8 ushorts
        endpoints = [[ep_flat[i*2+0], ep_flat[i*2+1]] for i in range(4)]
        crc_stored = tup[25]

        # Model names are stored as fixed 16-byte strings. Anything after the
        # first zero byte is padding, not part of the actual name.
        name = name_raw.split(b'\x00',1)[0].decode('utf-8', errors='ignore')

        # Recalculate the CRC so the GUI can warn when FRAM bytes look corrupt.
        crc_calc = crc16_ccitt(b[:58])  # CRC over first 58 bytes (no CRC field)

        # reserved bytes (6s) at index 24 => reverse mask stored in reserved[0]
        #
        # One byte can hold eight true/false flags. We only need four:
        #   bit 0 = channel 0 reversed
        #   bit 1 = channel 1 reversed
        #   bit 2 = channel 2 reversed
        #   bit 3 = channel 3 reversed
        reserved = tup[24]
        rev_mask = reserved[0] if isinstance(reserved, (bytes, bytearray)) and len(reserved) > 0 else 0
        reverse = [bool((rev_mask >> i) & 1) for i in range(4)]
        mix_enabled = bool(reserved[1] & 0x01) if len(reserved) > 1 else False
        mix_percent = struct.unpack("b", reserved[2:3])[0] if len(reserved) > 2 else 0
        mix_percent = max(-100, min(100, mix_percent))

        # Return a plain dictionary because it is easy for the GUI and JSON
        # import/export code to work with.
        return dict(name=name, bind_code=bind_code, rates=rates, expo=expo,
                dr_switch=dr_switch, active_rates=active_rates,
                subtrim=subtrim, endpoints=endpoints,
                reverse=reverse,
                ail_to_rud_mix_enabled=mix_enabled,
                ail_to_rud_mix_percent=mix_percent,
                crc_ok=(crc_stored == crc_calc))

    def write_model(self, slot: int, model):
        # The firmware name field is exactly 16 bytes. We keep 15 bytes for text
        # and force the final byte to zero so the C++ code sees a terminated
        # string.
        name_bytes = model["name"].encode("utf-8")[:15] + b"\x00"
        name_bytes = name_bytes.ljust(16, b"\x00")

        # Clamp each setting to the same safe range the transmitter expects.
        # This prevents a bad GUI value or imported JSON file from writing
        # nonsense into FRAM.
        bind_code = int(model["bind_code"]) & 0x7FFF
        rates = [int(max(0, min(100, r))) for r in model["rates"]]
        expo  = [int(max(-100, min(100, e))) for e in model["expo"]]
        dr_switch = int(model["dr_switch"]) & 0xFF
        active_rates = 1 if model["active_rates"] else 0
        subtrim = [int(max(-500, min(500, s))) for s in model["subtrim"]]

        # The firmware stores endpoints as one flat list:
        #   ch0 min, ch0 max, ch1 min, ch1 max, ...
        # The GUI keeps them grouped by channel, so flatten them before packing.
        ep_flat = []
        for ch in range(4):
            mn, mx = model["endpoints"][ch]
            ep_flat += [int(mn), int(mx)]

        # Build reserved bytes and include reverse mask in reserved[0]
        #
        # Example: if channels 0 and 2 are reversed:
        #   rev_mask = 00000101 binary = 0x05
        rev_mask = 0
        if "reverse" in model:
            for i in range(4):
                if model["reverse"][i]: rev_mask |= (1 << i)
        mix_enabled = bool(model.get("ail_to_rud_mix_enabled", False))
        mix_percent = int(max(-100, min(100, model.get("ail_to_rud_mix_percent", 0))))
        mix_flags = 0x01 if mix_enabled else 0x00
        reserved = bytes([rev_mask, mix_flags]) + struct.pack("b", mix_percent) + b"\x00"*3

        # Pack everything except the CRC first, because the CRC is calculated
        # over these first 58 bytes.
        packed_no_crc = struct.pack(MODEL_FMT_NOCRC, name_bytes, bind_code,
                                    *rates, *expo, dr_switch, active_rates,
                                    *subtrim, *ep_flat, reserved)

        # CRC over first 58 bytes
        crc = crc16_ccitt(packed_no_crc)
        b = packed_no_crc + struct.pack("<H", crc)  # 58 + 2 = 60

        # Pad to 64 for slot spacing
        b_padded = b + b"\x00" * (MODEL_SLOT_SIZE - MODEL_BIN_SIZE)
        self.w.cmd_write(self.slot_addr(slot), b_padded)

class ChannelLabelStore:
    """
    Saves friendly channel names on the computer running the GUI.

    This is intentionally separate from ModelsStore because channel descriptors
    are not part of the transmitter firmware struct. The transmitter still only
    knows channel numbers 0..3; the GUI remembers labels like "Throttle" or
    "Camera Tilt" for the user's convenience.
    """

    def __init__(self, path=LOCAL_PREFS_PATH):
        self.path = path
        self.labels = {}
        self.load()

    def load(self):
        # If the preferences file is missing or malformed, fall back quietly to
        # default names. The GUI should still open even if local preferences fail.
        try:
            source = self.path
            if source == LOCAL_PREFS_PATH and not os.path.exists(source) and os.path.exists(LEGACY_PREFS_PATH):
                source = LEGACY_PREFS_PATH
            with open(source, "r") as f:
                data = json.load(f)
            self.labels = data.get("channel_labels", {})
        except Exception:
            self.labels = {}

    def save(self):
        # Save all known slot label sets to a small JSON file in the user's home
        # directory. JSON keeps it human-readable and easy to repair by hand.
        folder = os.path.dirname(self.path)
        if folder and not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({"channel_labels": self.labels}, f, indent=2)

    def get(self, slot):
        # Slot keys are strings in JSON, so convert the numeric slot to str.
        values = self.labels.get(str(slot), CHANNEL_DEFAULT_NAMES)

        # Always return exactly four labels so the rest of the GUI can index
        # labels[0], labels[1], labels[2], and labels[3] safely.
        values = list(values[:4])
        while len(values) < 4:
            values.append(CHANNEL_DEFAULT_NAMES[len(values)])
        return values

    def set(self, slot, names):
        # Clean up user-entered labels. Blank names fall back to defaults and
        # very long names are shortened so they fit nicely in the table.
        cleaned = []
        for i, name in enumerate(names[:4]):
            fallback = CHANNEL_DEFAULT_NAMES[i]
            cleaned.append((str(name).strip() or fallback)[:24])
        self.labels[str(slot)] = cleaned
        self.save()

    def clear(self, slot):
        # When a model slot is deleted, forget its local channel labels too.
        if str(slot) in self.labels:
            del self.labels[str(slot)]
            self.save()

class App(tk.Tk):
    """
    Main Tkinter window.

    Tkinter apps are usually structured around callbacks. A callback is a
    function that runs when the user clicks a button, changes a value, or causes
    some other event. Methods named on_* below are mostly button callbacks.
    """

    def __init__(self):
        super().__init__()

        # Basic window setup.
        self.title(APP_TITLE)
        self.geometry("1120x760")
        self.minsize(980, 650)
        self.configure(bg=COLORS["bg"])

        # Create helper objects used by the UI callbacks.
        self.w = SerialWorker()
        self.role_worker = EspRoleWorker()
        self.store = ModelsStore(self.w)
        self.channel_labels = ChannelLabelStore()
        self.firmware_release = None
        self.firmware_busy = False

        # Tracks which slot was last loaded into the editor. The selected slot
        # in the list is still the source of truth when saving.
        self.current_slot = None

        # Build the visual pieces of the app.
        self._install_app_icon()
        self._install_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Populate the serial-port dropdown right away.
        self.refresh_ports()

    def _install_app_icon(self):
        try:
            self._app_icon = tk.PhotoImage(file=resource_path("assets/altitude_unknown_icon.png"))
            self.iconphoto(True, self._app_icon)
        except Exception:
            # Icons are nice-to-have. If a platform rejects this icon setup, the
            # app should still run normally.
            pass

    def _install_style(self):
        # ttk widgets are styled through a shared Style object rather than by
        # setting colors on every widget individually.
        style = ttk.Style(self)

        # "clam" is one of the more themeable built-in ttk themes.
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # General app fonts and colors.
        style.configure(".", background=COLORS["bg"], foreground=COLORS["text"], font=("Helvetica", 11))
        style.configure("TFrame", background=COLORS["bg"])

        # Custom named styles. Widgets opt into these with style="Panel.TFrame",
        # style="Header.TLabel", etc.
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure("Header.TFrame", background=COLORS["accent_dark"])
        style.configure("Header.TLabel", background=COLORS["accent_dark"], foreground="#ffffff", font=("Helvetica", 18, "bold"))
        style.configure("HeaderSub.TLabel", background=COLORS["accent_dark"], foreground="#d9f3f6", font=("Helvetica", 11))
        style.configure("Status.TLabel", background=COLORS["accent_dark"], foreground="#d9f3f6", font=("Helvetica", 10, "bold"))
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("Panel.TLabel", background=COLORS["panel"], foreground=COLORS["text"])
        style.configure("Muted.TLabel", background=COLORS["panel"], foreground=COLORS["muted"])
        style.configure("TLabelframe", background=COLORS["panel"], bordercolor=COLORS["border"], relief="solid")
        style.configure("TLabelframe.Label", background=COLORS["panel"], foreground=COLORS["accent_dark"], font=("Helvetica", 11, "bold"))
        style.configure("TButton", padding=(12, 7), background=COLORS["panel_alt"], foreground=COLORS["text"], bordercolor=COLORS["border"])
        style.map("TButton", background=[("active", "#dce8ef")])
        style.configure("Accent.TButton", background=COLORS["accent"], foreground="#ffffff", bordercolor=COLORS["accent"])
        style.map("Accent.TButton", background=[("active", COLORS["accent_dark"])])
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 8), background=COLORS["panel_alt"], foreground=COLORS["muted"])
        style.map("TNotebook.Tab", background=[("selected", COLORS["panel"])], foreground=[("selected", COLORS["accent_dark"])])
        style.configure("Treeview", rowheight=30, fieldbackground=COLORS["panel"], background=COLORS["panel"], foreground=COLORS["text"], bordercolor=COLORS["border"])
        style.configure("Treeview.Heading", background=COLORS["panel_alt"], foreground=COLORS["accent_dark"], font=("Helvetica", 10, "bold"))
        style.map("Treeview", background=[("selected", "#cfe9ed")], foreground=[("selected", COLORS["text"])])

    def _build_ui(self):
        # Header band across the top of the window.
        header = ttk.Frame(self, padding=(18, 14), style="Header.TFrame")
        header.pack(fill='x')
        try:
            self._header_logo = tk.PhotoImage(file=resource_path("assets/altitude_unknown_icon.png")).subsample(7, 7)
            ttk.Label(header, image=self._header_logo, style="Header.TLabel").pack(side='left', padx=(0, 14))
        except Exception:
            pass
        title_area = ttk.Frame(header, style="Header.TFrame")
        title_area.pack(side='left', fill='x', expand=True)
        ttk.Label(title_area, text=APP_TITLE, style="Header.TLabel").pack(anchor='w')
        ttk.Label(title_area, text="Transmitter setup, receiver updates, and flight-system tools", style="HeaderSub.TLabel").pack(anchor='w', pady=(2, 0))

        # Serial connection controls. The user chooses a USB port, then connects
        # to the transmitter while it is in Config Mode.
        top = ttk.Frame(self, padding=(14, 12), style="Panel.TFrame")
        top.pack(fill='x', padx=14, pady=(14, 0))
        ttk.Label(top, text="Serial Port:", style="Panel.TLabel").pack(side='left')
        self.port_var = tk.StringVar()
        self.port_cmb = ttk.Combobox(top, textvariable=self.port_var, width=30, state="readonly")
        self.port_cmb.pack(side='left', padx=6)
        ttk.Button(top, text="Refresh", command=self.refresh_ports).pack(side='left')
        self.connect_btn = ttk.Button(top, text="Connect", command=self.on_connect)
        self.connect_btn.pack(side='left', padx=6)
        self.status_lbl = ttk.Label(header, text="Not connected", style="Status.TLabel")
        self.status_lbl.pack(side='right', padx=4)

        # Notebook allows more tabs later. Right now it only contains Models.
        self.nb = ttk.Notebook(self); self.nb.pack(fill='both', expand=True, padx=14, pady=14)

        # --- Models tab ---
        self.tab_models = ttk.Frame(self.nb, padding=12, style="Panel.TFrame")
        self.nb.add(self.tab_models, text="Models")

        # Left side: list of all FRAM model slots.
        left = ttk.Frame(self.tab_models, style="Panel.TFrame"); left.pack(side='left', fill='y', padx=(0,14))
        ttk.Label(left, text="Model Slots", style="Panel.TLabel", font=("Helvetica", 12, "bold")).pack(anchor='w', pady=(0, 6))
        self.models_list = tk.Listbox(left, width=34, height=27, relief="flat", highlightthickness=1,
                                      highlightbackground=COLORS["border"], selectbackground=COLORS["accent"],
                                      selectforeground="#ffffff", bg="#f8fafb", fg=COLORS["text"],
                                      activestyle="none", font=("Menlo", 11))
        self.models_list.pack(side='top', fill='y')
        btns = ttk.Frame(left, style="Panel.TFrame"); btns.pack(side='top', pady=10)
        ttk.Button(btns, text="New", command=self.on_new_model).grid(row=0, column=0, padx=2)
        ttk.Button(btns, text="Rename", command=self.on_rename_model).grid(row=0, column=1, padx=2)
        ttk.Button(btns, text="Delete", command=self.on_delete_model).grid(row=0, column=2, padx=2)
        ttk.Button(btns, text="Set Active", command=self.on_set_active).grid(row=0, column=3, padx=2)

        # Right side: editor for the selected model's values.
        right = ttk.Frame(self.tab_models, style="Panel.TFrame"); right.pack(side='left', fill='both', expand=True)
        form = ttk.Frame(right, style="Panel.TFrame"); form.pack(fill='x', pady=(0, 10))

        # Tk variables keep widget state synchronized with Python values.
        # For example, editing the Model Name entry changes self.name_var.
        self.name_var = tk.StringVar()
        self.bind_var = tk.StringVar(value="0")
        self.bind_changed = False
        self.dr_active_var = tk.BooleanVar(value=False)
        self.dr_switch_var = tk.StringVar(value="0")
        self.ail_rud_mix_enabled_var = tk.BooleanVar(value=False)
        self.ail_rud_mix_percent_var = tk.IntVar(value=30)

        ttk.Label(form, text="Model Name", style="Panel.TLabel").grid(row=0, column=0, sticky='e', pady=4)
        ttk.Entry(form, textvariable=self.name_var, width=24).grid(row=0, column=1, sticky='w', padx=6)

        ttk.Label(form, text="Bind Code", style="Panel.TLabel").grid(row=0, column=2, sticky='e')
        ttk.Entry(form, textvariable=self.bind_var, width=10, state="readonly").grid(row=0, column=3, sticky='w', padx=6)
        def gen_bind():
            # A bind code identifies a transmitter/receiver pair. Changing it is
            # intentionally gated by a warning because the receiver must be
            # rebound afterward.
            if messagebox.askyesno("Change Bind Code", "Generate a new bind code for this model?\n\nThe receiver must be rebound after this change."):
                self.bind_var.set(str(random.randint(1, 65535)))
                self.bind_changed = True
        ttk.Button(form, text="New Bind", command=gen_bind).grid(row=0, column=4, sticky='w', padx=4)

        ttk.Label(form, text="DR Switch", style="Panel.TLabel").grid(row=0, column=5, sticky='e')
        ttk.Entry(form, textvariable=self.dr_switch_var, width=6).grid(row=0, column=6, sticky='w', padx=6)
        ttk.Checkbutton(form, text="High Rates Active", variable=self.dr_active_var).grid(row=0, column=7, sticky='w', padx=6)

        mix_frame = ttk.LabelFrame(right, text="Control Mixing", padding=(12, 8))
        mix_frame.pack(fill='x', pady=(0, 6))
        ttk.Checkbutton(
            mix_frame, text="Mix aileron into rudder",
            variable=self.ail_rud_mix_enabled_var
        ).pack(side='left')
        ttk.Label(mix_frame, text="Rudder amount:", style="Panel.TLabel").pack(side='left', padx=(18, 5))
        ttk.Spinbox(
            mix_frame, from_=-100, to=100, increment=5, width=6,
            textvariable=self.ail_rud_mix_percent_var
        ).pack(side='left')
        ttk.Label(
            mix_frame,
            text="%  (negative reverses the mix direction)",
            style="Muted.TLabel"
        ).pack(side='left', padx=5)

        # Editable channel table. A Treeview is normally read-only, so the
        # _install_cell_editor method below adds double-click editing behavior.
        table_frame = ttk.LabelFrame(right, text="Channels: double-click a channel name or value to edit")
        table_frame.pack(fill='x', pady=6)
        cols = ("Channel", "Rate%", "Expo%", "Subtrim", "Min us", "Max us", "Reverse")
        self.tree = ttk.Treeview(table_frame, columns=cols, show='headings', height=6)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=120, anchor='center')
        self.tree.column("Channel", width=170, anchor='w')
        self.tree.pack(fill='x')
        self.tree.tag_configure("odd", background="#f8fafb")
        self.tree.tag_configure("even", background="#eef5f7")

        # Insert the rows in receiver-style TAER order, but keep each row's iid
        # as "ch0", "ch1", etc. That iid is how collect_editor knows which
        # firmware channel array index to update.
        for row, ch in enumerate(CHANNEL_DISPLAY_ORDER):
            tag = "even" if row % 2 == 0 else "odd"
            self.tree.insert("", "end", iid=f"ch{ch}", values=(CHANNEL_DEFAULT_NAMES[ch], 100, 0, 0, 1000, 2000, "No"), tags=(tag,))

        # Make table cells editable on double-click
        self._install_cell_editor(self.tree)

        bottom = ttk.Frame(right, style="Panel.TFrame"); bottom.pack(fill='x', pady=12)
        ttk.Button(bottom, text="Load From Radio", command=self.on_load_slot).pack(side='left')
        ttk.Button(bottom, text="Save To Radio", command=self.on_save_slot, style="Accent.TButton").pack(side='left', padx=6)
        ttk.Button(bottom, text="Export Model (.json)", command=self.on_export_model).pack(side='left', padx=6)
        ttk.Button(bottom, text="Import Model (.json)", command=self.on_import_model).pack(side='left', padx=6)

        self._build_role_tab()
        self._build_firmware_tab()

    def _build_firmware_tab(self):
        """Build the guided SAMD21/ESP32-C3 firmware updater."""
        self.tab_firmware = ttk.Frame(self.nb, style="Panel.TFrame")
        self.nb.add(self.tab_firmware, text="Firmware Update")

        # This form is intentionally detailed, and can be taller than the usable
        # window on laptops or displays with increased scaling.  Keep it in a
        # canvas so every control, especially the flash button at the bottom,
        # remains reachable.
        firmware_canvas = tk.Canvas(
            self.tab_firmware, background=COLORS["panel"], highlightthickness=0)
        firmware_scrollbar = ttk.Scrollbar(
            self.tab_firmware, orient="vertical", command=firmware_canvas.yview)
        firmware_canvas.configure(yscrollcommand=firmware_scrollbar.set)
        firmware_scrollbar.pack(side="right", fill="y")
        firmware_canvas.pack(side="left", fill="both", expand=True)

        content = ttk.Frame(firmware_canvas, padding=22, style="Panel.TFrame")
        content_window = firmware_canvas.create_window(
            (0, 0), window=content, anchor="nw")

        def resize_firmware_content(event):
            firmware_canvas.itemconfigure(content_window, width=event.width)

        def update_firmware_scrollregion(_event=None):
            firmware_canvas.configure(scrollregion=firmware_canvas.bbox("all"))

        def scroll_firmware(event):
            if event.delta:
                firmware_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

        firmware_canvas.bind("<Configure>", resize_firmware_content)
        content.bind("<Configure>", update_firmware_scrollregion)
        firmware_canvas.bind("<MouseWheel>", scroll_firmware)
        content.bind("<MouseWheel>", scroll_firmware)
        firmware_canvas.bind("<Button-4>", lambda _event: firmware_canvas.yview_scroll(-1, "units"))
        firmware_canvas.bind("<Button-5>", lambda _event: firmware_canvas.yview_scroll(1, "units"))

        ttk.Label(content, text="RC Firmware Update", style="Panel.TLabel",
                  font=("Helvetica", 16, "bold")).pack(anchor="w")
        ttk.Label(
            content,
            text=("Download verified firmware from the latest Altitude Unknown GitHub release. "
                  "Keep the aircraft powered off and remove its propeller before updating."),
            style="Muted.TLabel", wraplength=850, justify="left"
        ).pack(anchor="w", pady=(5, 16))

        release_frame = ttk.LabelFrame(content, text="Latest release", padding=14)
        release_frame.pack(fill="x")
        release_row = ttk.Frame(release_frame, style="Panel.TFrame")
        release_row.pack(fill="x")
        self.firmware_release_var = tk.StringVar(value="Not checked")
        ttk.Label(release_row, textvariable=self.firmware_release_var,
                  style="Panel.TLabel", font=("Menlo", 11, "bold")).pack(side="left", fill="x", expand=True)
        self.firmware_check_btn = ttk.Button(
            release_row, text="Check GitHub", command=self.on_check_firmware)
        self.firmware_check_btn.pack(side="right")

        target_frame = ttk.LabelFrame(content, text="Processors to update", padding=14)
        target_frame.pack(fill="x", pady=14)
        self.firmware_target_var = tk.StringVar(value="tx_both")
        for text, value in (("Transmitter — both processors (recommended)", "tx_both"),
                            ("Transmitter M0 only", "tx_samd21"),
                            ("Transmitter ESP32-C3 only", "tx_esp32c3"),
                            ("Receiver", "receiver_samd21")):
            ttk.Radiobutton(target_frame, text=text, value=value,
                            variable=self.firmware_target_var,
                            command=self._update_firmware_instructions).pack(anchor="w", pady=2)

        samd_port_frame = ttk.LabelFrame(content, text="Transmitter M0 or receiver USB port", padding=14)
        samd_port_frame.pack(fill="x")
        samd_port_row = ttk.Frame(samd_port_frame, style="Panel.TFrame")
        samd_port_row.pack(fill="x")
        self.firmware_samd_port_var = tk.StringVar()
        self.firmware_samd_port_cmb = ttk.Combobox(
            samd_port_row, textvariable=self.firmware_samd_port_var, width=52, state="readonly")
        self.firmware_samd_port_cmb.pack(side="left")
        ttk.Button(samd_port_row, text="Refresh Ports", command=self.refresh_ports).pack(side="left", padx=8)
        ttk.Label(
            samd_port_frame,
            text="Used for automatic bootloader entry; manual RESET remains available as a fallback.",
            style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

        port_frame = ttk.LabelFrame(content, text="Transmitter ESP32-C3 USB port", padding=14)
        port_frame.pack(fill="x", pady=(14, 0))
        port_row = ttk.Frame(port_frame, style="Panel.TFrame")
        port_row.pack(fill="x")
        self.firmware_esp_port_var = tk.StringVar()
        self.firmware_esp_port_cmb = ttk.Combobox(
            port_row, textvariable=self.firmware_esp_port_var, width=52, state="readonly")
        self.firmware_esp_port_cmb.pack(side="left")
        ttk.Button(port_row, text="Refresh Ports", command=self.refresh_ports).pack(side="left", padx=8)
        ttk.Label(
            port_frame,
            text="Use the small ESP USB connector. The Altitude RC TX M0 port is the other processor.",
            style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

        guide = ttk.LabelFrame(content, text="Connection guide", padding=14)
        guide.pack(fill="x", pady=14)
        self.firmware_guide_var = tk.StringVar()
        ttk.Label(guide, textvariable=self.firmware_guide_var, style="Panel.TLabel",
                  wraplength=850, justify="left").pack(anchor="w")

        action_row = ttk.Frame(content, style="Panel.TFrame")
        action_row.pack(fill="x")
        self.firmware_flash_btn = ttk.Button(
            action_row, text="Download and Flash Latest", style="Accent.TButton",
            command=self.on_flash_firmware, state="disabled")
        self.firmware_flash_btn.pack(side="left")
        self.firmware_progress_var = tk.StringVar(value="Check GitHub to begin.")
        ttk.Label(action_row, textvariable=self.firmware_progress_var,
                  style="Muted.TLabel").pack(side="left", padx=14)
        self._update_firmware_instructions()

    def _update_firmware_instructions(self):
        target = self.firmware_target_var.get()
        samd = ("SAMD21: select its USB port. The configurator will request bootloader mode "
                "automatically; use a RESET double-tap only if automatic entry fails.")
        esp = ("ESP32-C3: connect the small ESP USB connector and select it above. The updater "
               "will enter its bootloader automatically; if asked, hold BOOT and tap RESET.")
        receiver = ("Receiver: remove the propeller, select the receiver USB port, and update. "
                    "Afterward, rebind it and verify controls and failsafe before flight.")
        if target == "tx_both": guide = samd + "\n\n" + esp
        elif target == "tx_esp32c3": guide = esp
        elif target == "receiver_samd21": guide = receiver
        else: guide = samd
        self.firmware_guide_var.set(guide)

    def _set_firmware_busy(self, busy, status=None):
        self.firmware_busy = busy
        self.firmware_check_btn.config(state="disabled" if busy else "normal")
        can_flash = (not busy and self.firmware_release is not None)
        self.firmware_flash_btn.config(state="normal" if can_flash else "disabled")
        if status:
            self.firmware_progress_var.set(status)

    def _firmware_thread(self, work, completed):
        def runner():
            try:
                result = work()
                self.after(0, lambda: completed(result, None))
            except Exception as exc:
                self.after(0, lambda exc=exc: completed(None, exc))
        threading.Thread(target=runner, daemon=True).start()

    def on_check_firmware(self):
        if self.firmware_busy:
            return
        self._set_firmware_busy(True, "Checking GitHub…")

        def completed(result, error):
            self.firmware_release = result
            self._set_firmware_busy(False, "Ready to update." if result else "Update check failed.")
            if error:
                messagebox.showerror("Firmware update", str(error))
                return
            published = result.get("published_at", "")[:10]
            self.firmware_release_var.set(f"{result['name']}  •  {published}")
        self._firmware_thread(firmware_updater.fetch_latest_firmware, completed)

    def _selected_firmware_esp_port(self):
        selection = self.firmware_esp_port_var.get().strip()
        return self.esp_port_devices.get(selection, selection)

    def _selected_firmware_samd_port(self):
        selection = self.firmware_samd_port_var.get().strip()
        return self.firmware_samd_port_devices.get(selection, selection)

    def on_flash_firmware(self):
        if self.firmware_busy or not self.firmware_release:
            return
        target = self.firmware_target_var.get()
        targets = {
            "tx_both": ["samd21", "esp32c3"],
            "tx_samd21": ["samd21"],
            "tx_esp32c3": ["esp32c3"],
            "receiver_samd21": ["receiver_samd21"],
        }[target]
        esp_port = self._selected_firmware_esp_port()
        samd_port = self._selected_firmware_samd_port()
        if "esp32c3" in targets and not esp_port:
            messagebox.showerror("Firmware update", "Select the ESP32-C3 USB port before flashing.")
            return
        if any(item in targets for item in ("samd21", "receiver_samd21")) and not samd_port:
            messagebox.showerror("Firmware update", "Select the transmitter M0 or receiver USB port before flashing.")
            return
        samd_selection = self.firmware_samd_port_var.get().strip()
        samd_kind = self.firmware_samd_port_kinds.get(samd_selection, "unknown")
        expected_kind = "receiver" if "receiver_samd21" in targets else "transmitter"
        if any(item in targets for item in ("samd21", "receiver_samd21")) and \
                samd_kind != "unknown" and samd_kind != expected_kind:
            messagebox.showerror(
                "Wrong SAMD21 device selected",
                f"The selected USB port identifies as a {samd_kind}, but this update targets the "
                f"{expected_kind}. Select the correct port before continuing.")
            return
        receiver_warning = ("\n\nReceiver firmware can clear its bind code. You must rebind and "
                            "perform a complete control and failsafe check.") if "receiver_samd21" in targets else ""
        if not messagebox.askyesno(
                "Confirm firmware update",
                "Keep the aircraft powered off and remove the propeller. Do not unplug USB while "
                "a processor is being written." + receiver_warning +
                "\n\nContinue with the latest verified firmware?"):
            return
        self.w.close()
        self.role_worker.close()
        self.connect_btn.config(text="Connect")
        self.esp_connect_btn.config(text="Connect")
        self._set_firmware_busy(True, "Preparing firmware…")

        def work():
            for current in targets:
                label = {"samd21": "Transmitter M0", "esp32c3": "Transmitter ESP32-C3",
                         "receiver_samd21": "Receiver"}[current]
                self.after(0, lambda label=label: self.firmware_progress_var.set(f"Downloading {label} firmware…"))
                image = firmware_updater.download_firmware(self.firmware_release, current)
                try:
                    if current == "receiver_samd21":
                        self.after(0, lambda: self.firmware_progress_var.set(
                            "Entering the receiver bootloader…"))
                        try:
                            mount = firmware_updater.enter_receiver_uf2(samd_port)
                        except firmware_updater.FirmwareUpdateError:
                            # Original Receiver V4 boards use SAM-BA rather than
                            # the UF2 bootloader fitted to newer receivers.
                            self.after(0, lambda: self.firmware_progress_var.set(
                                "UF2 not detected; trying the legacy receiver bootloader…"))
                            legacy_image = firmware_updater.download_firmware(
                                self.firmware_release, current, serial_image=True)
                            try:
                                firmware_updater.flash_receiver_samba(legacy_image, samd_port)
                            finally:
                                try:
                                    Path(legacy_image).unlink()
                                except OSError:
                                    pass
                        else:
                            self.after(0, lambda: self.firmware_progress_var.set(
                                "Flashing receiver through its UF2 bootloader…"))
                            firmware_updater.flash_samd_uf2(image, mount, "ALTITUDE_RX.UF2")
                        time.sleep(2)
                    elif current == "samd21":
                        self.after(0, lambda label=label: self.firmware_progress_var.set(
                            f"Requesting automatic bootloader mode on {label}…"))
                        try:
                            mount = firmware_updater.enter_samd_uf2(samd_port)
                        except firmware_updater.FirmwareUpdateError as auto_error:
                            before = firmware_updater.uf2_mounts()
                            proceed = threading.Event()
                            answer = {"yes": False}
                            def prompt_samd():
                                answer["yes"] = messagebox.askokcancel(
                                    "Automatic bootloader entry failed",
                                    f"{auto_error}\n\nDouble-tap the device RESET button, then click OK. "
                                    "The configurator will continue waiting for its UF2 drive.")
                                proceed.set()
                            self.after(0, prompt_samd)
                            proceed.wait()
                            if not answer["yes"]:
                                raise firmware_updater.FirmwareUpdateError("Firmware update cancelled.")
                            mount = firmware_updater.wait_for_new_uf2_mount(before)
                        firmware_updater.flash_samd_uf2(image, mount, "ALTITUDE_TX.UF2")
                        time.sleep(2)
                    else:
                        self.after(0, lambda: self.firmware_progress_var.set("Flashing ESP32-C3…"))
                        firmware_updater.flash_esp32(image, esp_port)
                finally:
                    try:
                        os.unlink(image)
                    except OSError:
                        pass
            return targets

        def completed(result, error):
            self._set_firmware_busy(False, "Update complete." if result else "Update stopped.")
            self.refresh_ports()
            if error:
                messagebox.showerror(
                    "Firmware update failed",
                    f"{error}\n\nNo other processor will be flashed. If this was the ESP32-C3, "
                    "hold BOOT, tap RESET, release BOOT, and try again.")
                return
            names = " and ".join({"samd21": "Transmitter M0", "esp32c3": "Transmitter ESP32-C3",
                                  "receiver_samd21": "Receiver"}[item] for item in result)
            followup = (" Rebind the receiver, then verify every control and failsafe before flight."
                        if "receiver_samd21" in result else
                        " Power-cycle the transmitter, reconnect, and verify its models and controls before flight.")
            messagebox.showinfo(
                "Firmware update complete",
                f"Updated {names}." + followup)
        self._firmware_thread(work, completed)

    def _build_role_tab(self):
        """Build the guarded ESP32 instructor/student role controls."""
        self.tab_roles = ttk.Frame(self.nb, padding=22, style="Panel.TFrame")
        self.nb.add(self.tab_roles, text="Instructor / Student")

        ttk.Label(self.tab_roles, text="Transmitter Role", style="Panel.TLabel",
                  font=("Helvetica", 16, "bold")).pack(anchor="w")
        ttk.Label(
            self.tab_roles,
            text=("Connect the transmitter's ESP32-C3 USB port here. This is the small "
                  "ESP USB connector, not the M0 model-configurator connector."),
            style="Muted.TLabel", wraplength=820, justify="left"
        ).pack(anchor="w", pady=(5, 18))

        connection = ttk.LabelFrame(self.tab_roles, text="ESP32-C3 connection", padding=14)
        connection.pack(fill="x")
        row = ttk.Frame(connection, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="ESP Port:", style="Panel.TLabel").pack(side="left")
        self.esp_port_var = tk.StringVar()
        self.esp_port_cmb = ttk.Combobox(row, textvariable=self.esp_port_var, width=46, state="readonly")
        self.esp_port_cmb.pack(side="left", padx=7)
        ttk.Button(row, text="Refresh", command=self.refresh_role_ports).pack(side="left")
        self.esp_connect_btn = ttk.Button(row, text="Connect", command=self.on_role_connect)
        self.esp_connect_btn.pack(side="left", padx=7)

        details = ttk.LabelFrame(self.tab_roles, text="Detected transmitter", padding=14)
        details.pack(fill="x", pady=16)
        self.role_vars = {
            "mac": tk.StringVar(value="—"), "role": tk.StringVar(value="—"),
            "mode": tk.StringVar(value="—"), "authority": tk.StringVar(value="—"),
            "link": tk.StringVar(value="—"),
        }
        labels = (("ESP MAC address", "mac"), ("Current role", "role"),
                  ("M0 operating mode", "mode"), ("Current authority", "authority"),
                  ("Link counters", "link"))
        for row_number, (caption, key) in enumerate(labels):
            ttk.Label(details, text=caption + ":", style="Panel.TLabel").grid(
                row=row_number, column=0, sticky="e", padx=(0, 10), pady=4)
            ttk.Label(details, textvariable=self.role_vars[key], style="Panel.TLabel",
                      font=("Menlo", 11, "bold")).grid(row=row_number, column=1, sticky="w", pady=4)

        actions = ttk.LabelFrame(self.tab_roles, text="Assign role", padding=14)
        actions.pack(fill="x")
        self.role_safety_var = tk.StringVar(
            value="Connect to the ESP32-C3 to read its role before making changes.")
        ttk.Label(actions, textvariable=self.role_safety_var, style="Muted.TLabel",
                  wraplength=820, justify="left").pack(anchor="w", pady=(0, 12))
        buttons = ttk.Frame(actions, style="Panel.TFrame")
        buttons.pack(anchor="w")
        self.master_role_btn = ttk.Button(
            buttons, text="Set as Instructor (Master)",
            command=lambda: self.on_set_role("MASTER"), state="disabled")
        self.master_role_btn.pack(side="left")
        self.student_role_btn = ttk.Button(
            buttons, text="Set as Student", command=lambda: self.on_set_role("STUDENT"),
            state="disabled")
        self.student_role_btn.pack(side="left", padx=8)
        ttk.Button(buttons, text="Read Status Again", command=self.on_role_refresh).pack(side="left")

    def on_close(self):
        self.w.close()
        self.role_worker.close()
        self.destroy()

    # ---------- Editable Treeview ----------
    def _install_cell_editor(self, tree: ttk.Treeview):
        # Treeview identifies columns as "#1", "#2", etc. Map those internal
        # column IDs to friendly names for validation and error messages.
        editable_cols = {"#1": "Channel", "#2": "Rate%", "#3": "Expo%", "#4": "Subtrim", "#5": "Min us", "#6": "Max us", "#7": "Reverse"}

        # Valid ranges for numeric settings. Values outside these ranges get
        # clamped before being accepted.
        ranges = {
            "Rate%":   (0, 100),
            "Expo%":   (-100, 100),
            "Subtrim": (-500, 500),
            "Min us":  (800, 2200),
            "Max us":  (800, 2200),
        }

        def start_edit(event):
            # Find which table row and column were double-clicked.
            rowid = tree.identify_row(event.y)
            colid = tree.identify_column(event.x)

            # Ignore clicks outside editable cells.
            if not rowid or colid not in editable_cols:
                return

            # bbox gives the pixel rectangle of the clicked cell. We place a
            # normal Entry widget directly on top of that rectangle.
            x, y, w, h = tree.bbox(rowid, colid)
            if w <= 0 or h <= 0:
                return
            cur = tree.set(rowid, colid)

            # For Reverse column, toggle on double-click instead of numeric entry
            heading = editable_cols[colid]
            if heading == "Reverse":
                newval = "No" if cur in ("Yes", "True", "1") else "Yes"
                tree.set(rowid, colid, newval)
                return

            # Create the temporary editor box.
            entry = tk.Entry(tree)
            entry.place(x=x, y=y, width=w, height=h)
            entry.insert(0, cur)
            entry.select_range(0, tk.END)
            entry.focus()

            lo, hi = ranges.get(heading, (None, None))

            def commit():
                # Called when the user presses Enter inside the temporary entry.
                val = entry.get().strip()

                if heading == "Channel":
                    # Channel names are free text, but blank names fall back to
                    # the default for that firmware channel.
                    fallback = CHANNEL_DEFAULT_NAMES[int(rowid.replace("ch", ""))]
                    tree.set(rowid, colid, (val or fallback)[:24])
                    entry.destroy()
                    return

                try:
                    iv = int(val)
                except:
                    messagebox.showerror("Invalid value", f"Enter an integer for {heading}.")
                    return
                # clamp
                iv = max(lo, min(hi, iv))

                # Min/Max consistency
                #
                # Endpoints are a range. If the user enters a min above the max
                # or a max below the min, keep them equal rather than inverted.
                if heading in ("Min us", "Max us"):
                    minv = int(tree.set(rowid, "#5"))
                    maxv = int(tree.set(rowid, "#6"))
                    if heading == "Min us":
                        minv = iv
                        if minv > maxv: maxv = minv
                    else:
                        maxv = iv
                        if maxv < minv: minv = maxv
                    tree.set(rowid, "#5", str(minv))
                    tree.set(rowid, "#6", str(maxv))
                else:
                    tree.set(rowid, colid, str(iv))
                entry.destroy()

            entry.bind("<Return>", lambda e: commit())

            # If the editor loses focus without Enter, discard the partial edit.
            entry.bind("<FocusOut>", lambda e: entry.destroy())

        tree.bind("<Double-1>", start_edit)

    # --- Serial ---
    def refresh_ports(self):
        # Ask pyserial for all currently visible serial ports and place their
        # device names in the dropdown. Prefer the SAMD21 by its assigned USB
        # identity so the V3 ESP32 diagnostic port is not selected by mistake.
        detected = list(list_ports.comports())
        detected.sort(key=lambda p: 0 if (p.vid == 0x03EB and p.pid == 0x2402) else 1)
        self.port_devices = {}
        labels = []
        for p in detected:
            name = p.product or p.description or "Serial device"
            label = f"{name} — {p.device}"
            self.port_devices[label] = p.device
            labels.append(label)
        self.port_cmb["values"] = labels
        if labels:
            self.port_cmb.current(0)
        self.refresh_role_ports(detected)

    def refresh_role_ports(self, detected=None):
        detected = list(detected if detected is not None else list_ports.comports())

        def esp_priority(port):
            text = " ".join(filter(None, (port.product, port.description, port.manufacturer))).lower()
            return 0 if (port.vid == 0x303A or "esp32" in text or "espressif" in text) else 1

        detected.sort(key=esp_priority)
        self.esp_port_devices = {}
        labels = []
        for port in detected:
            name = port.product or port.description or "Serial device"
            label = f"{name} — {port.device}"
            self.esp_port_devices[label] = port.device
            labels.append(label)
        self.esp_port_cmb["values"] = labels
        if labels and self.esp_port_var.get() not in labels:
            self.esp_port_cmb.current(0)
        if hasattr(self, "firmware_esp_port_cmb"):
            self.firmware_esp_port_cmb["values"] = labels
            if labels and self.firmware_esp_port_var.get() not in labels:
                self.firmware_esp_port_cmb.current(0)
        if hasattr(self, "firmware_samd_port_cmb"):
            # The user may deliberately flash either the transmitter M0 or the
            # receiver, so retain all detected ports and show their USB names.
            def samd_priority(port):
                text = " ".join(filter(None, (port.product, port.description, port.manufacturer))).lower()
                return 0 if (port.vid in (0x03EB, 0x239A) or "samd" in text or
                             "feather" in text or "altitude rc tx" in text) else 1
            samd_ports = sorted(detected, key=samd_priority)
            self.firmware_samd_port_devices = {}
            self.firmware_samd_port_kinds = {}
            samd_labels = []
            for port in samd_ports:
                name = port.product or port.description or "Serial device"
                label = f"{name} — {port.device}"
                text = " ".join(filter(None, (port.product, port.description, port.manufacturer))).lower()
                kind = ("transmitter" if "altitude rc tx" in text else
                        "receiver" if ("receiver" in text or "feather m0" in text) else "unknown")
                self.firmware_samd_port_devices[label] = port.device
                self.firmware_samd_port_kinds[label] = kind
                samd_labels.append(label)
            self.firmware_samd_port_cmb["values"] = samd_labels
            if samd_labels and self.firmware_samd_port_var.get() not in samd_labels:
                self.firmware_samd_port_cmb.current(0)

    def _show_role_status(self, status):
        self.role_vars["mac"].set(status.get("mac", "—"))
        self.role_vars["role"].set(status.get("role", "—"))
        self.role_vars["mode"].set(status.get("mode", "Not reported by older firmware"))
        self.role_vars["authority"].set(status.get("authority", "—"))
        counters = [f"{key}={status[key]}" for key in ("sent", "received", "forwarded") if key in status]
        self.role_vars["link"].set("   ".join(counters) or "—")
        # A role button performs its own two-sample activity test before it
        # writes. Do not lock solely from authority: the ESP can retain the
        # last authority string after the SAMD enters Config Mode and stops
        # sending heartbeats.
        self.master_role_btn.config(state="normal")
        self.student_role_btn.config(state="normal")
        if status.get("mode") in ("CONFIG", "SIMULATOR", "SETUP"):
            self.role_safety_var.set(
                f"The M0 reports safe {status['mode']} mode. Keep the aircraft powered off while changing roles.")
        elif status.get("mode"):
            self.role_safety_var.set(
                f"Role changes are locked in {status['mode']} mode. Restart in Config or Simulator mode.")
        elif status.get("authority") == "UNKNOWN":
            self.role_safety_var.set(
                "No flight authority is currently reported. A final M0 activity check will run "
                "before saving. Keep the aircraft powered off.")
        else:
            self.role_safety_var.set(
                "The displayed authority may be live or stale. Select a role to run the final "
                "M0 activity check; saving remains blocked if messages are still arriving.")

    def _clear_role_status(self):
        for value in self.role_vars.values():
            value.set("—")
        self.master_role_btn.config(state="disabled")
        self.student_role_btn.config(state="disabled")
        self.role_safety_var.set("Connect to the ESP32-C3 to read its role before making changes.")

    def on_role_connect(self):
        if self.role_worker.ser:
            self.role_worker.close()
            self.esp_connect_btn.config(text="Connect")
            self._clear_role_status()
            return
        selection = self.esp_port_var.get().strip()
        port = self.esp_port_devices.get(selection, selection)
        if not port:
            messagebox.showerror("ESP role", "Select the ESP32-C3 serial port")
            return
        try:
            status = self.role_worker.open(port)
            self.esp_connect_btn.config(text="Disconnect")
            self._show_role_status(status)
        except Exception as exc:
            messagebox.showerror(
                "ESP connection failed",
                f"{exc}\n\nSelect the ESP32-C3 USB port, not the Altitude RC TX M0 port.")

    def on_role_refresh(self):
        if not self.role_worker.ser:
            messagebox.showerror("ESP role", "Connect the ESP32-C3 port first")
            return
        try:
            self._show_role_status(self.role_worker.status())
        except Exception as exc:
            messagebox.showerror("Status failed", str(exc))

    def on_set_role(self, role):
        friendly = "Instructor (Master)" if role == "MASTER" else "Student"
        try:
            # Two readings more than one firmware heartbeat apart close the
            # short startup window before the M0 reports active authority.
            first = self.role_worker.status()
            time.sleep(1.1)
            second = self.role_worker.status()
            self._show_role_status(second)
            try:
                first_lines = int(first["samd_lines"])
                second_lines = int(second["samd_lines"])
            except (KeyError, TypeError, ValueError):
                raise RuntimeError(
                    "The ESP status did not include its M0 message counter. Reflash the current "
                    "TxV3 Buddy ESP32 firmware before changing roles with the GUI.")
            mode = second.get("mode")
            try:
                mode_fresh = int(second.get("mode_age_ms", "999999")) <= 1500
            except ValueError:
                mode_fresh = False
            if mode and mode_fresh:
                if mode not in ("CONFIG", "SIMULATOR", "SETUP"):
                    raise RuntimeError(
                        f"The M0 reports {mode} mode, so role changes are locked. Keep the aircraft "
                        "powered off and restart in Config or Simulator mode.")
            elif second_lines != first_lines:
                # A master M0 sends AUTHORITY heartbeats even in Config Mode,
                # although that mode returns before LoRa initialization. Older
                # firmware has no MODE field, so prove its safe branch through
                # the independent M0 USB config service.
                config_verified = False
                try:
                    config_verified = self.w.verify_config_mode()
                except Exception:
                    config_verified = False
                if not config_verified:
                    raise RuntimeError(
                        "M0 messages are arriving and Config Mode has not been verified. Connect "
                        "the same transmitter's M0 USB port using the Models connection at the "
                        "top of this window, then try again. Keep the aircraft powered off.")
            current = second.get("role", "UNKNOWN")
            mac = second.get("mac", "unknown")
            if current == role:
                messagebox.showinfo("Role unchanged", f"This transmitter is already {friendly}.")
                return
            confirmed = messagebox.askyesno(
                "Confirm transmitter role",
                f"ESP {mac}\n\nChange role from {current} to {friendly}?\n\n"
                "Confirm the aircraft is powered off. Assign exactly one radio as Master; "
                "incorrect role assignments can prevent control.")
            if not confirmed:
                return
            verified = self.role_worker.set_role(role)
            self._show_role_status(verified)
            messagebox.showinfo(
                "Role saved",
                f"ESP {verified.get('mac', mac)} is now {friendly}.\n\nRestart the transmitter before flight.")
        except Exception as exc:
            messagebox.showerror("Role change failed", str(exc))

    def on_connect(self):
        # The same button handles both connecting and disconnecting.
        if self.w.ser:
            self.w.close()
            self.connect_btn.config(text="Connect")
            self.status_lbl.config(text="Disconnected")
            return

        # If we are not already connected, open the selected serial port.
        selection = self.port_var.get().strip()
        port = self.port_devices.get(selection, selection)
        if not port:
            messagebox.showerror("Error", "Select a serial port")
            return
        try:
            self.w.open(port)
            self.connect_btn.config(text="Disconnect")
            backend = self.w.device_info.get("storage", "transmitter memory").replace("_", " ")
            self.status_lbl.config(text=f"Connected • {backend}")
            self.refresh_model_list()
        except Exception as e:
            messagebox.showerror("Connect failed", str(e))

    # --- Models ops ---
    def refresh_model_list(self):
        # Re-read the FRAM header and rebuild the left-hand slot list.
        hdr = self.store.ensure_header()
        self.models_list.delete(0, "end")

        for i in range(hdr["total_slots"]):
            # used_bitmap is a compact set of flags. Bit i tells us whether
            # model slot i contains a model.
            used = ((hdr["used_bitmap"] >> i) & 1) != 0

            # Mark the active model with an asterisk in the list.
            tag = "*" if i == hdr["active_slot"] else " "
            label = f"{tag} [{i}] "

            if used:
                try:
                    m = self.store.read_model(i)
                    name = m["name"] if m["name"] else "(unnamed)"

                    # Show CRC status so corruption is visible to the user.
                    crc = "OK" if m["crc_ok"] else "BADCRC"
                    label += f"{name}  ({crc})"
                except Exception as e:
                    label += f"(err: {e})"
            else:
                label += "(empty)"
            self.models_list.insert("end", label)

    def get_selected_slot(self):
        # Convert the selected listbox row into a model slot number.
        sel = self.models_list.curselection()
        if not sel:
            messagebox.showerror("Select", "Select a slot from the list")
            return None
        index = sel[0]
        return index

    def on_new_model(self):
        # Find the first unused slot and create a default model there.
        hdr = self.store.ensure_header()
        slot = None
        for i in range(hdr["total_slots"]):
            if ((hdr["used_bitmap"] >> i) & 1) == 0:
                slot = i; break
        if slot is None:
            messagebox.showerror("Full", "No empty slots")
            return

        # Ask the user for a model name. If they cancel or leave it blank, use a
        # simple fallback name based on the slot number.
        name = simpledialog.askstring("New Model", "Model name:") or f"Model{slot}"

        # Default values are conservative: full rate, no expo, centered subtrim,
        # normal direction, and standard 1000-2000 us endpoints.
        model = dict(
            name=name,
            bind_code=random.randint(1, 65535),  # auto-generate
            rates=[100,100,100,100],
            expo=[0,0,0,0],
            dr_switch=0,
            active_rates=False,
            subtrim=[0,0,0,0],
            endpoints=[[1000,2000],[1000,2000],[1000,2000],[1000,2000]],
            reverse=[False, False, False, False],
            ail_to_rud_mix_enabled=False,
            ail_to_rud_mix_percent=30
        )

        # Write the model, then set the used bit for this slot in the header.
        self.store.write_model(slot, model)
        hdr["used_bitmap"] |= (1<<slot)
        self.store.write_header(hdr)
        self.refresh_model_list()

    def on_rename_model(self):
        # Rename only the model's firmware-stored name. Preserve the GUI-only
        # channel labels separately so they do not disappear during the write.
        slot = self.get_selected_slot()
        if slot is None: return
        try:
            m = self.store.read_model(slot)
            labels = self.channel_labels.get(slot)
            new = simpledialog.askstring("Rename", "New name:", initialvalue=m["name"])
            if not new: return
            m["name"] = new
            self.store.write_model(slot, m)
            self.channel_labels.set(slot, labels)
            self.refresh_model_list()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def on_delete_model(self):
        # Clear the selected slot's raw FRAM bytes and mark the slot as unused.
        slot = self.get_selected_slot()
        if slot is None: return
        if not messagebox.askyesno("Delete", f"Clear slot {slot}?"): return

        # Writing zeroes is enough to clear the model body.
        self.store.w.cmd_write(self.store.slot_addr(slot), b"\x00"*MODEL_SLOT_SIZE)

        hdr = self.store.ensure_header()
        hdr["used_bitmap"] &= ~(1<<slot)

        # If the active model was deleted, fall back to slot 0.
        if hdr["active_slot"] == slot:
            hdr["active_slot"] = 0
        self.store.write_header(hdr)
        self.channel_labels.clear(slot)
        self.refresh_model_list()

    def populate_editor(self, m, slot=None):
        # Copy a model dictionary into the visible editor widgets.
        self.name_var.set(m["name"])
        self.bind_var.set(str(m["bind_code"]))
        self.bind_changed = False
        self.dr_switch_var.set(str(m["dr_switch"]))
        self.dr_active_var.set(bool(m["active_rates"]))
        self.ail_rud_mix_enabled_var.set(bool(m.get("ail_to_rud_mix_enabled", False)))
        self.ail_rud_mix_percent_var.set(int(m.get("ail_to_rud_mix_percent", 30)))

        # Channel names can come from imported JSON, local GUI preferences, or
        # defaults if neither is available.
        names = m.get("channel_names")
        if not names and slot is not None:
            names = self.channel_labels.get(slot)
        if not names:
            names = CHANNEL_DEFAULT_NAMES

        # Tree rows are keyed by firmware channel ID: ch0, ch1, ch2, ch3. That
        # remains true even though the display order is TAER.
        for ch in range(4):
            rate = m["rates"][ch]
            expo = m["expo"][ch]
            sub  = m["subtrim"][ch]
            mn, mx = m["endpoints"][ch]
            rev = "Yes" if ("reverse" in m and m["reverse"][ch]) else "No"
            label = str(names[ch]).strip() if ch < len(names) else CHANNEL_DEFAULT_NAMES[ch]
            self.tree.item(f"ch{ch}", values=(label or CHANNEL_DEFAULT_NAMES[ch], rate, expo, sub, mn, mx, rev))

    def collect_editor(self):
        # Read the visible editor widgets and return a model dictionary. This is
        # the inverse of populate_editor.
        model = dict(
            name=self.name_var.get().strip()[:16],
            bind_code=int(self.bind_var.get() or "0"),
            dr_switch=int(self.dr_switch_var.get() or "0"),
            active_rates=bool(self.dr_active_var.get()),
            ail_to_rud_mix_enabled=bool(self.ail_rud_mix_enabled_var.get()),
            ail_to_rud_mix_percent=max(-100, min(100, int(self.ail_rud_mix_percent_var.get()))),
            rates=[0]*4, expo=[0]*4, subtrim=[0]*4, endpoints=[[0,0] for _ in range(4)],
            channel_names=[""]*4
        )

        # Read one row per firmware channel. Because row IDs are ch0..ch3, this
        # collects the correct channel values no matter how the table is sorted.
        for ch in range(4):
            v = self.tree.item(f"ch{ch}", "values")
            model["channel_names"][ch] = str(v[0]).strip() or CHANNEL_DEFAULT_NAMES[ch]
            model["rates"][ch]   = int(v[1])
            model["expo"][ch]    = int(v[2])
            model["subtrim"][ch] = int(v[3])
            model["endpoints"][ch]= [int(v[4]), int(v[5])]

        # collect reverse flags (column 6)
        model["reverse"] = [False]*4
        for ch in range(4):
            v = self.tree.item(f"ch{ch}", "values")
            rv = v[6] if len(v) > 6 else "No"
            model["reverse"][ch] = str(rv).lower() in ("yes","true","1")
        return model

    def on_load_slot(self):
        # Read the selected slot from FRAM and put its values into the editor.
        slot = self.get_selected_slot()
        if slot is None: return
        try:
            m = self.store.read_model(slot)
            self.current_slot = slot
            self.populate_editor(m, slot)
        except Exception as e:
            messagebox.showerror("Load failed", str(e))

    def on_save_slot(self):
        # Write whatever is currently visible in the editor to the selected slot.
        slot = self.get_selected_slot()
        if slot is None: return
        try:
            m = self.collect_editor()

            # Existing models already have a bind code. Unless the user clicked
            # "New Bind", keep the old bind code instead of changing it.
            try:
                existing = self.store.read_model(slot)
            except Exception:
                existing = None
            if not self.bind_changed and existing:
                m["bind_code"] = existing["bind_code"]

            # quick clamps and min<=max
            #
            # collect_editor converts text to numbers, but this final pass makes
            # sure imported/edited values are inside known-safe bounds before
            # they reach ModelsStore.write_model.
            validate_model_controls(m)

            # Firmware-compatible model bytes go to FRAM. GUI-only channel names
            # go to the local JSON preferences file.
            self.store.write_model(slot, m)
            self.channel_labels.set(slot, m.get("channel_names", CHANNEL_DEFAULT_NAMES))

            # Saving to a slot makes that slot "used" in the header.
            hdr = self.store.ensure_header()
            hdr["used_bitmap"] |= (1<<slot)
            self.store.write_header(hdr)
            self.refresh_model_list()
            self.bind_changed = False
            messagebox.showinfo("Saved", "Model updated")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def on_set_active(self):
        # The active slot is the model the transmitter uses when it boots/runs.
        slot = self.get_selected_slot()
        if slot is None: return
        try:
            hdr = self.store.ensure_header()
            hdr["active_slot"] = slot
            self.store.write_header(hdr)
            self.refresh_model_list()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def on_export_model(self):
        # Save the selected model to a JSON file on the computer. This is useful
        # for backups or copying a model to another machine.
        slot = self.get_selected_slot()
        if slot is None: return
        try:
            m = self.store.read_model(slot)

            # Include GUI-only channel names in the exported JSON even though
            # they are not stored in transmitter FRAM.
            m["channel_names"] = self.channel_labels.get(slot)
            path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
            if not path: return
            with open(path, "w") as f:
                json.dump(m, f, indent=2)
            messagebox.showinfo("Exported", f"Saved {path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def on_import_model(self):
        # Load a JSON model file and write it into the selected transmitter slot.
        slot = self.get_selected_slot()
        if slot is None: return
        path = filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if not path: return
        try:
            with open(path, "r") as f:
                m = json.load(f)

            # Pull out channel names before writing the firmware model. The
            # firmware write ignores channel_names, but the GUI stores them.
            names = m.get("channel_names", CHANNEL_DEFAULT_NAMES)
            self.store.write_model(slot, m)
            self.channel_labels.set(slot, names)

            # Mark the target slot as used after a successful import.
            hdr = self.store.ensure_header()
            hdr["used_bitmap"] |= (1<<slot)
            self.store.write_header(hdr)
            self.refresh_model_list()
            messagebox.showinfo("Imported", "Model written to transmitter memory")
        except Exception as e:
            messagebox.showerror("Import failed", str(e))

if __name__ == "__main__":
    # This block runs only when the file is launched directly:
    #   python3 fram_gui_models.py
    #
    # mainloop() hands control to Tkinter so it can listen for clicks, keyboard
    # input, window redraws, and other GUI events.
    app = App()
    app.mainloop()
