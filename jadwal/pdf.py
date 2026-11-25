from __future__ import annotations

import struct
import zlib

from PIL import ImageColor, ImageFont

from . import settings as cfg
from .image import PAD, _font_path
from .layout import build_model
from .schedule import Schedule

# Satuan tabel ke poin PDF
UNIT = 0.75

# Lebar huruf cadangan Helvetica
FALLBACK_WIDTH = 556


# Font satu gaya: data TTF dan lebar karakter
class Face:
    def __init__(self, bold: bool):
        path = _font_path(bold)
        self.name = "LiberationSans-Bold" if bold else "LiberationSans"
        self.data = None
        self.widths = [FALLBACK_WIDTH] * 224
        self.mid = 0.3465
        self.info = None
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            self.info = ttf_info(data)
            font = ImageFont.truetype(path, 1000)
            ascent, descent = font.getmetrics()
            self.widths = [self._advance(font, code) for code in range(32, 256)]
            self.mid = (ascent - descent) / 2000
            self.data = data
        except (OSError, ValueError, KeyError, struct.error):
            self.data = None
            self.info = None

    # Lebar maju satu karakter (1000 satuan per em)
    @staticmethod
    def _advance(font, code: int) -> int:
        try:
            ch = bytes([code]).decode("cp1252")
        except UnicodeDecodeError:
            return 0
        return round(font.getlength(ch))

    # Lebar teks dalam poin pada ukuran tertentu
    def width(self, raw: bytes, size: float) -> float:
        return sum(self.widths[b - 32] for b in raw if 32 <= b <= 255) * size / 1000


# Ukuran dasar font dari tabel head, hhea, dan OS/2
def ttf_info(data: bytes) -> dict:
    count = struct.unpack(">H", data[4:6])[0]
    tables = {}
    for i in range(count):
        tag = data[12 + 16 * i:16 + 16 * i].decode("latin1")
        tables[tag] = struct.unpack(">II", data[20 + 16 * i:28 + 16 * i])[0]
    head, hhea = tables["head"], tables["hhea"]
    upm = struct.unpack(">H", data[head + 18:head + 20])[0]
    box = struct.unpack(">hhhh", data[head + 36:head + 44])
    asc, desc = struct.unpack(">hh", data[hhea + 4:hhea + 8])
    k = 1000 / upm
    cap = 0.7 * upm
    if "OS/2" in tables:
        os2 = tables["OS/2"]
        if struct.unpack(">H", data[os2:os2 + 2])[0] >= 2:
            cap = struct.unpack(">h", data[os2 + 88:os2 + 90])[0] or cap
    return {"bbox": [round(v * k) for v in box], "ascent": round(asc * k), "descent": round(desc * k),
            "cap": round(cap * k)}


# Angka ringkas untuk aliran konten PDF
def num(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".") or "0"


# Warna ke tiga angka 0 sampai 1
def rgb(color: str) -> str:
    return " ".join(num(v / 255) for v in ImageColor.getrgb(color)[:3])


# Teks aman untuk tanda kurung PDF
def pdf_text(raw: bytes) -> bytes:
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


# Aliran konten halaman PDF
def page_content(model: dict, faces: tuple, page_h: float) -> bytes:
    xs = offsets(model["W"])
    ys = offsets([model["H"][i] for i in range(model["n_rows"])])
    ops: list = []
    state = {"fill": None}

    def fill(color: str):
        if state["fill"] != color:
            ops.append(f"{rgb(color)} rg")
            state["fill"] = color

    def rect(x: float, y: float, w: float, h: float, color: str):
        fill(color)
        ops.append(f"{num(x)} {num(y)} {num(w)} {num(h)} re f")

    for cell in model["cells"]:
        x = (PAD + xs[cell["c"]]) * UNIT
        w = (xs[cell["c"] + cell["cs"]] - xs[cell["c"]]) * UNIT
        h = (ys[cell["r"] + cell["rs"]] - ys[cell["r"]]) * UNIT
        y = page_h - (PAD + ys[cell["r"]]) * UNIT - h
        rect(x, y, w, h, cell["bg"])
        if cell["t"] != "":
            draw_text(ops, fill, faces[1 if cell["b"] else 0], cell, x, y, w, h)
        if not cell.get("nb"):
            draw_borders(rect, cell, x, y, w, h)
    return "\n".join(ops).encode("latin1")


# Posisi kumulatif kolom atau baris
def offsets(sizes: list) -> list:
    out = [0]
    for size in sizes:
        out.append(out[-1] + size)
    return out


# Teks sel: rata tengah atau kiri
def draw_text(ops: list, fill, face: Face, cell: dict, x: float, y: float, w: float, h: float):
    raw = cell["t"].encode("cp1252", "replace")
    size = cell["fs"] * UNIT
    tx = x + 8 * UNIT if cell["al"] == "l" else x + (w - face.width(raw, size)) / 2
    ty = y + h / 2 - face.mid * size
    fill(cell["fg"])
    font = "F2" if face.name.endswith("Bold") else "F1"
    ops.append(f"BT /{font} {num(size)} Tf 1 0 0 1 {num(tx)} {num(ty)} Tm ("
               + pdf_text(raw).decode("latin1") + ") Tj ET")


# Garis tepi sel
def draw_borders(rect, cell: dict, x: float, y: float, w: float, h: float):
    line = cfg.LINE
    rw = (2 if cell.get("fr") else 1) * UNIT
    bw = (2 if cell.get("fb") else 1) * UNIT
    rect(x + w - rw, y, rw, h, line)
    rect(x, y, w, bw, line)
    if cell.get("fl"):
        rect(x, y, 2 * UNIT, h, line)
    if cell.get("ft"):
        rect(x, y + h - 2 * UNIT, w, 2 * UNIT, line)


# Aliran terkompresi sebagai objek PDF
def stream(body: bytes, extra: str = "") -> bytes:
    packed = zlib.compress(body, 9)
    return f"<< /Length {len(packed)} {extra}/Filter /FlateDecode >>\nstream\n".encode() + packed + b"\nendstream"


# Objek font: tersemat atau Helvetica
def font_objects(face: Face, first_id: int) -> list:
    if face.data is None:
        base = "Helvetica-Bold" if face.name.endswith("Bold") else "Helvetica"
        return [f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} /Encoding /WinAnsiEncoding >>".encode()]
    info = face.info
    widths = " ".join(str(v) for v in face.widths)
    font = (f"<< /Type /Font /Subtype /TrueType /BaseFont /{face.name} /FirstChar 32 /LastChar 255 "
            f"/Widths [{widths}] /Encoding /WinAnsiEncoding /FontDescriptor {first_id + 1} 0 R >>").encode()
    descriptor = (f"<< /Type /FontDescriptor /FontName /{face.name} /Flags 32 "
                  f"/FontBBox [{' '.join(str(v) for v in info['bbox'])}] /ItalicAngle 0 "
                  f"/Ascent {info['ascent']} /Descent {info['descent']} /CapHeight {info['cap']} /StemV 80 "
                  f"/FontFile2 {first_id + 2} 0 R >>").encode()
    return [font, descriptor, stream(face.data, f"/Length1 {len(face.data)} ")]


# Susun objek menjadi berkas PDF
def assemble(objects: list) -> bytes:
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets_ = []
    for number, body in enumerate(objects, 1):
        offsets_.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets_:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {len(objects)} 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


# Buat PDF vektor jadwal; kind "adm" atau "gl"
def render(sched: Schedule, kind: str) -> bytes:
    model = build_model(sched, kind)
    xs = offsets(model["W"])
    ys = offsets([model["H"][i] for i in range(model["n_rows"])])
    page_w = (xs[-1] + 2 * PAD) * UNIT
    page_h = (ys[-1] + 2 * PAD) * UNIT
    faces = (Face(False), Face(True))
    content = page_content(model, faces, page_h)
    first = 5
    regular = font_objects(faces[0], first)
    bold = font_objects(faces[1], first + len(regular))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {num(page_w)} {num(page_h)}] "
         f"/Resources << /Font << /F1 {first} 0 R /F2 {first + len(regular)} 0 R >> >> /Contents 4 0 R >>").encode(),
        stream(content),
        *regular,
        *bold,
    ]
    objects.append(b"<< /Title (Jadwal Kerja) /Producer (Jadwal Kerja) >>")
    return assemble(objects)
