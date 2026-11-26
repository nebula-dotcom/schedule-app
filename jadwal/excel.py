from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import timedelta

import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell

from . import settings as cfg
from .schedule import Division, Schedule, excel_serial, fmt_hours

# Rumus Excel: sel tanggal mulai dan larik nama hari/bulan
R4 = "Config!$R$4"
MONTH_ARR = "{" + ",".join(f'"{m}"' for m in cfg.MONTHS_LONG) + "}"
MONTH_ABBR_ARR = "{" + ",".join(f'"{m}"' for m in cfg.MONTHS_SHORT) + "}"
DAYL_ARR = "{" + ",".join(f'"{d}"' for d in cfg.DAYS_LONG) + "}"
DAYS_ARR = "{" + ",".join(f'"{d}"' for d in cfg.DAYS_SHORT) + "}"
SHEET_TITLES = {"adm": "Administrator", "gl": "Jadwal Global", "all": "Semua Sheet"}

# Rumus sheet Config: Hari, Check, tanggal
F_CFG_DAYNAME = f'=IF($R$4="","",INDEX({DAYL_ARR},WEEKDAY($R$4,2)))'
F_CFG_CHECK = (
    '=IF(OR($C$4="",$D$4="",$F$4=""),"Lengkapi tanggal, bulan, dan tahun",'
    'IF(OR(NOT(ISNUMBER($C$4)),NOT(ISNUMBER($F$4))),"Tanggal dan tahun harus berupa angka",'
    f'IF(ISNA(MATCH($D$4,{MONTH_ARR},0)),"Nama bulan tidak dikenali",'
    f'IF(DAY(DATE($F$4,MATCH($D$4,{MONTH_ARR},0),$C$4))<>$C$4,'
    '"Tanggal "&$C$4&" tidak ada di bulan "&$D$4&" "&$F$4,"Sesuai kalender"))))'
)
F_CFG_DATE = (
    '=IF(OR($C$4="",$D$4="",$F$4=""),"",IFERROR('
    f'IF(DAY(DATE($F$4,MATCH($D$4,{MONTH_ARR},0),$C$4))=$C$4,'
    f'DATE($F$4,MATCH($D$4,{MONTH_ARR},0),$C$4),""),""))'
)


# Rumus judul Periode
def f_period() -> str:
    e = f"({R4}+13)"
    return (
        f'=IF({R4}="","Periode: -","Periode: "&INDEX({DAYL_ARR},WEEKDAY({R4},2))&", "'
        f'&DAY({R4})&" "&INDEX({MONTH_ARR},MONTH({R4}))'
        f'&IF(YEAR({R4})<>YEAR({e})," "&YEAR({R4}),"")&" – "'
        f'&INDEX({DAYL_ARR},WEEKDAY({e},2))&", "&DAY({e})&" "'
        f'&INDEX({MONTH_ARR},MONTH({e}))&" "&YEAR({e})&"  (14 hari)")'
    )


# Rumus header bulan
def f_month(k: int) -> str:
    d = f"({R4}+{k})"
    first = f"MAX({R4},DATE(YEAR({d}),MONTH({d}),1))"
    last = f"MIN({R4}+13,DATE(YEAR({d}),MONTH({d})+1,0))"
    diff = f"({last}-{first})"
    return (
        f'=IF({R4}="","",IF({d}-{first}=MIN(INT({diff}/2),MAX({diff}-1,0)),'
        f'IF({diff}=0,UPPER(INDEX({MONTH_ABBR_ARR},MONTH({d}))),UPPER(INDEX({MONTH_ARR},MONTH({d})))),'
        f'IF(MOD(MONTH({d}),2)=1,1,2)))'
    )


# Rumus header nama hari
def f_dayname(k: int) -> str:
    return f'=IF({R4}="","",INDEX({DAYS_ARR},WEEKDAY({R4}+{k},2)))'


# Rumus header nomor tanggal
def f_daynum(k: int) -> str:
    d = f"({R4}+{k})"
    return f'=IF({R4}="","",IF(WEEKDAY({d},2)>5,-DAY({d}),DAY({d})))'


# Nilai awal header bulan
def month_cell_value(start, k: int):
    d = start + timedelta(days=k)
    first = max(start, d.replace(day=1))
    nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    last = min(start + timedelta(days=13), nxt - timedelta(days=1))
    diff = (last - first).days
    if (d - first).days == min(diff // 2, max(diff - 1, 0)):
        names = cfg.MONTHS_SHORT if diff == 0 else cfg.MONTHS_LONG
        return names[d.month - 1].upper()
    return 1 if d.month % 2 == 1 else 2


# Nilai awal nomor tanggal (negatif = akhir pekan)
def daynum_value(d) -> int:
    return -d.day if d.weekday() >= 5 else d.day


# Lebar kolom Excel dari lebar tampilan
def cw(raw: float) -> float:
    return raw - 5 / 7


# Lebar kolom A sampai P
def set_base_columns(ws):
    ws.set_column("A:A", cw(6))
    ws.set_column("B:B", cw(24))
    ws.set_column("C:P", cw(9.57))


# Pembungkus workbook dan cache format
class Book:

    def __init__(self, buf):
        self.wb = xlsxwriter.Workbook(buf, {"in_memory": True})
        self._fmt, self._dxf = {}, {}

    # Format sel
    def fmt(self, **p):
        key = tuple(sorted(p.items()))
        if key not in self._fmt:
            self._fmt[key] = self.wb.add_format(p)
        return self._fmt[key]

    # Format aturan warna
    def dxf(self, bg=None, fg=None, bold=False):
        key = (bg, fg, bold)
        if key not in self._dxf:
            p = {}
            if bg:
                p["bg_color"] = bg
            if fg:
                p["font_color"] = fg
            if bold:
                p["bold"] = True
            self._dxf[key] = self.wb.add_format(p)
        return self._dxf[key]


# Daftar sel satu sheet
class Page:

    def __init__(self, book: Book, ws):
        self.book, self.ws = book, ws
        self.items: list = []

    # Tambah satu sel
    def put(self, r, c, value="", *, f=None, rs=1, cs=1, sides="LRTB", bg=None,
            fg="#000000", bold=False, size=10, align="center", indent=0, nf=None):
        it = dict(r=r, c=c, rs=rs, cs=cs, value=value, f=f, bg=bg, fg=fg, bold=bold,
                  size=size, align=align, indent=indent, nf=nf, b={s: 1 for s in sides})
        self.items.append(it)
        return it

    # Garis tebal sekeliling blok
    def frame(self, r0, c0, r1, c1):
        for it in self.items:
            if it["r"] < r0 or it["c"] < c0 or it["r"] > r1 or it["c"] > c1:
                continue
            if it["r"] == r0:
                it["b"]["T"] = 2
            if it["r"] + it["rs"] - 1 == r1:
                it["b"]["B"] = 2
            if it["c"] == c0:
                it["b"]["L"] = 2
            if it["c"] + it["cs"] - 1 == c1:
                it["b"]["R"] = 2

    # Tulis semua sel ke sheet
    def flush(self):
        for it in self.items:
            p = dict(font_name="Arial", font_size=it["size"], bold=it["bold"],
                     font_color=it["fg"], align=it["align"], valign="vcenter")
            if it["bg"]:
                p["bg_color"] = it["bg"]
            if it["indent"]:
                p["indent"] = it["indent"]
            if it["nf"]:
                p["num_format"] = it["nf"]
            for side, name in (("L", "left"), ("R", "right"), ("T", "top"), ("B", "bottom")):
                if it["b"].get(side):
                    p[name] = it["b"][side]
                    p["border_color"] = cfg.LINE
            fmt = self.book.fmt(**p)
            r, c = it["r"], it["c"]
            if it["rs"] > 1 or it["cs"] > 1:
                self.ws.merge_range(r, c, r + it["rs"] - 1, c + it["cs"] - 1, "", fmt)
            v = it["value"]
            if it["f"]:
                self.ws.write_formula(r, c, it["f"], fmt, v)
            elif isinstance(v, str):
                self.ws.write_string(r, c, v, fmt)
            else:
                self.ws.write_number(r, c, v, fmt)


# Posisi blok satu divisi
@dataclass
class Block:
    div: Division
    r: int
    n: int
    e: int
    g: int


# Hitung posisi blok semua divisi
def plan(sched: Schedule):
    blocks, ra, rg = [], 3, 3
    for div in sched.divisions:
        n = max(len(div.staff), 1)
        e = ra + 3 + n
        blocks.append(Block(div, ra, n, e, rg))
        ra = e + 6
        rg += max(3 + n, 5) + 1
    last_a = blocks[-1].e + 4
    last_g = blocks[-1].g + max(3 + blocks[-1].n, 5) - 1
    return blocks, last_a, last_g


# Aturan warna shift
def add_shift_cf(book: Book, ws, r0, c0, r1, c1):
    for code in cfg.SHIFT_ORDER + cfg.ABSENT:
        name, bg, fg = cfg.SHIFTS[code]
        ws.conditional_format(r0, c0, r1, c1, {
            "type": "cell", "criteria": "==", "value": f'"{name}"',
            "format": book.dxf(bg, fg, bold=code != "L")})


# Aturan warna header bulan, hari, tanggal
def add_header_cf(book: Book, ws, r: int):
    c0, c1 = 2, 15
    nav = book.dxf(cfg.NAVY, cfg.WHITE, True)
    red = book.dxf(cfg.RED, cfg.WHITE, True)
    for v, bg in ((1, cfg.SL1), (2, cfg.SL2)):
        ws.conditional_format(r, c0, r, c1, {"type": "cell", "criteria": "==", "value": v,
                                             "format": book.dxf(bg, cfg.WHITE, True)})
    done = set()
    for i in range(12):
        for name in (cfg.MONTHS_LONG[i], cfg.MONTHS_SHORT[i]):
            if name.upper() in done:
                continue
            done.add(name.upper())
            ws.conditional_format(r, c0, r, c1, {
                "type": "cell", "criteria": "==", "value": f'"{name.upper()}"',
                "format": book.dxf(cfg.SL2 if i % 2 else cfg.SL1, cfg.WHITE, True)})
    for dname in ("Sab", "Min"):
        ws.conditional_format(r + 1, c0, r + 1, c1, {
            "type": "cell", "criteria": "==", "value": f'"{dname}"', "format": red})
    first = xl_rowcol_to_cell(r + 1, c0)
    ws.conditional_format(r + 1, c0, r + 1, c1, {
        "type": "formula", "criteria": f'=AND({first}<>"",{first}<>"Sab",{first}<>"Min")',
        "format": nav})
    ws.conditional_format(r + 2, c0, r + 2, c1, {"type": "cell", "criteria": "<", "value": 0,
                                                 "format": red})
    ws.conditional_format(r + 2, c0, r + 2, c1, {"type": "cell", "criteria": ">=", "value": 0,
                                                 "format": nav})


# Baris judul JADWAL KERJA dan Periode
def title_rows(page: Page, text, f_text, value_text):
    page.put(0, 0, text, cs=21, bg=cfg.NAVY, fg=cfg.WHITE, bold=True, size=16,
             align="left", indent=1, sides="", f=f_text[0])
    page.put(1, 0, value_text, f=f_text[1], cs=21, bg=cfg.PERIOD_BG, fg=cfg.NAVY, bold=True,
             size=11, align="left", indent=1, sides="")


# Header divisi: bulan, hari, tanggal, NO, NAMA
def header_rows(page: Page, sched: Schedule, r: int, label, f_label=None, link=None,
                formulas=True):
    days = sched.days

    def fx(off, ac, own):
        if not formulas:
            return None
        return link(off, ac) if link else own

    page.put(r, 0, label, f=f_label, rs=2, cs=2, bg=cfg.TEAL, fg=cfg.WHITE, bold=True, size=11)
    for k, d in enumerate(days):
        sides = "TB" + ("L" if k == 0 else "") + ("R" if k == cfg.N_DAYS - 1 else "")
        mv = month_cell_value(sched.start, k)
        page.put(r, 2 + k, mv, f=fx(0, 2 + k, f_month(k)),
                 sides=sides, bg=cfg.SL2 if d.month % 2 == 0 else cfg.SL1, fg=cfg.WHITE,
                 bold=True, size=8, nf=";;;@")
        wk = d.weekday() >= 5
        bg = cfg.RED if wk else cfg.NAVY
        page.put(r + 1, 2 + k, cfg.DAYS_SHORT[d.weekday()], f=fx(1, 2 + k, f_dayname(k)),
                 bg=bg, fg=cfg.WHITE, bold=True)
        page.put(r + 2, 2 + k, daynum_value(d), f=fx(2, 2 + k, f_daynum(k)),
                 bg=bg, fg=cfg.WHITE, bold=True, nf="0;0;0")
    for c, text in ((0, "NO"), (1, "NAMA")):
        page.put(r + 2, c, text, f=link(2, c, text=True) if formulas and link else None,
                 bg=cfg.NAVY, fg=cfg.WHITE, bold=True)


# Sel nomor, nama, dan shift satu staff
def staff_cells(page: Page, st, i: int, y: int, link=None):
    def fx(c):
        return link(c) if link else None

    page.put(y, 0, i + 1 if st else "", f=fx(0))
    page.put(y, 1, st.name if st else "", f=fx(1), align="left", indent=1)
    shifts = st.shifts if st else [None] * cfg.N_DAYS
    for k, code in enumerate(shifts):
        if code and code != cfg.EMPTY:
            name, bg, fg = cfg.SHIFTS[code]
            page.put(y, 2 + k, name, f=fx(2 + k), bg=bg, fg=fg, bold=code != "L")
        else:
            page.put(y, 2 + k, "", f=fx(2 + k))


# Sheet Config
def build_config(book: Book, sched: Schedule):
    ws = book.wb.add_worksheet("Config")
    pg = Page(book, ws)
    s = sched.start
    pg.put(0, 0, "KONFIGURASI JADWAL", cs=16, bg=cfg.NAVY, fg=cfg.WHITE, bold=True, size=16,
           align="left", indent=1, sides="")
    pg.put(2, 0, "TANGGAL MULAI", rs=2, cs=2, bg=cfg.TEAL, fg=cfg.WHITE, bold=True, size=11)
    for c, cs, text in ((2, 1, "Tanggal"), (3, 2, "Bulan"), (5, 1, "Tahun"), (6, 2, "Hari"),
                        (8, 8, "Check")):
        pg.put(2, c, text, cs=cs, bg=cfg.NAVY, fg=cfg.WHITE, bold=True)
    inp = dict(bg="#fff2cc", fg="#1f4e79", bold=True, size=11)
    pg.put(3, 2, s.day, nf="0", **inp)
    pg.put(3, 3, cfg.MONTHS_LONG[s.month - 1], cs=2, **inp)
    pg.put(3, 5, s.year, nf="0", **inp)
    pg.put(3, 6, cfg.DAYS_LONG[s.weekday()], f=F_CFG_DAYNAME, cs=2, bg="#ededed",
           fg=cfg.NAVY, bold=True, size=11)
    pg.put(3, 8, "Sesuai kalender", f=F_CFG_CHECK, cs=8, bg="#e2efda", fg="#375623", bold=True)
    pg.frame(2, 0, 3, 15)
    pg.flush()

    ws.write_formula(3, 17, F_CFG_DATE, book.fmt(num_format="dd/mm/yyyy"), excel_serial(s))
    ws.conditional_format(3, 8, 3, 15, {"type": "cell", "criteria": "==",
                                        "value": '"Sesuai kalender"',
                                        "format": book.dxf("#e2efda", "#375623", True)})
    ws.conditional_format(3, 8, 3, 15, {"type": "cell", "criteria": "!=",
                                        "value": '"Sesuai kalender"',
                                        "format": book.dxf(cfg.BAD_BG, cfg.BAD_FG, True)})
    ws.data_validation(3, 2, 3, 2, {
        "validate": "integer", "criteria": "between", "minimum": 1, "maximum": 31,
        "ignore_blank": False, "error_title": "Tanggal tidak valid",
        "error_message": "Isi angka 1 sampai 31."})
    ws.data_validation(3, 3, 3, 4, {
        "validate": "list", "source": list(cfg.MONTHS_LONG), "ignore_blank": False,
        "error_title": "Bulan tidak dikenal", "error_message": "Pilih bulan dari daftar."})
    ws.data_validation(3, 5, 3, 5, {
        "validate": "integer", "criteria": "between", "minimum": cfg.YEAR_MIN,
        "maximum": cfg.YEAR_MAX, "ignore_blank": False, "error_title": "Tahun tidak valid",
        "error_message": "Isi tahun 4 digit, misalnya 2026."})

    set_base_columns(ws)
    ws.set_column("R:R", cw(13), None, {"hidden": True})
    for r, h in ((0, 36), (1, 24), (2, 24), (3, 24)):
        ws.set_row(r, h)
    ws.hide_gridlines(2)
    ws.set_zoom(90)
    ws.set_tab_color(cfg.TEAL)
    ws.set_landscape()
    ws.set_paper(9)
    ws.fit_to_pages(1, 1)
    ws.set_margins(0.75, 0.75, 1.0, 1.0)
    ws.print_area(0, 0, 3, 15)
    return ws


# Sheet Administrator
def build_admin(book: Book, sched: Schedule, blocks, last_row, live=True):
    ws = book.wb.add_worksheet("Administrator")
    pg = Page(book, ws)

    def lf(formula):
        return formula if live else None

    title_rows(pg, "JADWAL KERJA", (None, lf(f_period())), sched.period_text())
    for b in blocks:
        r, n, e, div = b.r, b.n, b.e, b.div
        header_rows(pg, sched, r, div.label, formulas=live)
        hdr = r + 2
        pg.put(r, 16, "REKAP SHIFT (2 MINGGU)", cs=5, bg=cfg.SL1, fg=cfg.WHITE, bold=True)
        for i, code in enumerate("PSR"):
            name, bg, fg = cfg.SHIFTS[code]
            pg.put(r + 1, 16 + i, name, rs=2, bg=bg, fg=fg, bold=True)
        pg.put(r + 1, 19, "Total Shift", rs=2, bg=cfg.NAVY, fg=cfg.WHITE, bold=True)
        _, lbg, lfg = cfg.SHIFTS["L"]
        pg.put(r + 1, 20, "Libur", rs=2, bg=lbg, fg=lfg, bold=True)

        staff = div.staff or [None]
        for i, st in enumerate(staff):
            y, y1 = r + 3 + i, r + 4 + i
            staff_cells(pg, st, i, y)
            tot = div.totals(st) if st else {c: 0 for c in cfg.SHIFT_ORDER}
            for col, code in ((16, "P"), (17, "S"), (18, "R")):
                letter = "QRS"[col - 16]
                pg.put(y, col, tot[code], f=lf(f"=COUNTIF($C{y1}:$P{y1},{letter}${hdr})"))
            pg.put(y, 19, tot["P"] + tot["S"] + tot["R"], f=lf(f"=SUM(Q{y1}:S{y1})"),
                   bg=cfg.TOTAL_BG, bold=True)
            pg.put(y, 20, tot["L"], f=lf(f"=COUNTIF($C{y1}:$P{y1},U${hdr})"))

        pg.put(e, 0, "JUMLAH STAFF PER SHIFT", cs=16, bg=cfg.SUM_BG, fg=cfg.SUM_FG, bold=True,
               align="left", indent=1)
        pg.put(e, 16, "SHIFT", cs=3, bg=cfg.SL1, fg=cfg.WHITE, bold=True)
        pg.put(e, 19, "JAM KERJA", cs=2, bg=cfg.SL1, fg=cfg.WHITE, bold=True)
        first, last = r + 4, r + 3 + n
        for i, code in enumerate(cfg.SHIFT_ORDER):
            y = e + 1 + i
            name, bg, fg = cfg.SHIFTS[code]
            pg.put(y, 0, name, cs=2, bg=bg, fg=fg, bold=True, align="left", indent=1)
            for k in range(cfg.N_DAYS):
                z = div.count(code, k)
                bad = z == 0 and code != "L"
                col = xlsxwriter.utility.xl_col_to_name(2 + k)
                pg.put(y, 2 + k, z, f=lf(f"=COUNTIF({col}${first}:{col}${last},$A{y + 1})"),
                       bg=cfg.BAD_BG if bad else bg, fg=cfg.BAD_FG if bad else fg, bold=True)
            pg.put(y, 16, name, cs=3, bg=bg, fg=fg, bold=True, align="left", indent=1)
            pg.put(y, 19, fmt_hours(div.hours[code]), cs=2, bg=bg, fg=fg)

        pg.frame(r, 0, r + 2 + n, 15)
        pg.frame(r, 16, r + 2 + n, 20)
        pg.frame(e, 0, e + 4, 15)
        pg.frame(e, 16, e + 4, 20)

        add_header_cf(book, ws, r)
        add_shift_cf(book, ws, r + 3, 2, r + 2 + n, 15)
        if live:
            for i, code in enumerate("PSR"):
                y = e + 1 + i
                _, bg, fg = cfg.SHIFTS[code]
                ws.conditional_format(y, 2, y, 15, {"type": "cell", "criteria": "==", "value": 0,
                                                    "format": book.dxf(cfg.BAD_BG, cfg.BAD_FG, True)})
                ws.conditional_format(y, 2, y, 15, {"type": "cell", "criteria": "!=", "value": 0,
                                                    "format": book.dxf(bg, fg, True)})
            ws.data_validation(r + 3, 2, r + 2 + n, 15, {
                "validate": "list", "source": [cfg.SHIFTS[c][0] for c in cfg.SHIFT_ORDER + cfg.ABSENT],
                "ignore_blank": True, "error_title": "Shift tidak dikenal",
                "error_message": "Pilih salah satu: " + ", ".join(cfg.SHIFTS[c][0] for c in cfg.SHIFT_ORDER + cfg.ABSENT)})

        for y in range(r, r + 3):
            ws.set_row(y, 21.75)
        for y in range(r + 3, e + 6 if b is not blocks[-1] else e + 5):
            ws.set_row(y, 24)
    ws.set_row(0, 36)
    ws.set_row(1, 25.5)
    ws.set_row(2, 24)
    pg.flush()
    finish_sheet(ws, "Administrator", last_row, portrait=True, tab="#2e75b6")
    return pg


# Sheet Jadwal Global
def build_global(book: Book, sched: Schedule, blocks, last_row, linked=False):
    ws = book.wb.add_worksheet("Jadwal Global")
    pg = Page(book, ws)

    def ref(ar, ac):
        return f"Administrator!{xl_rowcol_to_cell(ar, ac)}"

    def if_link(ar, ac):
        return f'=IF({ref(ar, ac)}="","",{ref(ar, ac)})'

    def lf(formula):
        return formula if linked else None

    title_rows(pg, "JADWAL KERJA", (lf(if_link(0, 0)), lf(if_link(1, 0))), sched.period_text())

    for b in blocks:
        r, n, e, div, g = b.r, b.n, b.e, b.div, b.g

        def link(off, ac, text=False, _r=r):
            ar = _r + off
            return if_link(ar, ac) if text else f"={ref(ar, ac)}"

        header_rows(pg, sched, g, div.label, lf(if_link(r, 0)),
                    link=link if linked else None, formulas=linked)

        for i, st in enumerate(div.staff or [None]):
            ar = r + 3 + i
            staff_cells(pg, st, i, g + 3 + i,
                        link=(lambda c, _ar=ar: if_link(_ar, c)) if linked else None)

        pg.put(g, 17, f"SHIFT {div.label}",
               f=lf(f'=TRIM(Administrator!Q{e + 1}&" "&Administrator!A{r + 1})'),
               cs=2, bg=cfg.SL1, fg=cfg.WHITE, bold=True)
        pg.put(g, 19, "JAM KERJA", f=lf(if_link(e, 19)), cs=2, bg=cfg.SL1, fg=cfg.WHITE, bold=True)
        for i, code in enumerate(cfg.SHIFT_ORDER):
            name, bg, fg = cfg.SHIFTS[code]
            pg.put(g + 1 + i, 17, name, f=lf(if_link(e + 1 + i, 16)), cs=2, bg=bg, fg=fg,
                   bold=True, align="left", indent=1)
            pg.put(g + 1 + i, 19, fmt_hours(div.hours[code]), f=lf(if_link(e + 1 + i, 19)),
                   cs=2, bg=bg, fg=fg)

        pg.frame(g, 0, g + 2 + n, 15)
        pg.frame(g, 17, g + 4, 20)
        add_header_cf(book, ws, g)
        add_shift_cf(book, ws, g + 3, 2, g + 2 + n, 15)
        for y in range(g, g + 3):
            ws.set_row(y, 21.75)
        end = g + max(3 + n, 5)
        for y in range(g + 3, end + (0 if b is blocks[-1] else 1)):
            ws.set_row(y, 24)
        if b is blocks[-1]:
            ws.set_row(end, 12)
    ws.set_row(0, 36)
    ws.set_row(1, 25.5)
    ws.set_row(2, 24)
    pg.flush()
    finish_sheet(ws, "Jadwal Global", last_row, portrait=False, tab=cfg.NAVY, spacer=True)
    return pg


# Pengaturan kolom dan cetak sheet
def finish_sheet(ws, name, last_row, portrait, tab, spacer=False):
    set_base_columns(ws)
    if spacer:
        ws.set_column("Q:Q", cw(4.57))
        ws.set_column("R:S", cw(9))
    else:
        ws.set_column("Q:S", cw(9))
    ws.set_column("T:T", cw(12))
    ws.set_column("U:U", cw(9))
    ws.hide_gridlines(2)
    ws.set_zoom(90)
    ws.set_tab_color(tab)
    (ws.set_portrait if portrait else ws.set_landscape)()
    ws.set_paper(9)
    ws.fit_to_pages(1, 1)
    ws.set_margins(0.4, 0.4, 0.5, 0.5)
    ws.center_horizontally()
    ws.print_area(0, 0, last_row, 20)


# Buat file Excel: adm, gl, atau all
def build_workbook(sched: Schedule, sheet: str = "adm") -> bytes:
    if sheet not in SHEET_TITLES:
        raise ValueError(f"Sheet tidak dikenal: {sheet!r}")
    buf = io.BytesIO()
    book = Book(buf)
    blocks, last_a, last_g = plan(sched)
    if sheet == "all":
        build_config(book, sched)
        build_admin(book, sched, blocks, last_a, live=True)
        build_global(book, sched, blocks, last_g, linked=True)
    elif sheet == "gl":
        build_global(book, sched, blocks, last_g, linked=False)
    else:
        build_admin(book, sched, blocks, last_a, live=False)
    title = "Jadwal Kerja" if sheet == "all" else f"Jadwal Kerja - {SHEET_TITLES[sheet]}"
    book.wb.set_properties({"title": title,
                            "comments": "Dibuat otomatis oleh aplikasi Jadwal Kerja"})
    book.wb.close()
    return buf.getvalue()
