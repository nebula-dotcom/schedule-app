"""Membaca file Excel jadwal (.xlsx) menjadi payload jadwal (lihat schedule.py).

Format yang dikenali = file buatan aplikasi ini lewat Download Excel:
  - "Semua Sheet"   : Config + Administrator + Jadwal Global  (sumber data = Administrator)
  - "Administrator" : satu sheet saja
  - "Jadwal Global" : satu sheet saja

Yang dibaca hanya SEL ISIAN (tanggal, nama staff, shift, jam kerja), bukan rumus, jadi aman
walau file sudah dibuka dan disimpan ulang di Excel/WPS. Memakai zipfile + xml bawaan Python,
tanpa library tambahan, jadi tidak perlu mengubah requirements di buildozer.spec.

Tanggal mulai dicari berurutan (yang pertama ketemu dipakai):
  1. sheet Config (C4 tanggal, D4 bulan, F4 tahun)
  2. judul "Periode: Jumat, 20 November – Kamis, 3 Desember 2026" (sel A2)
  3. header hari/tanggal di atas tabel (tahun diperkirakan dari kecocokan nama hari)
"""
from __future__ import annotations

import base64
import binascii
import io
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta

from . import settings as cfg
from .schedule import Schedule, ScheduleError, clean_text

KNOWN = ("BAR", "FLOOR", "CASHIER", "KITCHEN")      # divisi yang didukung halaman web
MAX_FILE = 350 * 1024                                # file jadwal asli hanya ~30 KB
MAX_WARN = 12

_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_COL0 = 3                                            # kolom C = hari pertama
_COLS = range(_COL0, _COL0 + cfg.N_DAYS)             # C..P
_HOURS_COL_MIN = 17                                  # tabel SHIFT / JAM KERJA ada di kolom Q ke kanan
_WORDS = {name.casefold(): code for code, (name, *_rest) in cfg.SHIFTS.items()}   # 'pagi' -> 'P'
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "may": 5, "jun": 6, "jul": 7, "agu": 8,
           "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "des": 12, "dec": 12}
_PERIOD = re.compile(r"(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?\s*[–—-]\s*(?:[A-Za-z]+,\s*)?"
                     r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")


def _q(tag: str) -> str:
    return f"{{{_M}}}{tag}"


def _n(v) -> str:
    """Teks pembanding: rapi dan huruf kecil semua ('' kalau kosong)."""
    return "" if v is None else re.sub(r"\s+", " ", str(v)).strip().casefold()


def _int(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v) if float(v).is_integer() else None
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
        return int(v.strip())
    return None


def _month(v):
    n = _int(v) if not isinstance(v, str) or v.strip().isdigit() else None
    if n is not None:
        return n if 1 <= n <= 12 else None
    return _MONTHS.get(_n(v)[:3])


def _colnum(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _letters(col: int) -> str:
    s = ""
    while col:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return s


# --------------------------------------------------------------------------
# membaca isi .xlsx
# --------------------------------------------------------------------------
def _open(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ScheduleError("File ini bukan file Excel (.xlsx) yang valid.") from None
    infos = zf.infolist()
    if len(infos) > 400 or sum(i.file_size for i in infos) > 30 * 1024 * 1024:
        raise ScheduleError("Isi file terlalu besar atau tidak wajar untuk file jadwal.")
    if "xl/workbook.xml" not in zf.namelist():
        raise ScheduleError("File ini bukan file Excel (.xlsx) yang valid.")
    return zf


def _xml(zf: zipfile.ZipFile, name: str):
    try:
        return ET.fromstring(zf.read(name))
    except (KeyError, ET.ParseError):
        raise ScheduleError("File Excel rusak atau tidak lengkap.") from None


def _sheets(zf: zipfile.ZipFile) -> list:
    """[(nama sheet, path di dalam zip)] sesuai urutan di file."""
    rels = {r.get("Id"): r.get("Target") for r in _xml(zf, "xl/_rels/workbook.xml.rels")}
    out = []
    for s in _xml(zf, "xl/workbook.xml").iter(_q("sheet")):
        target = rels.get(s.get(f"{{{_R}}}id"))
        if target:
            out.append((s.get("name", ""), target.lstrip("/") if target.startswith("/") else "xl/" + target))
    return out


def _shared(zf: zipfile.ZipFile) -> list:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    out = []
    for si in _xml(zf, "xl/sharedStrings.xml").iter(_q("si")):
        parts = []
        for ch in si:
            if ch.tag == _q("t"):
                parts.append(ch.text or "")
            elif ch.tag == _q("r"):                    # teks bergaya campur; abaikan <rPh> (furigana)
                t = ch.find(_q("t"))
                parts.append((t.text or "") if t is not None else "")
        out.append("".join(parts))
    return out


def _cells(zf: zipfile.ZipFile, path: str, shared: list) -> dict:
    """{(baris, kolom): nilai}. Sel kosong, galat, dan boolean dilewati; teks dirapikan."""
    cells = {}
    for c in _xml(zf, path).iter(_q("c")):
        m = re.fullmatch(r"([A-Z]+)(\d+)", c.get("r", ""))
        if not m:
            continue
        kind, v = c.get("t"), c.find(_q("v"))
        if kind == "inlineStr":
            val = "".join(t.text or "" for t in c.iter(_q("t")))
        elif v is None or v.text is None:
            continue
        elif kind == "s":
            try:
                val = shared[int(v.text)]
            except (ValueError, IndexError):
                continue
        elif kind == "str":
            val = v.text
        elif kind in ("b", "e"):
            continue
        else:
            try:
                f = float(v.text)
            except ValueError:
                continue
            if not math.isfinite(f):
                continue
            val = int(f) if f.is_integer() else f
        if isinstance(val, str):
            val = val.strip()
        if val != "":
            cells[(int(m.group(2)), _colnum(m.group(1)))] = val
    return cells


# --------------------------------------------------------------------------
# letak tabel di sheet
# --------------------------------------------------------------------------
def _blocks(cells: dict) -> list:
    """Satu blok per divisi, dikenali dari baris header 'NO | NAMA' (judul divisi 2 baris di atasnya)."""
    heads = sorted(r for (r, c), v in cells.items()
                   if c == 2 and r >= 3 and _n(v) == "nama" and _n(cells.get((r, 1))) == "no")
    last = max((r for r, _ in cells), default=0)
    return [{"hr": hr, "title": cells.get((hr - 2, 1)), "title_row": hr - 2,
             "end": heads[i + 1] - 2 if i + 1 < len(heads) else last + 1}
            for i, hr in enumerate(heads)]


def _staff_rows(cells: dict, blk: dict) -> list:
    rows, r = [], blk["hr"] + 1
    while r < blk["end"]:
        a, b = cells.get((r, 1)), cells.get((r, 2))
        if _int(a) is None and not (a is None and isinstance(b, str)):
            break                                       # 'JUMLAH STAFF ...', baris kosong, atau judul berikutnya
        rows.append(r)
        r += 1
    return rows


def _hours(cells: dict, blk: dict) -> dict:
    """Jam kerja dari tabel 'SHIFT | JAM KERJA'. Kosong -> {} (jam yang ada di aplikasi dibiarkan)."""
    marker = None
    for (r, c), v in sorted(cells.items()):
        if blk["title_row"] <= r < blk["end"] and c >= _HOURS_COL_MIN and _n(v) == "jam kerja":
            marker = (r, c)
            break
    if not marker:
        return {}
    mr, jc = marker
    out = {}
    for r in range(mr + 1, mr + 1 + len(cfg.SHIFT_ORDER)):
        code = next((_WORDS[_n(cells[(r, c)])] for c in range(_HOURS_COL_MIN, jc)
                     if _n(cells.get((r, c))) in _WORDS), None)
        if code:
            text = clean_text(str(cells.get((r, jc), "")), f"Jam {cfg.SHIFTS[code][0]} (sel {_letters(jc)}{r})",
                              cfg.MAX_HOURS)
            out[code] = re.sub(r"\s*[–—]\s*", "–", text, count=1)     # '09.00 – 17.00' -> '09.00–17.00'
    return out


# --------------------------------------------------------------------------
# tanggal mulai
# --------------------------------------------------------------------------
def _make_date(y, m, d, where: str) -> date:
    try:
        out = date(y, m, d)
    except (TypeError, ValueError):
        raise ScheduleError(f"Tanggal di {where} tidak ada di kalender ({d}-{m}-{y}).") from None
    if not cfg.YEAR_MIN <= out.year <= cfg.YEAR_MAX:
        raise ScheduleError(f"Tahun harus antara {cfg.YEAR_MIN} dan {cfg.YEAR_MAX} (di {where}).")
    return out


def _from_config(cells: dict):
    d, m, y = _int(cells.get((4, 3))), _month(cells.get((4, 4))), _int(cells.get((4, 6)))
    if d is None or m is None or y is None:
        return None                                    # Config belum lengkap -> coba sumber berikutnya
    return _make_date(y, m, d, "sheet Config (sel C4–F4)")


def _from_title(text):
    m = _PERIOD.search(str(text or ""))
    if not m:
        return None
    d1, mo1, y1, d2, mo2, y2 = m.groups()
    m1, m2 = _month(mo1), _month(mo2)
    if m1 is None or m2 is None:
        return None
    year = int(y1) if y1 else int(y2) - (1 if m1 > m2 else 0)
    return _make_date(year, m1, int(d1), "judul Periode (sel A2)")


def _weekday(v):
    n = _n(v)
    for i, (short, long_) in enumerate(zip(cfg.DAYS_SHORT, cfg.DAYS_LONG)):
        if n in (short.casefold(), long_.casefold()):
            return i
    return None


def _from_header(cells: dict, blk: dict, warn: list) -> date:
    hr = blk["hr"]
    day = _int(cells.get((hr, _COL0)))
    labels = [cells.get((hr - 2, c)) for c in _COLS]
    month = next((_month(v) for v in labels if isinstance(v, str) and not v.isdigit() and _month(v)), None)
    wd = _weekday(cells.get((hr - 1, _COL0)))
    if day is None or month is None or day == 0:
        raise ScheduleError("Tanggal mulai tidak bisa dibaca dari file. Pastikan judul “Periode: …” atau "
                            "header tanggal di atas tabel masih utuh.")
    day = abs(day)
    years = []
    for y in range(cfg.YEAR_MIN, cfg.YEAR_MAX + 1):
        try:
            if wd is None or date(y, month, day).weekday() == wd:
                years.append(y)
        except ValueError:
            pass
    if not years:
        raise ScheduleError("Tanggal di header file tidak cocok dengan nama harinya. Periksa header tabel.")
    now = date.today().year
    year = min(years, key=lambda y: (abs(y - now), y))
    warn.append(f"File tidak mencantumkan tahun; dipakai tahun {year} (dicocokkan dari nama hari). "
                f"Kalau keliru, ubah di bagian Tahun.")
    return date(year, month, day)


def _check_header(cells: dict, blk: dict, start: date, warn: list) -> None:
    """Header file (hari/tanggal) harus sama dengan tanggal mulai; kalau beda cukup diberi peringatan."""
    hr = blk["hr"]
    wd = _weekday(cells.get((hr - 1, _COL0)))
    if wd is not None and wd != start.weekday():
        warn.append(f"Header file menulis hari “{cells.get((hr - 1, _COL0))}”, padahal "
                    f"{start.day} {cfg.MONTHS_LONG[start.month - 1]} {start.year} adalah "
                    f"{cfg.DAYS_LONG[start.weekday()]}.")
        return
    for k, c in enumerate(_COLS):
        n = _int(cells.get((hr, c)))
        if n is not None and abs(n) != (start + timedelta(days=k)).day:
            warn.append(f"Nomor tanggal di header file (kolom {_letters(c)}) tidak cocok dengan periode.")
            return


# --------------------------------------------------------------------------
# pintu masuk
# --------------------------------------------------------------------------
def parse_xlsx(data: bytes) -> dict:
    """Isi file Excel -> {'payload': {...}, 'info': {...}}. Galat -> ScheduleError (pesan Indonesia)."""
    if len(data) > MAX_FILE:
        raise ScheduleError(f"File terlalu besar (maksimal {MAX_FILE // 1024} KB).")
    zf = _open(data)
    sheets = _sheets(zf)
    shared = _shared(zf)
    by_name = {n.casefold(): (n, p) for n, p in sheets}

    # sheet sumber: Administrator dulu (di "Semua Sheet" Jadwal Global hanya rumus), lalu Jadwal Global
    order = [k for k in ("administrator", "jadwal global") if k in by_name]
    order += [n.casefold() for n, _ in sheets if n.casefold() not in ("administrator", "jadwal global", "config")]
    sheet = cells = blocks = None
    for key in order:
        sheet, path = by_name[key]
        cells = _cells(zf, path, shared)
        blocks = _blocks(cells)
        if blocks:
            break
    else:
        raise ScheduleError("Format file tidak dikenali. Pakai file hasil Download Excel dari aplikasi ini "
                            "(Semua Sheet, Administrator, atau Jadwal Global).")

    warn: list = []
    start = source = None
    if "config" in by_name:
        start = _from_config(_cells(zf, by_name["config"][1], shared))
        source = "sheet Config"
    if start is None:
        start, source = _from_title(cells.get((2, 1))), "judul Periode"
    if start is None:
        start, source = _from_header(cells, blocks[0], warn), "header tabel"
    _check_header(cells, blocks[0], start, warn)

    divisions, seen, skipped = [], set(), []
    for blk in blocks:
        title = clean_text(str(blk["title"] or ""), "Nama divisi", cfg.MAX_TITLE)
        key = re.sub(r"[^A-Z0-9]", "", title.upper())
        if key not in KNOWN:
            skipped.append(title or f"(baris {blk['title_row']})")
            continue
        if key in seen:
            warn.append(f"Divisi {title} muncul dua kali; yang kedua dilewati.")
            continue
        seen.add(key)
        staff = []
        for r in _staff_rows(cells, blk):
            raw = cells.get((r, 2))
            try:
                name = clean_text(str(raw) if raw is not None else "", "Nama staff", cfg.MAX_NAME)
            except ScheduleError:
                raise ScheduleError(f"Nama di sel B{r} terlalu panjang (maksimal {cfg.MAX_NAME} karakter).") from None
            if not name:
                warn.append(f"Baris {r} ({title}) punya nomor tapi tanpa nama; dilewati.")
                continue
            shifts = ""
            for c in _COLS:
                v = cells.get((r, c))
                code = _WORDS.get(_n(v)) if v is not None else cfg.EMPTY
                if code is None and _n(v) == cfg.EMPTY:
                    code = cfg.EMPTY
                if code is None:
                    warn.append(f"Sel {_letters(c)}{r} ({name}) berisi “{v}”, bukan Pagi/Siang/Malam/Libur; dikosongkan.")
                    code = cfg.EMPTY
                shifts += code
            staff.append({"name": name, "shifts": shifts})
        if not staff:
            warn.append(f"Divisi {title} tidak berisi staff; dilewati.")
            continue
        divisions.append({"key": key, "title": title.title(), "hours": _hours(cells, blk), "staff": staff})

    if skipped:
        warn.append("Divisi tidak dikenali dan dilewati: " + ", ".join(skipped) + ".")
    if not divisions:
        raise ScheduleError("Tidak ada divisi yang dikenali di file (BAR, FLOOR, CASHIER, KITCHEN).")

    payload = {"start": start.isoformat(), "divisions": divisions}
    Schedule.from_payload(payload)                      # satu pintu validasi yang sama dengan simpan/ekspor
    sched = Schedule(start, [])
    shown = warn[:MAX_WARN] + ([f"…dan {len(warn) - MAX_WARN} peringatan lainnya."] if len(warn) > MAX_WARN else [])
    return {"payload": payload,
            "info": {"sheet": sheet, "source": source, "period": sched.period_text(),
                     "warnings": shown,
                     "divisions": [{"key": d["key"], "title": d["title"], "staff": len(d["staff"]),
                                    "filled": sum(ch != cfg.EMPTY for s in d["staff"] for ch in s["shifts"]),
                                    "cells": len(d["staff"]) * cfg.N_DAYS} for d in divisions]}}


def parse_b64(data: str) -> dict:
    """Sama seperti parse_xlsx, isi file dikirim sebagai teks base64 (dari halaman web)."""
    if not isinstance(data, str) or not data:
        raise ScheduleError("Tidak ada file yang dikirim.")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise ScheduleError("File yang dikirim rusak. Coba pilih ulang filenya.") from None
    return parse_xlsx(raw)
