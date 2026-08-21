#!/usr/bin/env python3
"""
Desktop transmitter configuration GUI.

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

import sys, os, binascii, json, time, struct, random
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

try:
    import serial
    import serial.tools.list_ports as list_ports
except Exception as e:
    raise SystemExit("This app requires 'pyserial' (or apt python3-serial on Debian).\n" + str(e))

# Basic application-wide settings.
APP_TITLE = "Walach Aviation Transmitter Configurator"
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
LOCAL_PREFS_PATH = os.path.join(os.path.expanduser("~"), ".walach_transmitter_configurator.json")

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

        # Return a plain dictionary because it is easy for the GUI and JSON
        # import/export code to work with.
        return dict(name=name, bind_code=bind_code, rates=rates, expo=expo,
                dr_switch=dr_switch, active_rates=active_rates,
                subtrim=subtrim, endpoints=endpoints,
                reverse=reverse,
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
        reserved = bytes([rev_mask]) + b"\x00"*5

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
            with open(self.path, "r") as f:
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
        self.store = ModelsStore(self.w)
        self.channel_labels = ChannelLabelStore()

        # Tracks which slot was last loaded into the editor. The selected slot
        # in the list is still the source of truth when saving.
        self.current_slot = None

        # Build the visual pieces of the app.
        self._install_app_icon()
        self._install_style()
        self._build_ui()

        # Populate the serial-port dropdown right away.
        self.refresh_ports()

    def _install_app_icon(self):
        # Build a tiny icon using Tk's PhotoImage. This avoids needing a PNG/ICO
        # file just to get a nice window icon during normal Python launches.
        try:
            icon = tk.PhotoImage(width=64, height=64)

            # PhotoImage.put fills rectangular regions. The result is a simple
            # transmitter-like mark with an antenna and control body.
            icon.put(COLORS["accent_dark"], to=(0, 0, 64, 64))
            icon.put(COLORS["accent"], to=(6, 6, 58, 58))
            icon.put("#ffffff", to=(14, 18, 50, 24))
            icon.put("#ffffff", to=(20, 28, 44, 34))
            icon.put("#ffffff", to=(26, 38, 38, 44))
            icon.put("#d9f3f6", to=(12, 46, 52, 50))
            icon.put(COLORS["accent_dark"], to=(28, 12, 36, 54))
            icon.put("#f6c64f", to=(27, 10, 37, 18))
            self._app_icon = icon
            self.iconphoto(True, icon)
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
        title_area = ttk.Frame(header, style="Header.TFrame")
        title_area.pack(side='left', fill='x', expand=True)
        ttk.Label(title_area, text=APP_TITLE, style="Header.TLabel").pack(anchor='w')
        ttk.Label(title_area, text="Model setup, channel tuning, and transmitter-memory sync", style="HeaderSub.TLabel").pack(anchor='w', pady=(2, 0))

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
            "Min us":  (700, 2300),
            "Max us":  (700, 2300),
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
            reverse=[False, False, False, False]
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
            for i in range(4):
                m["rates"][i]   = max(0, min(100, m["rates"][i]))
                m["expo"][i]    = max(-100, min(100, m["expo"][i]))
                m["subtrim"][i] = max(-500, min(500, m["subtrim"][i]))
                mn, mx = m["endpoints"][i]
                mn = max(700, min(2300, mn))
                mx = max(700, min(2300, mx))
                if mn > mx: mx = mn
                m["endpoints"][i] = [mn, mx]

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
