"""Render model tabel menjadi PNG memakai Pillow (terjemahan dari png() di halaman web)."""
from __future__ import annotations

import io
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from . import settings as cfg
from .layout import build_model
from .schedule import Schedule

SCALE = 3          # 3x supaya tajam saat di-zoom / dikirim lewat WhatsApp
PAD = 14           # margin putih di sekeliling tabel (px logis)

# Urutan pencarian font. Font di folder fonts/ dipakai lebih dulu supaya
# hasilnya sama di semua perangkat (Termux biasanya tidak punya Arial).
_REGULAR = ["LiberationSans-Regular.ttf", "Arimo-Regular.ttf", "Arial.ttf", "arial.ttf",
            "DejaVuSans.ttf", "Roboto-Regular.ttf", "NotoSans-Regular.ttf",
            "DroidSans.ttf"]
_BOLD = ["LiberationSans-Bold.ttf", "Arimo-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf",
         "DejaVuSans-Bold.ttf", "Roboto-Bold.ttf", "NotoSans-Bold.ttf",
         "DroidSans-Bold.ttf"]
_ROOTS = [str(cfg.FONT_DIR), "/usr/share/fonts", "/usr/local/share/fonts",
          "/system/fonts", "/data/data/com.termux/files/usr/share/fonts",
          os.path.expanduser("~/.fonts"), os.path.expanduser("~/.local/share/fonts")]


@lru_cache(maxsize=None)
def _font_path(bold: bool):
    names = _BOLD if bold else _REGULAR
    for name in names:                       # nama paling disukai dicari di semua folder dulu
        for root in _ROOTS:
            if not os.path.isdir(root):
                continue
            for dirpath, _dirs, files in os.walk(root):
                if name in files:
                    return os.path.join(dirpath, name)
    return None


@lru_cache(maxsize=None)
def _font(bold: bool, size: int):
    path = _font_path(bold)
    if path:
        return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size)  # cadangan terakhir (Pillow >= 10.1)
    except TypeError:
        return ImageFont.load_default()


def render(sched: Schedule, kind: str, scale: int = SCALE) -> bytes:
    """kind = 'adm' atau 'gl'. Mengembalikan isi file PNG."""
    model = build_model(sched, kind)
    widths = model["W"]
    heights = [model["H"][i] for i in range(model["n_rows"])]
    xs, ys = [0], [0]
    for w in widths:
        xs.append(xs[-1] + w)
    for h in heights:
        ys.append(ys[-1] + h)

    img = Image.new("RGB", ((xs[-1] + 2 * PAD) * scale, (ys[-1] + 2 * PAD) * scale), "white")
    line = cfg.LINE

    for x in model["cells"]:
        px = (PAD + xs[x["c"]]) * scale
        py = (PAD + ys[x["r"]]) * scale
        w = (xs[x["c"] + x["cs"]] - xs[x["c"]]) * scale
        h = (ys[x["r"] + x["rs"]] - ys[x["r"]]) * scale

        # isi sel + teks digambar di "kertas kecil" supaya teks terpotong rapi di batas sel
        tile = Image.new("RGB", (w, h), x["bg"])
        if x["t"] != "":
            d = ImageDraw.Draw(tile)
            font = _font(bool(x["b"]), max(1, round(x["fs"] * scale)))
            if x["al"] == "l":
                d.text((8 * scale, h / 2), x["t"], font=font, fill=x["fg"], anchor="lm")
            else:
                d.text((w / 2, h / 2), x["t"], font=font, fill=x["fg"], anchor="mm")
        img.paste(tile, (px, py))

        if not x.get("nb"):
            g = ImageDraw.Draw(img)
            rw = (2 if x.get("fr") else 1) * scale
            bw = (2 if x.get("fb") else 1) * scale
            g.rectangle([px + w - rw, py, px + w - 1, py + h - 1], fill=line)
            g.rectangle([px, py + h - bw, px + w - 1, py + h - 1], fill=line)
            if x.get("fl"):
                g.rectangle([px, py, px + 2 * scale - 1, py + h - 1], fill=line)
            if x.get("ft"):
                g.rectangle([px, py, px + w - 1, py + 2 * scale - 1], fill=line)

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
