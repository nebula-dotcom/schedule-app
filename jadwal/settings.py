"""Konstanta bersama: shift, warna, nama hari/bulan, lokasi folder, batas input.

Semua modul (Excel, PNG, validasi) membaca angka dan warna dari sini,
jadi mengubah warna shift atau jam default cukup di satu tempat.
"""
import os
from pathlib import Path

# ---------- lokasi folder ----------
BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
FONT_DIR = BASE_DIR / "fonts"
_PRIVATE = os.environ.get("ANDROID_PRIVATE")     # folder pribadi aplikasi Android (tetap ada saat update)
DATA_DIR = Path(_PRIVATE) / "data" if _PRIVATE else BASE_DIR / "data"
STATE_FILE = DATA_DIR / "state.json"

# ---------- server ----------
DEFAULT_PORT = 8888
BLOCKED_PORTS = {5000}          # sudah dipakai aplikasi lain
PORT_TRIES = 20                 # kalau 8888 sibuk, coba 8889, 8890, ...
ANDROID_PORT = 8765             # port tetap di aplikasi Android; harus sama dengan p4a.port di buildozer.spec

# ---------- shift ----------
SHIFT_ORDER = "PSRL"            # urutan tampil: Pagi, Siang, Malam, Libur
EMPTY = "-"                     # sel shift kosong (belum diisi)
SHIFT_VALID = SHIFT_ORDER + EMPTY   # semua kode yang boleh ada di data
SHIFTS = {                      # kode: (nama, warna isi, warna teks)
    "P": ("Pagi", "#bdd7ee", "#1f4e79"),
    "S": ("Siang", "#ffe699", "#7f6000"),
    "R": ("Malam", "#f6b26b", "#7f3f00"),   # kode "R" sengaja dipertahankan agar data lama (state.json) tetap terbaca
    "L": ("Libur", "#ededed", "#7f7f7f"),
}
SHIFT_CODE = {v[0]: k for k, v in SHIFTS.items()}   # "Pagi" -> "P"
DEFAULT_HOURS = {                # jam kerja bawaan kosong; diisi lewat halaman web / sel JAM KERJA di Excel
    "P": "",
    "S": "",
    "R": "",
    "L": "Tidak bertugas",
}

# ---------- warna tabel ----------
NAVY = "#1f2a44"
TEAL = "#1b7f79"
SL1 = "#44546a"                 # pita bulan (ganjil) & judul tabel kecil
SL2 = "#5f7392"                 # pita bulan (genap)
RED = "#c00000"                 # Sabtu/Minggu
LINE = "#7f7f7f"                # garis tabel
WHITE = "#ffffff"
PERIOD_BG = "#dce6f1"
TOTAL_BG = "#f2f2f2"
SUM_BG = "#d9d9d9"
SUM_FG = "#404040"
BAD_BG = "#ffc7ce"              # jumlah staff 0 (kosong)
BAD_FG = "#9c0006"

# ---------- nama hari/bulan (Senin = indeks 0, sesuai date.weekday()) ----------
DAYS_LONG = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
DAYS_SHORT = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
MONTHS_LONG = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
               "Agustus", "September", "Oktober", "November", "Desember"]
MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sept",
                "Okt", "Nov", "Des"]

# ---------- bentuk tabel ----------
N_DAYS = 14                     # satu periode = 2 minggu

# ---------- batas input (menjaga file tetap wajar & aman) ----------
MAX_DIVISIONS = 12
MAX_STAFF = 60
MAX_NAME = 40
MAX_TITLE = 30
MAX_HOURS = 30
YEAR_MIN, YEAR_MAX = 2025, 2100
