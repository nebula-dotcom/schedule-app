from __future__ import annotations

import io
import os
import struct
import zlib
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFont

from . import settings as cfg
from .layout import build_model
from .schedule import Schedule

# Skala gambar, margin, kompresi PNG, dan tinggi pita baris
SCALE = 8
PAD = 14
PNG_COMPRESS = 6
BAND_ROWS = 256

# Daftar nama font dan folder pencarian

_REGULAR = ["LiberationSans-Regular.ttf", "Arimo-Regular.ttf", "Arial.ttf", "arial.ttf",
            "DejaVuSans.ttf", "Roboto-Regular.ttf", "NotoSans-Regular.ttf",
            "DroidSans.ttf"]
_BOLD = ["LiberationSans-Bold.ttf", "Arimo-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf",
         "DejaVuSans-Bold.ttf", "Roboto-Bold.ttf", "NotoSans-Bold.ttf",
         "DroidSans-Bold.ttf"]
_ROOTS = [str(cfg.FONT_DIR), "/usr/share/fonts", "/usr/local/share/fonts",
          "/system/fonts", "/data/data/com.termux/files/usr/share/fonts",
          os.path.expanduser("~/.fonts"), os.path.expanduser("~/.local/share/fonts")]


# Cari berkas font di folder umum
@lru_cache(maxsize=None)
def _font_path(bold: bool):
    names = _BOLD if bold else _REGULAR
    for name in names:
        for root in _ROOTS:
            if not os.path.isdir(root):
                continue
            for dirpath, _dirs, files in os.walk(root):
                if name in files:
                    return os.path.join(dirpath, name)
    return None


# Muat font; pakai font bawaan Pillow bila tidak ketemu
@lru_cache(maxsize=None)
def _font(bold: bool, size: int):
    path = _font_path(bold)
    if path:
        return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


# Posisi kumulatif kolom atau baris
def _offsets(sizes: list) -> list:
    out = [0]
    for size in sizes:
        out.append(out[-1] + size)
    return out


# Gambar isi satu sel (warna latar dan teks)
def _draw_cell(cell: dict, w: int, h: int, scale: int) -> Image.Image:
    tile = Image.new("RGB", (w, h), cell["bg"])
    if cell["t"] != "":
        d = ImageDraw.Draw(tile)
        font = _font(bool(cell["b"]), max(1, round(cell["fs"] * scale)))
        if cell["al"] == "l":
            d.text((8 * scale, h / 2), cell["t"], font=font, fill=cell["fg"], anchor="lm")
        else:
            d.text((w / 2, h / 2), cell["t"], font=font, fill=cell["fg"], anchor="mm")
    return tile


# Gambar garis tepi satu sel
def _draw_borders(img: Image.Image, cell: dict, px: int, py: int, w: int, h: int, scale: int):
    line = cfg.LINE
    g = ImageDraw.Draw(img)
    rw = (2 if cell.get("fr") else 1) * scale
    bw = (2 if cell.get("fb") else 1) * scale
    g.rectangle([px + w - rw, py, px + w - 1, py + h - 1], fill=line)
    g.rectangle([px, py + h - bw, px + w - 1, py + h - 1], fill=line)
    if cell.get("fl"):
        g.rectangle([px, py, px + 2 * scale - 1, py + h - 1], fill=line)
    if cell.get("ft"):
        g.rectangle([px, py, px + w - 1, py + 2 * scale - 1], fill=line)


# Tanda tangan dan potongan (chunk) berkas PNG
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


# Kanvas satu pita baris
def _band_canvas(boxes: list, width: int, y0: int, y1: int, prev: Image.Image, scale: int) -> Image.Image:
    canvas = Image.new("RGB", (width, y1 - y0 + 1), "white")
    canvas.paste(prev, (0, 0))
    for cell, px, py, w, h in boxes:
        if py >= y1 or py + h <= y0:
            continue
        y = py - y0 + 1
        canvas.paste(_draw_cell(cell, w, h, scale), (px, y))
        if not cell.get("nb"):
            _draw_borders(canvas, cell, px, y, w, h, scale)
    return canvas


# Baris PNG berfilter Up
def _scanlines(canvas: Image.Image, width: int) -> bytes:
    rows = canvas.size[1] - 1
    up = ImageChops.subtract_modulo(canvas.crop((0, 1, width, rows + 1)), canvas.crop((0, 0, width, rows)))
    raw, size = up.tobytes(), width * 3
    return b"".join(b"\x02" + raw[i * size:(i + 1) * size] for i in range(rows))


# PNG jadwal per pita baris; kind adm atau gl
def render(sched: Schedule, kind: str, scale: int = 0) -> bytes:
    scale = scale or SCALE
    model = build_model(sched, kind)
    xs = _offsets(model["W"])
    ys = _offsets([model["H"][i] for i in range(model["n_rows"])])
    width = (xs[-1] + 2 * PAD) * scale
    height = (ys[-1] + 2 * PAD) * scale
    boxes = [(cell,
              (PAD + xs[cell["c"]]) * scale, (PAD + ys[cell["r"]]) * scale,
              (xs[cell["c"] + cell["cs"]] - xs[cell["c"]]) * scale,
              (ys[cell["r"] + cell["rs"]] - ys[cell["r"]]) * scale) for cell in model["cells"]]
    out = io.BytesIO()
    out.write(PNG_SIGNATURE)
    out.write(_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
    packer = zlib.compressobj(PNG_COMPRESS)
    prev = Image.new("RGB", (width, 1), (0, 0, 0))
    for y0 in range(0, height, BAND_ROWS):
        y1 = min(y0 + BAND_ROWS, height)
        canvas = _band_canvas(boxes, width, y0, y1, prev, scale)
        prev = canvas.crop((0, y1 - y0, width, y1 - y0 + 1))
        packed = packer.compress(_scanlines(canvas, width))
        if packed:
            out.write(_chunk(b"IDAT", packed))
    out.write(_chunk(b"IDAT", packer.flush()))
    out.write(_chunk(b"IEND", b""))
    return out.getvalue()
