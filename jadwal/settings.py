import os
from pathlib import Path

# Folder proyek dan data
BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
FONT_DIR = BASE_DIR / "fonts"
_PRIVATE = os.environ.get("ANDROID_PRIVATE")
DATA_DIR = Path(_PRIVATE) / "data" if _PRIVATE else BASE_DIR / "data"
STATE_FILE = DATA_DIR / "state.json"

# Port server
DEFAULT_PORT = 8888
BLOCKED_PORTS = {5000}
PORT_TRIES = 20
ANDROID_PORT = 8765

# Kode dan warna shift
SHIFT_ORDER = "PSRL"
EMPTY = "-"
SHIFT_VALID = SHIFT_ORDER + EMPTY
SHIFTS = {
    "P": ("Pagi", "#bdd7ee", "#1f4e79"),
    "S": ("Siang", "#ffe699", "#7f6000"),
    "R": ("Malam", "#f6b26b", "#7f3f00"),
    "L": ("Libur", "#ededed", "#7f7f7f"),
}

# Jam kerja bawaan
DEFAULT_HOURS = {
    "P": "",
    "S": "",
    "R": "",
    "L": "Tidak bertugas",
}

# Warna tabel Excel dan PNG
NAVY = "#1f2a44"
TEAL = "#1b7f79"
SL1 = "#44546a"
SL2 = "#5f7392"
RED = "#c00000"
LINE = "#7f7f7f"
WHITE = "#ffffff"
PERIOD_BG = "#dce6f1"
TOTAL_BG = "#f2f2f2"
SUM_BG = "#d9d9d9"
SUM_FG = "#404040"
BAD_BG = "#ffc7ce"
BAD_FG = "#9c0006"

# Nama hari dan bulan
DAYS_LONG = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
DAYS_SHORT = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
MONTHS_LONG = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
               "Agustus", "September", "Oktober", "November", "Desember"]
MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sept",
                "Okt", "Nov", "Des"]

# Jumlah hari per jadwal
N_DAYS = 14

# Batas isian
MAX_DIVISIONS = 12
MAX_STAFF = 60
MAX_NAME = 40
MAX_TITLE = 30
MAX_HOURS = 30
YEAR_MIN, YEAR_MAX = 2025, 2100
