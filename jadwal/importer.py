from __future__ import annotations

import base64
import binascii
import io
import math
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from datetime import date, timedelta

from . import settings as cfg
from .schedule import Schedule, ScheduleError, clean_text

# Konstanta pembaca Excel
KNOWN = ("BAR", "FLOOR", "CASHIER", "KITCHEN")
MAX_FILE = 350 * 1024
MAX_WARN = 12

_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_COL0 = 3
_COLS = range(_COL0, _COL0 + cfg.N_DAYS)
_HOURS_COL_MIN = 17
_WORDS = {name.casefold(): code for code, (name, *_rest) in cfg.SHIFTS.items()}
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "may": 5, "jun": 6, "jul": 7, "agu": 8,
           "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "des": 12, "dec": 12}
_PERIOD = re.compile(r"(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?\s*[–—-]\s*(?:[A-Za-z]+,\s*)?"
                     r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")


# Nama tag XML
def _q(tag: str) -> str:
    return f"{{{_M}}}{tag}"


# Teks pembanding huruf kecil
def _n(v) -> str:
    return "" if v is None else re.sub(r"\s+", " ", str(v)).strip().casefold()


# Baca angka bulat
def _int(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v) if float(v).is_integer() else None
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
        return int(v.strip())
    return None


# Baca nama atau nomor bulan
def _month(v):
    n = _int(v) if not isinstance(v, str) or v.strip().isdigit() else None
    if n is not None:
        return n if 1 <= n <= 12 else None
    return _MONTHS.get(_n(v)[:3])


# Huruf kolom ke nomor
def _colnum(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


# Nomor kolom ke huruf
def _letters(col: int) -> str:
    s = ""
    while col:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return s


# Galat tingkat rendah file rusak
_RUSAK = (zipfile.BadZipFile, zlib.error, NotImplementedError, RuntimeError, EOFError, LookupError, ValueError,
          OSError, OverflowError, ET.ParseError)
_BUKAN_XLSX = "File ini bukan file Excel (.xlsx) yang valid."


# Buka file zip xlsx
def _open(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
        ada = "xl/workbook.xml" in zf.namelist()
    except _RUSAK:
        raise ScheduleError(_BUKAN_XLSX) from None
    if len(infos) > 400 or sum(i.file_size for i in infos) > 30 * 1024 * 1024:
        raise ScheduleError("Isi file terlalu besar atau tidak wajar untuk file jadwal.")
    if not ada:
        raise ScheduleError(_BUKAN_XLSX)
    return zf


# Baca satu berkas XML
def _xml(zf: zipfile.ZipFile, name: str):
    try:
        return ET.fromstring(zf.read(name))
    except (KeyError, *_RUSAK):
        raise ScheduleError("File Excel rusak atau tidak lengkap.") from None


# Daftar sheet dan lokasinya
def _sheets(zf: zipfile.ZipFile) -> list:
    rels = {r.get("Id"): r.get("Target") for r in _xml(zf, "xl/_rels/workbook.xml.rels")}
    out = []
    for s in _xml(zf, "xl/workbook.xml").iter(_q("sheet")):
        target = rels.get(s.get(f"{{{_R}}}id"))
        if target:
            out.append((s.get("name", ""), target.lstrip("/") if target.startswith("/") else "xl/" + target))
    return out


# Daftar teks bersama
def _shared(zf: zipfile.ZipFile) -> list:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    out = []
    for si in _xml(zf, "xl/sharedStrings.xml").iter(_q("si")):
        parts = []
        for ch in si:
            if ch.tag == _q("t"):
                parts.append(ch.text or "")
            elif ch.tag == _q("r"):
                t = ch.find(_q("t"))
                parts.append((t.text or "") if t is not None else "")
        out.append("".join(parts))
    return out


# Baca semua sel satu sheet
def _cells(zf: zipfile.ZipFile, path: str, shared: list) -> dict:
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


# Cari blok divisi di sheet
def _blocks(cells: dict) -> list:
    heads = sorted(r for (r, c), v in cells.items()
                   if c == 2 and r >= 3 and _n(v) == "nama" and _n(cells.get((r, 1))) == "no")
    last = max((r for r, _ in cells), default=0)
    return [{"hr": hr, "title": cells.get((hr - 2, 1)), "title_row": hr - 2,
             "end": heads[i + 1] - 2 if i + 1 < len(heads) else last + 1}
            for i, hr in enumerate(heads)]


# Cari baris staff satu blok
def _staff_rows(cells: dict, blk: dict) -> list:
    rows, r = [], blk["hr"] + 1
    while r < blk["end"]:
        a, b = cells.get((r, 1)), cells.get((r, 2))
        if _int(a) is None and not (a is None and isinstance(b, str)):
            break
        rows.append(r)
        r += 1
    return rows


# Baca tabel SHIFT dan JAM KERJA
def _hours(cells: dict, blk: dict) -> dict:
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
            out[code] = re.sub(r"\s*[–—]\s*", "–", text, count=1)
    return out


# Susun tanggal dan cek rentang tahun
def _make_date(y, m, d, where: str) -> date:
    try:
        out = date(y, m, d)
    except (TypeError, ValueError):
        raise ScheduleError(f"Tanggal di {where} tidak ada di kalender ({d}-{m}-{y}).") from None
    if not cfg.YEAR_MIN <= out.year <= cfg.YEAR_MAX:
        raise ScheduleError(f"Tahun harus antara {cfg.YEAR_MIN} dan {cfg.YEAR_MAX} (di {where}).")
    return out


# Tanggal mulai dari sheet Config
def _from_config(cells: dict):
    d, m, y = _int(cells.get((4, 3))), _month(cells.get((4, 4))), _int(cells.get((4, 6)))
    if d is None or m is None or y is None:
        return None
    return _make_date(y, m, d, "sheet Config (sel C4–F4)")


# Tanggal mulai dari judul Periode
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


# Nama hari ke nomor hari
def _weekday(v):
    n = _n(v)
    for i, (short, long_) in enumerate(zip(cfg.DAYS_SHORT, cfg.DAYS_LONG)):
        if n in (short.casefold(), long_.casefold()):
            return i
    return None


# Tanggal mulai dari header tabel
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


# Cocokkan header dengan tanggal mulai
def _check_header(cells: dict, blk: dict, start: date, warn: list) -> None:
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


# Baca file Excel menjadi data jadwal
def parse_xlsx(data: bytes) -> dict:
    if len(data) > MAX_FILE:
        raise ScheduleError(f"File terlalu besar (maksimal {MAX_FILE // 1024} KB).")
    zf = _open(data)
    sheets = _sheets(zf)
    shared = _shared(zf)
    by_name = {n.casefold(): (n, p) for n, p in sheets}
    sheet, cells, blocks = _pick_sheet(zf, sheets, shared, by_name)

    warn: list = []
    start, source = _resolve_start(zf, by_name, shared, cells, blocks, warn)
    _check_header(cells, blocks[0], start, warn)

    divisions, seen, skipped = [], set(), []
    for blk in blocks:
        division = _parse_block(cells, blk, seen, skipped, warn)
        if division:
            divisions.append(division)
    if skipped:
        warn.append("Divisi tidak dikenali dan dilewati: " + ", ".join(skipped) + ".")
    if not divisions:
        raise ScheduleError("Tidak ada divisi yang dikenali di file (BAR, FLOOR, CASHIER, KITCHEN).")

    payload = {"start": start.isoformat(), "divisions": divisions}
    Schedule.from_payload(payload)
    return {"payload": payload, "info": _info(sheet, source, start, warn, divisions)}


# Pilih sheet sumber data
def _pick_sheet(zf, sheets: list, shared: list, by_name: dict):
    order = [k for k in ("administrator", "jadwal global") if k in by_name]
    order += [n.casefold() for n, _ in sheets if n.casefold() not in ("administrator", "jadwal global", "config")]
    for key in order:
        sheet, path = by_name[key]
        cells = _cells(zf, path, shared)
        blocks = _blocks(cells)
        if blocks:
            return sheet, cells, blocks
    raise ScheduleError("Format file tidak dikenali. Pakai file hasil Download Excel dari aplikasi ini "
                        "(Semua Sheet, Administrator, atau Jadwal Global).")


# Tentukan tanggal mulai
def _resolve_start(zf, by_name: dict, shared: list, cells: dict, blocks: list, warn: list):
    start = source = None
    if "config" in by_name:
        start = _from_config(_cells(zf, by_name["config"][1], shared))
        source = "sheet Config"
    if start is None:
        start, source = _from_title(cells.get((2, 1))), "judul Periode"
    if start is None:
        start, source = _from_header(cells, blocks[0], warn), "header tabel"
    return start, source


# Baca satu blok divisi
def _parse_block(cells: dict, blk: dict, seen: set, skipped: list, warn: list):
    try:
        title = clean_text(str(blk["title"] or ""), "Nama divisi", cfg.MAX_TITLE)
    except ScheduleError:
        title = ""
    key = re.sub(r"[^A-Z0-9]", "", title.upper())
    if key not in KNOWN:
        skipped.append(title or f"(baris {blk['title_row']})")
        return None
    if key in seen:
        warn.append(f"Divisi {title} muncul dua kali; yang kedua dilewati.")
        return None
    seen.add(key)
    staff = [row for row in (_parse_staff_row(cells, r, title, warn) for r in _staff_rows(cells, blk)) if row]
    if not staff:
        warn.append(f"Divisi {title} tidak berisi staff; dilewati.")
        return None
    return {"key": key, "title": title.title(), "hours": _hours(cells, blk), "staff": staff}


# Baca satu baris staff
def _parse_staff_row(cells: dict, r: int, title: str, warn: list):
    raw = cells.get((r, 2))
    try:
        name = clean_text(str(raw) if raw is not None else "", "Nama staff", cfg.MAX_NAME)
    except ScheduleError:
        raise ScheduleError(f"Nama di sel B{r} terlalu panjang (maksimal {cfg.MAX_NAME} karakter).") from None
    if not name:
        warn.append(f"Baris {r} ({title}) punya nomor tapi tanpa nama; dilewati.")
        return None
    return {"name": name, "shifts": _parse_shifts(cells, r, name, warn)}


# Baca 14 sel shift
def _parse_shifts(cells: dict, r: int, name: str, warn: list) -> str:
    shifts = ""
    for c in _COLS:
        v = cells.get((r, c))
        code = _WORDS.get(_n(v)) if v is not None else cfg.EMPTY
        if code is None and _n(v) == cfg.EMPTY:
            code = cfg.EMPTY
        if code is None:
            warn.append(f"Sel {_letters(c)}{r} ({name}) berisi “{v}”, bukan Pagi/Siang/Malam/Libur/Izin/Sakit; dikosongkan.")
            code = cfg.EMPTY
        shifts += code
    return shifts


# Ringkasan untuk pratinjau
def _info(sheet: str, source: str, start: date, warn: list, divisions: list) -> dict:
    shown = warn[:MAX_WARN] + ([f"…dan {len(warn) - MAX_WARN} peringatan lainnya."] if len(warn) > MAX_WARN else [])
    return {"sheet": sheet, "source": source, "period": Schedule(start, []).period_text(),
            "warnings": shown,
            "divisions": [{"key": d["key"], "title": d["title"], "staff": len(d["staff"]),
                           "filled": sum(ch != cfg.EMPTY for s in d["staff"] for ch in s["shifts"]),
                           "cells": len(d["staff"]) * cfg.N_DAYS} for d in divisions]}


# Baca file Excel dari teks base64
def parse_b64(data: str) -> dict:
    if not isinstance(data, str) or not data:
        raise ScheduleError("Tidak ada file yang dikirim.")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise ScheduleError("File yang dikirim rusak. Coba pilih ulang filenya.") from None
    return parse_xlsx(raw)
