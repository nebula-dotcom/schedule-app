from __future__ import annotations

import io
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from . import settings as cfg
from .layout import build_model
from .schedule import Schedule

# Skala gambar, margin, dan tingkat kompresi PNG
SCALE = 3
PAD = 14
PNG_COMPRESS = 6

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


# Gambar jadwal menjadi PNG; kind "adm" atau "gl"
def render(sched: Schedule, kind: str, scale: int = SCALE) -> bytes:
    model = build_model(sched, kind)
    xs = _offsets(model["W"])
    ys = _offsets([model["H"][i] for i in range(model["n_rows"])])
    img = Image.new("RGB", ((xs[-1] + 2 * PAD) * scale, (ys[-1] + 2 * PAD) * scale), "white")
    for cell in model["cells"]:
        px = (PAD + xs[cell["c"]]) * scale
        py = (PAD + ys[cell["r"]]) * scale
        w = (xs[cell["c"] + cell["cs"]] - xs[cell["c"]]) * scale
        h = (ys[cell["r"] + cell["rs"]] - ys[cell["r"]]) * scale
        img.paste(_draw_cell(cell, w, h, scale), (px, py))
        if not cell.get("nb"):
            _draw_borders(img, cell, px, py, w, h, scale)
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=PNG_COMPRESS)
    return buf.getvalue()
