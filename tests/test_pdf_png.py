import io
import re
import struct
import unittest
import zlib
from unittest import mock

from PIL import Image, ImageChops

from jadwal import image, layout, pdf
from jadwal.schedule import Schedule
from tests.sample import payload

try:
    import pypdf
except ImportError:
    pypdf = None


# Jadwal contoh dan nama dengan karakter khusus
def jadwal(nama=None) -> Schedule:
    data = payload()
    if nama:
        data["divisions"][0]["staff"][0]["name"] = nama
    return Schedule.from_payload(data)


# Gambar penuh sekaligus sebagai pembanding PNG berpita
def gambar_penuh(sched: Schedule, kind: str, scale: int) -> Image.Image:
    model = layout.build_model(sched, kind)
    xs = image._offsets(model["W"])
    ys = image._offsets([model["H"][i] for i in range(model["n_rows"])])
    img = Image.new("RGB", ((xs[-1] + 2 * image.PAD) * scale, (ys[-1] + 2 * image.PAD) * scale), "white")
    for cell in model["cells"]:
        px = (image.PAD + xs[cell["c"]]) * scale
        py = (image.PAD + ys[cell["r"]]) * scale
        w = (xs[cell["c"] + cell["cs"]] - xs[cell["c"]]) * scale
        h = (ys[cell["r"] + cell["rs"]] - ys[cell["r"]]) * scale
        img.paste(image._draw_cell(cell, w, h, scale), (px, py))
        if not cell.get("nb"):
            image._draw_borders(img, cell, px, py, w, h, scale)
    return img


# Urai PNG menjadi potongan dan cek CRC tiap potongan
def potongan_png(data: bytes) -> list:
    assert data[:8] == image.PNG_SIGNATURE
    out, pos = [], 8
    while pos < len(data):
        size = struct.unpack(">I", data[pos:pos + 4])[0]
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + size]
        crc = struct.unpack(">I", data[pos + 8 + size:pos + 12 + size])[0]
        assert crc == zlib.crc32(tag + body) & 0xFFFFFFFF, tag
        out.append((tag, body))
        pos += 12 + size
    return out


# Tes PNG berpita: skala 8 dan piksel sama
class PngBerpita(unittest.TestCase):
    def test_skala_bawaan_8_dan_ukuran_sesuai_tabel(self):
        self.assertEqual(image.SCALE, 8)
        sched = jadwal()
        model = layout.build_model(sched, "gl")
        data = image.render(sched, "gl")
        w, h = struct.unpack(">II", potongan_png(data)[0][1][:8])
        self.assertEqual(w, (sum(model["W"]) + 2 * image.PAD) * 8)
        self.assertEqual(h, (sum(model["H"][i] for i in range(model["n_rows"])) + 2 * image.PAD) * 8)

    def test_potongan_sah_dan_semua_baris_berfilter_up(self):
        chunks = potongan_png(image.render(jadwal(), "adm", scale=2))
        self.assertEqual([t for t, _ in chunks][0], b"IHDR")
        self.assertEqual([t for t, _ in chunks][-1], b"IEND")
        w, h = struct.unpack(">II", chunks[0][1][:8])
        raw = zlib.decompress(b"".join(b for t, b in chunks if t == b"IDAT"))
        self.assertEqual(len(raw), h * (1 + w * 3))
        self.assertEqual({raw[i * (1 + w * 3)] for i in range(h)}, {2})

    def test_piksel_sama_dengan_gambar_penuh_termasuk_batas_pita(self):
        sched = jadwal()
        for kind, skala, tinggi_pita in (("adm", 2, 256), ("gl", 2, 256), ("adm", 2, 37), ("gl", 1, 1)):
            acuan = gambar_penuh(sched, kind, skala)
            with mock.patch.object(image, "BAND_ROWS", tinggi_pita):
                hasil = Image.open(io.BytesIO(image.render(sched, kind, scale=skala))).convert("RGB")
            self.assertEqual(hasil.size, acuan.size)
            self.assertIsNone(ImageChops.difference(hasil, acuan).getbbox(), (kind, skala, tinggi_pita))


# Urai PDF buatan sendiri: objek berdasarkan tabel xref
def baca_pdf(data: bytes) -> dict:
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    start = int(re.search(rb"startxref\n(\d+)\n%%EOF", data).group(1))
    head = re.match(rb"xref\n0 (\d+)\n", data[start:])
    count = int(head.group(1))
    table = data[start + head.end():start + head.end() + 20 * count]
    entries = re.findall(rb"(\d{10}) (\d{5}) ([nf]) \n", table)
    assert len(entries) == count and entries[0][2] == b"f"
    offsets = sorted(int(e[0]) for e in entries[1:]) + [start]
    objs = {}
    for number in range(1, count):
        awal = int(entries[number][0])
        potongan = data[awal:offsets[offsets.index(awal) + 1]]
        tanda = re.match(rb"%d 0 obj\n" % number, potongan)
        assert tanda, number
        assert potongan.endswith(b"\nendobj\n"), number
        objs[number] = potongan[tanda.end():-len(b"\nendobj\n")]
    return objs


# Isi aliran terkompresi satu objek
def isi_aliran(obj: bytes) -> bytes:
    panjang = int(re.search(rb"/Length (\d+)", obj).group(1))
    awal = obj.index(b"stream\n") + 7
    return zlib.decompress(obj[awal:awal + panjang])


# Tes PDF vektor: struktur sah, teks tersimpan, font tersemat
class PdfVektor(unittest.TestCase):
    def test_struktur_xref_dan_panjang_aliran_benar(self):
        objs = baca_pdf(pdf.render(jadwal(), "adm"))
        self.assertIn(b"/Type /Catalog", objs[1])
        for obj in objs.values():
            if b"stream\n" in obj[:400]:
                awal = obj.index(b"stream\n") + 7
                panjang = int(re.search(rb"/Length (\d+)", obj).group(1))
                self.assertEqual(obj[awal + panjang:awal + panjang + 10], b"\nendstream")

    def test_satu_halaman_ukuran_sesuai_tabel(self):
        sched = jadwal()
        model = layout.build_model(sched, "gl")
        objs = baca_pdf(pdf.render(sched, "gl"))
        lebar = (sum(model["W"]) + 2 * image.PAD) * pdf.UNIT
        tinggi = (sum(model["H"][i] for i in range(model["n_rows"])) + 2 * image.PAD) * pdf.UNIT
        box = [float(v) for v in re.search(rb"/MediaBox \[([^\]]+)\]", objs[3]).group(1).split()]
        self.assertEqual(box[:2], [0, 0])
        self.assertAlmostEqual(box[2], lebar, places=2)
        self.assertAlmostEqual(box[3], tinggi, places=2)
        self.assertIn(b"/Count 1", objs[2])

    def test_teks_ada_di_aliran_konten(self):
        isi = isi_aliran(baca_pdf(pdf.render(jadwal(), "adm"))[4])
        for teks in (b"(Sadewa) Tj", b"(JADWAL KERJA) Tj", b"(Pagi) Tj", b"(NAMA) Tj"):
            self.assertIn(teks, isi)
        self.assertIn(b"\x96", isi)

    def test_tanda_kurung_dan_garis_miring_di_escape(self):
        isi = isi_aliran(baca_pdf(pdf.render(jadwal("Ana (B)\\C"), "adm"))[4])
        self.assertIn(b"(Ana \\(B\\)\\\\C) Tj", isi)

    def test_karakter_di_luar_winansi_diganti_tanda_tanya(self):
        isi = isi_aliran(baca_pdf(pdf.render(jadwal("日本語"), "adm"))[4])
        self.assertIn(b"(???) Tj", isi)

    def test_font_liberation_tersemat_utuh(self):
        objs = baca_pdf(pdf.render(jadwal(), "adm"))
        for reguler, berkas in ((5, False), (8, True)):
            font = objs[reguler]
            self.assertIn(b"/Subtype /TrueType", font)
            lebar = re.search(rb"/Widths \[([^\]]+)\]", font).group(1).split()
            self.assertEqual(len(lebar), 224)
            with open(image._font_path(berkas), "rb") as fh:
                asli = fh.read()
            self.assertEqual(isi_aliran(objs[reguler + 2]), asli)
            self.assertIn(b"/Length1 %d" % len(asli), objs[reguler + 2])

    def test_cadangan_helvetica_bila_font_tidak_ada(self):
        with mock.patch.object(pdf, "_font_path", lambda bold: None):
            data = pdf.render(jadwal(), "gl")
        objs = baca_pdf(data)
        self.assertNotIn(b"FontFile2", data)
        self.assertIn(b"/BaseFont /Helvetica ", objs[5] + b" ")
        self.assertIn(b"(Sadewa) Tj", isi_aliran(objs[4]))

    def test_hasil_sama_setiap_kali_dibuat(self):
        sched = jadwal()
        self.assertEqual(pdf.render(sched, "adm"), pdf.render(sched, "adm"))

    def test_warna_heks_pendek_dan_panjang(self):
        self.assertEqual(pdf.rgb("#fff"), "1 1 1")
        self.assertEqual(pdf.rgb("#000000"), "0 0 0")
        self.assertEqual(pdf.rgb("#ff0000"), "1 0 0")

    @unittest.skipUnless(pypdf, "pypdf tidak terpasang")
    def test_pypdf_bisa_membaca_dan_mengambil_teks(self):
        reader = pypdf.PdfReader(io.BytesIO(pdf.render(jadwal(), "adm")))
        self.assertEqual(len(reader.pages), 1)
        teks = reader.pages[0].extract_text()
        self.assertIn("JADWAL KERJA", teks)
        self.assertIn("Sadewa", teks)


if __name__ == "__main__":
    unittest.main()
