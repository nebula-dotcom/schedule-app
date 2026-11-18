"""Model tabel (kotak-kotak berwarna) untuk PNG.

Ini terjemahan 1:1 dari fungsi model() di halaman web (index.html), supaya
PNG buatan Python sama persis dengan pratinjau yang terlihat di layar.
Setiap sel: baris/kolom, rentang (rs/cs), teks, warna, tebal, ukuran huruf,
rata teks, dan penanda bingkai tebal (ft/fb/fl/fr).
"""
from __future__ import annotations

from . import settings as cfg
from .schedule import Schedule, fmt_hours, month_spans


def build_model(sched: Schedule, kind: str) -> dict:
    """kind = 'adm' (Administrator, ada rekap) atau 'gl' (Jadwal Global)."""
    adm = kind == "adm"
    days = sched.days
    cells: list = []
    H: dict = {}
    W = [30, 92] + [46] * 14 + ([42, 42, 42, 56, 42] if adm else [12, 48, 48, 48, 48])

    def add(r, c, t, **o):
        cell = dict(r=r, c=c, rs=1, cs=1, t=str(t), bg="#ffffff", fg="#000000",
                    b=0, fs=10.5, al="c")
        cell.update(o)
        cells.append(cell)

    def frame(r0, c0, r1, c1):
        for x in cells:
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

    H[0] = 32
    add(0, 0, "JADWAL KERJA", cs=21, bg=cfg.NAVY, fg="#fff", b=1, fs=15, al="l", nb=1)
    H[1] = 24
    add(1, 0, sched.period_text(), cs=21, bg=cfg.PERIOD_BG, fg=cfg.NAVY, b=1, fs=11,
        al="l", nb=1)
    H[2] = 12
    r = 3

    for bi, div in enumerate(sched.divisions):
        if bi:
            H[r] = 14
            r += 1
        n = len(div.staff)
        rows = 3 + n if adm else max(3 + n, 5)
        title = div.label
        nv = dict(bg=cfg.NAVY, fg="#fff", b=1, fs=10)
        H[r] = H[r + 1] = H[r + 2] = 20
        add(r, 0, title, rs=2, cs=2, bg=cfg.TEAL, fg="#fff", b=1, fs=11)
        for m in month_spans(days):
            # bulan yang hanya 1 hari (1 sel) memakai singkatan (Jan, Feb, ..., Sept, ...)
            label = (cfg.MONTHS_SHORT if m["n"] < 2 else cfg.MONTHS_LONG)[m["m"]].upper()
            add(r, 2 + m["i"], label, cs=m["n"], bg=cfg.SL2 if m["m"] % 2 else cfg.SL1,
                fg="#fff", b=1, fs=8.5)
        for j, d in enumerate(days):
            o = dict(nv, bg=cfg.RED if d.weekday() >= 5 else cfg.NAVY)
            add(r + 1, 2 + j, cfg.DAYS_SHORT[d.weekday()], **o)
            add(r + 2, 2 + j, d.day, **o)
        add(r + 2, 0, "NO", **nv)
        add(r + 2, 1, "NAMA", **nv)

        for i, p in enumerate(div.staff):
            y = r + 3 + i
            tot = div.totals(p)
            add(y, 0, i + 1)
            add(y, 1, p.name, al="l")
            for j, code in enumerate(p.shifts):
                if code == cfg.EMPTY:               # belum diisi: sel putih kosong
                    add(y, 2 + j, "")
                    continue
                name, bg, fg = cfg.SHIFTS[code]
                add(y, 2 + j, name, bg=bg, fg=fg, b=0 if code == "L" else 1)
            if adm:
                add(y, 16, tot["P"])
                add(y, 17, tot["S"])
                add(y, 18, tot["R"])
                add(y, 19, tot["P"] + tot["S"] + tot["R"], bg=cfg.TOTAL_BG, b=1)
                add(y, 20, tot["L"])
        for y in range(r + 3, r + rows):
            H[y] = 22
        frame(r, 0, r + 2 + n, 15)

        if adm:
            add(r, 16, "REKAP SHIFT (2 MINGGU)", cs=5, bg=cfg.SL1, fg="#fff", b=1)
            for i, code in enumerate("PSR"):
                _, bg, fg = cfg.SHIFTS[code]
                add(r + 1, 16 + i, cfg.SHIFTS[code][0], rs=2, bg=bg, fg=fg, b=1)
            add(r + 1, 19, "Total Shift", rs=2, **nv)
            _, lbg, lfg = cfg.SHIFTS["L"]
            add(r + 1, 20, "Libur", rs=2, bg=lbg, fg=lfg, b=1)
            frame(r, 16, r + 2 + n, 20)
            e = r + 3 + n
            H[e] = 22
            add(e, 0, "JUMLAH STAFF PER SHIFT", cs=16, bg=cfg.SUM_BG, fg=cfg.SUM_FG,
                b=1, al="l")
            add(e, 16, "SHIFT", cs=3, bg=cfg.SL1, fg="#fff", b=1)
            add(e, 19, "JAM KERJA", cs=2, bg=cfg.SL1, fg="#fff", b=1)
            for i, code in enumerate(cfg.SHIFT_ORDER):
                y = e + 1 + i
                name, bg, fg = cfg.SHIFTS[code]
                H[y] = 22
                add(y, 0, name, cs=2, bg=bg, fg=fg, b=1, al="l")
                for j in range(cfg.N_DAYS):
                    z = div.count(code, j)
                    bad = z == 0 and code != "L"
                    add(y, 2 + j, z, bg=cfg.BAD_BG if bad else bg,
                        fg=cfg.BAD_FG if bad else fg, b=1)
                add(y, 16, name, cs=3, bg=bg, fg=fg, b=1, al="l")
                add(y, 19, fmt_hours(div.hours[code]), cs=2, bg=bg, fg=fg)
            frame(e, 0, e + 4, 15)
            frame(e, 16, e + 4, 20)
            for x in cells:                 # hindari garis tebal ganda
                if x["c"] == 16:
                    x["fl"] = 0
                if x["r"] == e:
                    x["ft"] = 0
            r = e + 5
        else:
            add(r, 17, "SHIFT " + title, cs=2, bg=cfg.SL1, fg="#fff", b=1, fs=10)
            add(r, 19, "JAM KERJA", cs=2, bg=cfg.SL1, fg="#fff", b=1, fs=10)
            for i, code in enumerate(cfg.SHIFT_ORDER):
                name, bg, fg = cfg.SHIFTS[code]
                add(r + 1 + i, 17, name, cs=2, bg=bg, fg=fg, b=1, al="l")
                add(r + 1 + i, 19, fmt_hours(div.hours[code]), cs=2, bg=bg, fg=fg)
            frame(r, 17, r + 4, 20)
            r += rows

    return {"W": W, "H": H, "cells": cells, "n_rows": r}
