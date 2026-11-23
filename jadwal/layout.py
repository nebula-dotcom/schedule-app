from __future__ import annotations

from . import settings as cfg
from .schedule import Division, Schedule, fmt_hours, month_spans

# Gaya sel header biru tua
_NAVY_CELL = dict(bg=cfg.NAVY, fg="#fff", b=1, fs=10)


# Kisi sel tabel: daftar sel dan tinggi baris
class _Grid:
    def __init__(self):
        self.cells: list = []
        self.heights: dict = {}

    # Tambah satu sel
    def add(self, r, c, t, **o):
        cell = dict(r=r, c=c, rs=1, cs=1, t=str(t), bg="#ffffff", fg="#000000",
                    b=0, fs=10.5, al="c")
        cell.update(o)
        self.cells.append(cell)

    # Tandai garis tebal di sekeliling blok sel
    def frame(self, r0, c0, r1, c1):
        for x in self.cells:
            if x.get("nb") or x["r"] < r0 or x["c"] < c0 or x["r"] > r1 or x["c"] > c1:
                continue
            if x["r"] == r0:
                x["ft"] = 1
            if x["r"] + x["rs"] - 1 == r1:
                x["fb"] = 1
            if x["c"] == c0:
                x["fl"] = 1
            if x["c"] + x["cs"] - 1 == c1:
                x["fr"] = 1


# Model tabel Administrator atau Jadwal Global
def build_model(sched: Schedule, kind: str) -> dict:
    adm = kind == "adm"
    widths = [30, 92] + [46] * 14 + ([42, 42, 42, 56, 42] if adm else [12, 48, 48, 48, 48])
    grid = _Grid()
    _add_title_rows(grid, sched)
    r = 3
    for index, div in enumerate(sched.divisions):
        if index:
            grid.heights[r] = 14
            r += 1
        r = _add_division(grid, sched.days, div, r, adm)
    return {"W": widths, "H": grid.heights, "cells": grid.cells, "n_rows": r}


# Baris judul JADWAL KERJA dan Periode
def _add_title_rows(grid: _Grid, sched: Schedule):
    grid.heights[0] = 32
    grid.add(0, 0, "JADWAL KERJA", cs=21, bg=cfg.NAVY, fg="#fff", b=1, fs=15, al="l", nb=1)
    grid.heights[1] = 24
    grid.add(1, 0, sched.period_text(), cs=21, bg=cfg.PERIOD_BG, fg=cfg.NAVY, b=1, fs=11,
             al="l", nb=1)
    grid.heights[2] = 12


# Blok satu divisi; mengembalikan nomor baris berikutnya
def _add_division(grid: _Grid, days: list, div: Division, r: int, adm: bool) -> int:
    n = len(div.staff)
    rows = 3 + n if adm else max(3 + n, 5)
    grid.heights[r] = grid.heights[r + 1] = grid.heights[r + 2] = 20
    _add_division_header(grid, days, div, r)
    _add_staff_rows(grid, div, r, adm)
    for y in range(r + 3, r + rows):
        grid.heights[y] = 22
    grid.frame(r, 0, r + 2 + n, 15)
    if adm:
        return _add_admin_summary(grid, days, div, r)
    _add_shift_hours(grid, div, r)
    return r + rows


# Header divisi: nama divisi, bulan, hari, tanggal, NO, NAMA
def _add_division_header(grid: _Grid, days: list, div: Division, r: int):
    grid.add(r, 0, div.label, rs=2, cs=2, bg=cfg.TEAL, fg="#fff", b=1, fs=11)
    for m in month_spans(days):
        label = (cfg.MONTHS_SHORT if m["n"] < 2 else cfg.MONTHS_LONG)[m["m"]].upper()
        grid.add(r, 2 + m["i"], label, cs=m["n"], bg=cfg.SL2 if m["m"] % 2 else cfg.SL1,
                 fg="#fff", b=1, fs=8.5)
    for j, d in enumerate(days):
        o = dict(_NAVY_CELL, bg=cfg.RED if d.weekday() >= 5 else cfg.NAVY)
        grid.add(r + 1, 2 + j, cfg.DAYS_SHORT[d.weekday()], **o)
        grid.add(r + 2, 2 + j, d.day, **o)
    grid.add(r + 2, 0, "NO", **_NAVY_CELL)
    grid.add(r + 2, 1, "NAMA", **_NAVY_CELL)


# Baris staff: nomor, nama, shift 14 hari, rekap (Administrator)
def _add_staff_rows(grid: _Grid, div: Division, r: int, adm: bool):
    for i, p in enumerate(div.staff):
        y = r + 3 + i
        tot = div.totals(p)
        grid.add(y, 0, i + 1)
        grid.add(y, 1, p.name, al="l")
        for j, code in enumerate(p.shifts):
            if code == cfg.EMPTY:
                grid.add(y, 2 + j, "")
                continue
            name, bg, fg = cfg.SHIFTS[code]
            grid.add(y, 2 + j, name, bg=bg, fg=fg, b=0 if code == "L" else 1)
        if adm:
            grid.add(y, 16, tot["P"])
            grid.add(y, 17, tot["S"])
            grid.add(y, 18, tot["R"])
            grid.add(y, 19, tot["P"] + tot["S"] + tot["R"], bg=cfg.TOTAL_BG, b=1)
            grid.add(y, 20, tot["L"])


# Rekap Administrator dan tabel jam kerja
def _add_admin_summary(grid: _Grid, days: list, div: Division, r: int) -> int:
    n = len(div.staff)
    grid.add(r, 16, "REKAP SHIFT (2 MINGGU)", cs=5, bg=cfg.SL1, fg="#fff", b=1)
    for i, code in enumerate("PSR"):
        _, bg, fg = cfg.SHIFTS[code]
        grid.add(r + 1, 16 + i, cfg.SHIFTS[code][0], rs=2, bg=bg, fg=fg, b=1)
    grid.add(r + 1, 19, "Total Shift", rs=2, **_NAVY_CELL)
    _, lbg, lfg = cfg.SHIFTS["L"]
    grid.add(r + 1, 20, "Libur", rs=2, bg=lbg, fg=lfg, b=1)
    grid.frame(r, 16, r + 2 + n, 20)
    e = r + 3 + n
    grid.heights[e] = 22
    grid.add(e, 0, "JUMLAH STAFF PER SHIFT", cs=16, bg=cfg.SUM_BG, fg=cfg.SUM_FG, b=1, al="l")
    grid.add(e, 16, "SHIFT", cs=3, bg=cfg.SL1, fg="#fff", b=1)
    grid.add(e, 19, "JAM KERJA", cs=2, bg=cfg.SL1, fg="#fff", b=1)
    for i, code in enumerate(cfg.SHIFT_ORDER):
        y = e + 1 + i
        name, bg, fg = cfg.SHIFTS[code]
        grid.heights[y] = 22
        grid.add(y, 0, name, cs=2, bg=bg, fg=fg, b=1, al="l")
        for j in range(cfg.N_DAYS):
            z = div.count(code, j)
            bad = z == 0 and code != "L"
            grid.add(y, 2 + j, z, bg=cfg.BAD_BG if bad else bg, fg=cfg.BAD_FG if bad else fg, b=1)
        grid.add(y, 16, name, cs=3, bg=bg, fg=fg, b=1, al="l")
        grid.add(y, 19, fmt_hours(div.hours[code]), cs=2, bg=bg, fg=fg)
    grid.frame(e, 0, e + 4, 15)
    grid.frame(e, 16, e + 4, 20)
    for x in grid.cells:
        if x["c"] == 16:
            x["fl"] = 0
        if x["r"] == e:
            x["ft"] = 0
    return e + 5


# Tabel SHIFT dan JAM KERJA Jadwal Global
def _add_shift_hours(grid: _Grid, div: Division, r: int):
    grid.add(r, 17, "SHIFT " + div.label, cs=2, bg=cfg.SL1, fg="#fff", b=1, fs=10)
    grid.add(r, 19, "JAM KERJA", cs=2, bg=cfg.SL1, fg="#fff", b=1, fs=10)
    for i, code in enumerate(cfg.SHIFT_ORDER):
        name, bg, fg = cfg.SHIFTS[code]
        grid.add(r + 1 + i, 17, name, cs=2, bg=bg, fg=fg, b=1, al="l")
        grid.add(r + 1 + i, 19, fmt_hours(div.hours[code]), cs=2, bg=bg, fg=fg)
    grid.frame(r, 17, r + 4, 20)
