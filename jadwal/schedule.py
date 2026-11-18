"""Data jadwal: validasi payload dari halaman web + hitungan tanggal/rekap.

Payload (JSON) yang dikirim halaman web:
{
  "start": "2026-11-20",
  "divisions": [
    {"key": "BAR", "title": "Bar",
     "hours": {"P": "09.00–17.00", "S": "...", "R": "...", "L": "Tidak bertugas"},
     "staff": [{"name": "Sadewa", "shifts": "PPPLSPSSSSLRRR"}, ...]}
  ]
}
`shifts` = 14 karakter (P/S/R/L, atau "-" = kosong), satu per hari mulai dari tanggal `start`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import settings as cfg


class ScheduleError(ValueError):
    """Data jadwal tidak valid. Pesan sudah dalam Bahasa Indonesia."""


# --------------------------------------------------------------------------
# struktur data
# --------------------------------------------------------------------------
@dataclass
class Staff:
    name: str
    shifts: str                     # 14 karakter: P/S/R/L atau "-" (kosong)


@dataclass
class Division:
    key: str
    title: str
    hours: dict
    staff: list = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.title.upper()

    def count(self, code: str, day: int) -> int:
        """Jumlah staff yang bershift `code` pada hari ke-`day` (0..13). Sel kosong tidak dihitung."""
        return sum(1 for s in self.staff if s.shifts[day] == code)

    def totals(self, staff: Staff) -> dict:
        return {c: staff.shifts.count(c) for c in cfg.SHIFT_ORDER}


@dataclass
class Schedule:
    start: date
    divisions: list

    @property
    def days(self) -> list:
        return [self.start + timedelta(days=i) for i in range(cfg.N_DAYS)]

    @property
    def end(self) -> date:
        return self.start + timedelta(days=cfg.N_DAYS - 1)

    # ---------------- masuk/keluar ----------------
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

        divisions, seen = [], set()
        for d in raw:
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

            hours = {}
            raw_h = d.get("hours") if isinstance(d.get("hours"), dict) else {}
            for code in cfg.SHIFT_ORDER:
                raw = raw_h.get(code)               # kosong ("") dibiarkan kosong; hanya yang tidak dikirim memakai bawaan
                hours[code] = clean_text(cfg.DEFAULT_HOURS[code] if raw is None else raw,
                                         f"Jam {cfg.SHIFTS[code][0]}", cfg.MAX_HOURS)

            raw_staff = d.get("staff", [])
            if not isinstance(raw_staff, list):
                raise ScheduleError(f"Daftar staff divisi {title} tidak valid.")
            if len(raw_staff) > cfg.MAX_STAFF:
                raise ScheduleError(f"Divisi {title}: maksimal {cfg.MAX_STAFF} staff.")
            staff = []
            for i, s in enumerate(raw_staff, 1):
                if not isinstance(s, dict):
                    raise ScheduleError(f"Staff ke-{i} divisi {title} tidak valid.")
                name = clean_text(s.get("name"), "Nama staff", cfg.MAX_NAME)
                if not name:
                    raise ScheduleError(f"Staff ke-{i} divisi {title} belum diberi nama.")
                shifts = s.get("shifts")
                if isinstance(shifts, list):
                    shifts = "".join(str(x) for x in shifts)
                if (not isinstance(shifts, str) or len(shifts) != cfg.N_DAYS
                        or any(ch not in cfg.SHIFT_VALID for ch in shifts)):
                    raise ScheduleError(
                        f"Shift {name} ({title}) harus {cfg.N_DAYS} hari berisi P/S/R/L atau - (kosong).")
                staff.append(Staff(name, shifts))
            divisions.append(Division(key, title, hours, staff))
        return cls(start, divisions)

    def to_payload(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "divisions": [
                {"key": d.key, "title": d.title, "hours": dict(d.hours),
                 "staff": [{"name": s.name, "shifts": s.shifts} for s in d.staff]}
                for d in self.divisions
            ],
        }

    # ---------------- teks turunan ----------------
    def period_text(self) -> str:
        """Sama persis dengan rumus A2 di Excel dan ptxt() di halaman web."""
        s, e = self.start, self.end
        left = f"{cfg.DAYS_LONG[s.weekday()]}, {s.day} {cfg.MONTHS_LONG[s.month - 1]}"
        if s.year != e.year:
            left += f" {s.year}"
        right = (f"{cfg.DAYS_LONG[e.weekday()]}, {e.day} "
                 f"{cfg.MONTHS_LONG[e.month - 1]} {e.year}")
        return f"Periode: {left} – {right}  ({cfg.N_DAYS} hari)"

    def file_stem(self) -> str:
        """Nama dasar file, mis. 'jadwal_20nov-3des_2026'."""
        s, e = self.start, self.end
        a = f"{s.day}{cfg.MONTHS_SHORT[s.month - 1].lower()}"
        b = f"{e.day}{cfg.MONTHS_SHORT[e.month - 1].lower()}"
        if s.year == e.year:
            return f"jadwal_{a}-{b}_{e.year}"
        return f"jadwal_{a}_{s.year}-{b}_{e.year}"


# --------------------------------------------------------------------------
# fungsi bantu
# --------------------------------------------------------------------------
def clean_text(value, label: str, maxlen: int) -> str:
    """Teks bersih: tanpa karakter kontrol, spasi rapi, dibatasi panjangnya."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ScheduleError(f"{label} harus berupa teks.")
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > maxlen:
        raise ScheduleError(f"{label} terlalu panjang (maksimal {maxlen} karakter).")
    return value


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


def fmt_hours(text: str) -> str:
    """'09.00–17.00' -> '09.00 – 17.00' (spasi di sekitar tanda pisah)."""
    return re.sub(r"\s*–\s*", " – ", text, count=1)


def excel_serial(d: date) -> int:
    """Tanggal -> nomor seri Excel (1900 date system)."""
    return (d - date(1899, 12, 30)).days


def month_spans(days: list) -> list:
    """Kelompok hari berurutan yang bulannya sama: [{'m': 0-11, 'i': indeks awal, 'n': jumlah}]."""
    out = []
    for i, d in enumerate(days):
        m = d.month - 1
        if out and out[-1]["m"] == m:
            out[-1]["n"] += 1
        else:
            out.append({"m": m, "i": i, "n": 1})
    return out
