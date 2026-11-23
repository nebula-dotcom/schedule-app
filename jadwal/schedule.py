from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import settings as cfg


# Galat validasi jadwal
class ScheduleError(ValueError):
    pass


# Data staff: nama dan kode shift 14 hari
@dataclass
class Staff:
    name: str
    shifts: str


# Data divisi: kode, judul, jam kerja, staff
@dataclass
class Division:
    key: str
    title: str
    hours: dict
    staff: list = field(default_factory=list)

    # Judul divisi huruf besar
    @property
    def label(self) -> str:
        return self.title.upper()

    # Jumlah staff pada satu shift dan hari
    def count(self, code: str, day: int) -> int:
        return sum(1 for s in self.staff if s.shifts[day] == code)

    # Rekap shift satu staff
    def totals(self, staff: Staff) -> dict:
        return {c: staff.shifts.count(c) for c in cfg.SHIFT_ORDER}


# Data jadwal satu periode
@dataclass
class Schedule:
    start: date
    divisions: list

    # Daftar tanggal periode
    @property
    def days(self) -> list:
        return [self.start + timedelta(days=i) for i in range(cfg.N_DAYS)]

    # Tanggal terakhir periode
    @property
    def end(self) -> date:
        return self.start + timedelta(days=cfg.N_DAYS - 1)

    # Baca dan validasi data dari halaman web
    @classmethod
    def from_payload(cls, data) -> "Schedule":
        if not isinstance(data, dict):
            raise ScheduleError("Data jadwal tidak valid.")
        start = parse_date(data.get("start"))
        raw = data.get("divisions")
        if not isinstance(raw, list) or not raw:
            raise ScheduleError("Belum ada divisi pada data jadwal.")
        if len(raw) > cfg.MAX_DIVISIONS:
            raise ScheduleError(f"Maksimal {cfg.MAX_DIVISIONS} divisi.")
        seen = set()
        return cls(start, [_parse_division(d, seen) for d in raw])

    # Ubah ke data JSON
    def to_payload(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "divisions": [
                {"key": d.key, "title": d.title, "hours": dict(d.hours),
                 "staff": [{"name": s.name, "shifts": s.shifts} for s in d.staff]}
                for d in self.divisions
            ],
        }

    # Teks Periode di judul
    def period_text(self) -> str:
        s, e = self.start, self.end
        left = f"{cfg.DAYS_LONG[s.weekday()]}, {s.day} {cfg.MONTHS_LONG[s.month - 1]}"
        if s.year != e.year:
            left += f" {s.year}"
        right = (f"{cfg.DAYS_LONG[e.weekday()]}, {e.day} "
                 f"{cfg.MONTHS_LONG[e.month - 1]} {e.year}")
        return f"Periode: {left} – {right}  ({cfg.N_DAYS} hari)"

    # Nama dasar file ekspor
    def file_stem(self) -> str:
        s, e = self.start, self.end
        a = f"{s.day}{cfg.MONTHS_SHORT[s.month - 1].lower()}"
        b = f"{e.day}{cfg.MONTHS_SHORT[e.month - 1].lower()}"
        if s.year == e.year:
            return f"jadwal_{a}-{b}_{e.year}"
        return f"jadwal_{a}_{s.year}-{b}_{e.year}"


# Validasi data: divisi
def _parse_division(d, seen: set) -> Division:
    if not isinstance(d, dict):
        raise ScheduleError("Data divisi tidak valid.")
    key = str(d.get("key") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,20}", key):
        raise ScheduleError("Kode divisi tidak valid.")
    if key in seen:
        raise ScheduleError(f"Divisi {key} muncul dua kali.")
    seen.add(key)
    title = clean_text(d.get("title") or key.title(), "Nama divisi", cfg.MAX_TITLE)
    if not title:
        raise ScheduleError("Nama divisi tidak boleh kosong.")
    return Division(key, title, _parse_hours(d.get("hours")), _parse_staff(d.get("staff", []), title))


# Validasi data: jam kerja
def _parse_hours(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {code: clean_text(cfg.DEFAULT_HOURS[code] if raw.get(code) is None else raw[code],
                             f"Jam {cfg.SHIFTS[code][0]}", cfg.MAX_HOURS)
            for code in cfg.SHIFT_ORDER}


# Validasi data: daftar staff
def _parse_staff(raw, title: str) -> list:
    if not isinstance(raw, list):
        raise ScheduleError(f"Daftar staff divisi {title} tidak valid.")
    if len(raw) > cfg.MAX_STAFF:
        raise ScheduleError(f"Divisi {title}: maksimal {cfg.MAX_STAFF} staff.")
    return [_parse_one_staff(s, i, title) for i, s in enumerate(raw, 1)]


# Validasi data: satu staff
def _parse_one_staff(s, index: int, title: str) -> Staff:
    if not isinstance(s, dict):
        raise ScheduleError(f"Staff ke-{index} divisi {title} tidak valid.")
    name = clean_text(s.get("name"), "Nama staff", cfg.MAX_NAME)
    if not name:
        raise ScheduleError(f"Staff ke-{index} divisi {title} belum diberi nama.")
    shifts = s.get("shifts")
    if isinstance(shifts, list):
        shifts = "".join(str(x) for x in shifts)
    if (not isinstance(shifts, str) or len(shifts) != cfg.N_DAYS
            or any(ch not in cfg.SHIFT_VALID for ch in shifts)):
        raise ScheduleError(f"Shift {name} ({title}) harus {cfg.N_DAYS} hari berisi P/S/R/L atau - (kosong).")
    return Staff(name, shifts)


# Rapikan teks isian
def clean_text(value, label: str, maxlen: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ScheduleError(f"{label} harus berupa teks.")
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > maxlen:
        raise ScheduleError(f"{label} terlalu panjang (maksimal {maxlen} karakter).")
    return value


# Baca tanggal TTTT-BB-HH
def parse_date(value) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ScheduleError("Tanggal mulai harus berformat TTTT-BB-HH.")
    try:
        d = date.fromisoformat(value)
    except ValueError:
        raise ScheduleError("Tanggal mulai tidak ada di kalender.") from None
    if not cfg.YEAR_MIN <= d.year <= cfg.YEAR_MAX:
        raise ScheduleError(f"Tahun harus antara {cfg.YEAR_MIN} dan {cfg.YEAR_MAX}.")
    return d


# Format jam dengan spasi di sekitar tanda –
def fmt_hours(text: str) -> str:
    return re.sub(r"\s*–\s*", " – ", text, count=1)


# Nomor seri tanggal Excel
def excel_serial(d: date) -> int:
    return (d - date(1899, 12, 30)).days


# Rentang bulan di header tabel
def month_spans(days: list) -> list:
    out = []
    for i, d in enumerate(days):
        m = d.month - 1
        if out and out[-1]["m"] == m:
            out[-1]["n"] += 1
        else:
            out.append({"m": m, "i": i, "n": 1})
    return out
