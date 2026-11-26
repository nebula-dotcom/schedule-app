import base64
import http.client
import io
import json
import re
import tempfile
import threading
import unittest
import zipfile
from datetime import date
from pathlib import Path

from jadwal import excel, importer
from jadwal import settings as cfg
from jadwal.schedule import Schedule, ScheduleError
from tests.sample import payload, payload_kosong

try:
    import openpyxl
except ImportError:
    openpyxl = None

# Folder proyek
ROOT = Path(__file__).resolve().parent.parent


# Buat file Excel uji dari aplikasi
def xlsx(sheet, p=None) -> bytes:
    return excel.build_workbook(Schedule.from_payload(p or payload()), sheet)


# Bentuk data setelah validasi
def utuh(p):
    return Schedule.from_payload(p).to_payload()


# Ubah file Excel uji lewat openpyxl
def ubah(data: bytes, fungsi) -> bytes:
    wb = openpyxl.load_workbook(io.BytesIO(data))
    fungsi(wb)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# Buat file xlsx tulisan tangan
def xlsx_mini(sheets: dict) -> bytes:
    def sel(ref, v):
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        v = str(v).replace("&", "&amp;").replace("<", "&lt;")
        return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'

    def baris(cells):
        rows = {}
        for ref, v in cells.items():
            rows.setdefault(int(re.sub(r"\D", "", ref)), []).append((ref, v))
        return "".join(f'<row r="{r}">' + "".join(sel(a, b) for a, b in sorted(rows[r], key=lambda x: (len(x[0]), x[0])))
                       + "</row>" for r in sorted(rows))

    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rid = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} {rid}><sheets>' + "".join(
            f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(sheets, 1)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
                       f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
                   + "</Relationships>")
        for i, cells in enumerate(sheets.values(), 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", f"<worksheet {ns}><sheetData>{baris(cells)}</sheetData></worksheet>")
    return buf.getvalue()


# Tes data ke Excel lalu impor kembali
class BolakBalik(unittest.TestCase):

    def cek(self, p, jenis):
        hasil = importer.parse_xlsx(xlsx(jenis, p))
        self.assertEqual(hasil["payload"], utuh(p), jenis)

    def test_tiga_jenis_file_terisi_penuh(self):
        for jenis in ("all", "adm", "gl"):
            with self.subTest(jenis):
                self.cek(payload(), jenis)

    def test_tiga_jenis_file_kosong(self):
        for jenis in ("all", "adm", "gl"):
            with self.subTest(jenis):
                p = payload_kosong()
                hasil = importer.parse_xlsx(xlsx(jenis, p))["payload"]
                self.assertEqual(hasil["start"], p["start"])
                self.assertTrue(all(set(s["shifts"]) == {"-"} for d in hasil["divisions"] for s in d["staff"]))

    def test_izin_dan_sakit_terbaca_kembali(self):
        p = payload_kosong()
        p["divisions"][0]["staff"][0]["shifts"] = "IIKKPPSSRRLL-I"
        for jenis in ("all", "adm", "gl"):
            with self.subTest(jenis):
                self.cek(p, jenis)

    def test_jumlah_staff_berbeda_dan_nama_unik(self):
        p = payload()
        p["divisions"][0]["staff"] = p["divisions"][0]["staff"][:2]
        p["divisions"][3]["staff"].append({"name": "Nama Panjang Sekali & <b>Tebal</b>", "shifts": "P" * 14})
        for jenis in ("all", "adm", "gl"):
            with self.subTest(jenis):
                self.cek(p, jenis)

    def test_jam_kerja_dibaca_dan_dikosongkan_kalau_kosong(self):
        p = payload()
        p["divisions"][1]["hours"] = {"P": "07.00–15.00", "S": "", "R": "15.00–23.00", "L": "Libur"}
        for jenis in ("all", "adm", "gl"):
            hasil = importer.parse_xlsx(xlsx(jenis, p))["payload"]
            self.assertEqual(hasil["divisions"][1]["hours"], utuh(p)["divisions"][1]["hours"], jenis)

    def test_tanggal_lintas_tahun_dan_kabisat(self):
        for mulai in ("2026-12-20", "2026-12-31", "2027-12-27", "2028-02-20", "2028-02-27"):
            for jenis in ("all", "gl"):
                with self.subTest(mulai=mulai, jenis=jenis):
                    hasil = importer.parse_xlsx(xlsx(jenis, payload(mulai)))
                    self.assertEqual(hasil["payload"]["start"], mulai)
                    self.assertEqual(hasil["info"]["warnings"], [])


# Tes sumber tanggal mulai
class SumberTanggal(unittest.TestCase):
    @unittest.skipUnless(openpyxl, "butuh openpyxl")
    def test_tanggal_dari_judul_periode_untuk_file_satu_sheet(self):
        hasil = importer.parse_xlsx(xlsx("gl"))
        self.assertEqual(hasil["info"]["source"], "judul Periode")
        self.assertEqual(hasil["info"]["sheet"], "Jadwal Global")

    def test_semua_sheet_memakai_config_dan_sheet_administrator(self):
        hasil = importer.parse_xlsx(xlsx("all"))
        self.assertEqual((hasil["info"]["source"], hasil["info"]["sheet"]), ("sheet Config", "Administrator"))

    @unittest.skipUnless(openpyxl, "butuh openpyxl")
    def test_tanggal_dari_header_kalau_judul_hilang(self):
        def hapus(wb):
            wb["Jadwal Global"]["A2"] = None
        hasil = importer.parse_xlsx(ubah(xlsx("gl"), hapus))
        start = date.fromisoformat(hasil["payload"]["start"])
        self.assertEqual((start.month, start.day, start.weekday()), (11, 20, 4))
        self.assertEqual(hasil["info"]["source"], "header tabel")
        self.assertTrue(any("tahun" in w.lower() for w in hasil["info"]["warnings"]))

    @unittest.skipUnless(openpyxl, "butuh openpyxl")
    def test_config_menang_atas_judul(self):
        def ganti(wb):
            wb["Config"]["C4"] = 5
        hasil = importer.parse_xlsx(ubah(xlsx("all"), ganti))
        self.assertEqual(hasil["payload"]["start"], "2026-11-05")

    @unittest.skipUnless(openpyxl, "butuh openpyxl")
    def test_config_tanggal_tidak_ada_di_kalender_ditolak(self):
        def ganti(wb):
            wb["Config"]["C4"], wb["Config"]["D4"] = 31, "Februari"
        with self.assertRaisesRegex(ScheduleError, "Config"):
            importer.parse_xlsx(ubah(xlsx("all"), ganti))

    def test_judul_dan_header_hanya_ada_di_xlsx_buatan_tangan(self):
        cells = {"A2": "Periode: Sabtu, 20 Desember 2026 – Jumat, 2 Januari 2027  (14 hari)",
                 "A4": "BAR", "A6": "NO", "B6": "NAMA", "A7": 1, "B7": "Sadewa", "C7": "pagi ", "D7": "MALAM", "E7": "libur"}
        hasil = importer.parse_xlsx(xlsx_mini({"Jadwal Global": cells}))
        self.assertEqual(hasil["payload"]["start"], "2026-12-20")
        self.assertEqual(hasil["payload"]["divisions"][0]["staff"][0]["shifts"], "PRL" + "-" * 11)


# Tes isi file tidak wajar
class IsiTidakWajar(unittest.TestCase):
    @unittest.skipUnless(openpyxl, "butuh openpyxl")
    def test_shift_tidak_dikenal_dikosongkan_dan_diberi_peringatan(self):
        def ganti(wb):
            ws = wb["Jadwal Global"]
            ws["C7"], ws["D7"], ws["E7"] = "Sore", "Pagi", "-"
        hasil = importer.parse_xlsx(ubah(xlsx("gl", payload_kosong()), ganti))
        self.assertEqual(hasil["payload"]["divisions"][0]["staff"][0]["shifts"], "-P" + "-" * 12)
        self.assertEqual(len(hasil["info"]["warnings"]), 1)
        self.assertIn("C7", hasil["info"]["warnings"][0])

    @unittest.skipUnless(openpyxl, "butuh openpyxl")
    def test_nama_kosong_dilewati_dan_divisi_tak_dikenal_dilewati(self):
        def ganti(wb):
            ws = wb["Jadwal Global"]
            ws["B8"] = None
            ws["A4"] = "RESTO"
        hasil = importer.parse_xlsx(ubah(xlsx("gl"), ganti))
        self.assertEqual([d["key"] for d in hasil["payload"]["divisions"]], ["FLOOR", "CASHIER", "KITCHEN"])
        self.assertTrue(any("RESTO" in w for w in hasil["info"]["warnings"]))

    def test_judul_blok_terlalu_panjang_dilewati_bukan_membatalkan_impor(self):
        cells = {"A2": "Periode: Jumat, 20 November – Kamis, 3 Desember 2026  (14 hari)",
                 "A4": "x" * 200, "A6": "NO", "B6": "NAMA", "A7": 1, "B7": "Budi",
                 "A14": "BAR", "A16": "NO", "B16": "NAMA", "A17": 1, "B17": "Sadewa", "C17": "Pagi"}
        hasil = importer.parse_xlsx(xlsx_mini({"Administrator": cells}))
        self.assertEqual([d["key"] for d in hasil["payload"]["divisions"]], ["BAR"])
        self.assertTrue(any("tidak dikenali" in w for w in hasil["info"]["warnings"]))

    def test_tidak_ada_divisi_dikenal(self):
        cells = {"A2": "Periode: Jumat, 20 November – Kamis, 3 Desember 2026  (14 hari)",
                 "A4": "GUDANG", "A6": "NO", "B6": "NAMA", "A7": 1, "B7": "Budi"}
        with self.assertRaisesRegex(ScheduleError, "divisi"):
            importer.parse_xlsx(xlsx_mini({"Jadwal Global": cells}))

    def test_sheet_tanpa_tabel_jadwal(self):
        with self.assertRaisesRegex(ScheduleError, "Format file tidak dikenali"):
            importer.parse_xlsx(xlsx_mini({"Sheet1": {"A1": "halo", "B2": 5}}))

    def test_nama_terlalu_panjang(self):
        cells = {"A2": "Periode: Jumat, 20 November – Kamis, 3 Desember 2026  (14 hari)",
                 "A4": "BAR", "A6": "NO", "B6": "NAMA", "A7": 1, "B7": "x" * (cfg.MAX_NAME + 1)}
        with self.assertRaisesRegex(ScheduleError, "B7"):
            importer.parse_xlsx(xlsx_mini({"Administrator": cells}))


# Tes file rusak
class FileRusak(unittest.TestCase):
    def test_bukan_zip(self):
        with self.assertRaisesRegex(ScheduleError, "bukan file Excel"):
            importer.parse_xlsx(b"ini teks biasa")

    def test_xls_lama_ditolak(self):
        with self.assertRaisesRegex(ScheduleError, "bukan file Excel"):
            importer.parse_xlsx(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 200)

    def test_zip_tanpa_workbook(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.txt", "x")
        with self.assertRaisesRegex(ScheduleError, "bukan file Excel"):
            importer.parse_xlsx(buf.getvalue())

    def test_xml_rusak(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml", "<workbook><sheets>")
        with self.assertRaisesRegex(ScheduleError, "rusak"):
            importer.parse_xlsx(buf.getvalue())

    def test_terlalu_besar(self):
        with self.assertRaisesRegex(ScheduleError, "terlalu besar"):
            importer.parse_xlsx(b"0" * (importer.MAX_FILE + 1))

    def test_file_dirusak_acak_hanya_menghasilkan_scheduleerror(self):
        import random
        rng = random.Random(7)
        asli = xlsx("all")
        for i in range(150):
            data = bytearray(asli)
            for _ in range(rng.choice([1, 3, 10, 40])):
                data[rng.randrange(len(data))] = rng.randrange(256)
            try:
                importer.parse_xlsx(bytes(data))
            except ScheduleError:
                pass
            except Exception as err:
                self.fail(f"percobaan {i}: {type(err).__name__}: {err}")
        for potong in (30, len(asli) // 2, len(asli) - 5):
            with self.assertRaises(ScheduleError):
                importer.parse_xlsx(asli[:potong])

    def test_xml_encoding_aneh_ditolak_dengan_pesan_ramah(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTFa8"?><workbook/>')
        with self.assertRaisesRegex(ScheduleError, "rusak"):
            importer.parse_xlsx(buf.getvalue())

    def test_base64_rusak_dan_kosong(self):
        for isi in ("%%%bukan-base64%%%", "", None, 123):
            with self.subTest(isi=isi), self.assertRaises(ScheduleError):
                importer.parse_b64(isi)


# Tes endpoint POST /api/import
class EndpointHttp(unittest.TestCase):
    def setUp(self):
        from jadwal import server as aplikasi
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._asli = (cfg.DATA_DIR, cfg.STATE_FILE)
        cfg.DATA_DIR, cfg.STATE_FILE = base, base / "state.json"
        self.server = aplikasi.make_server("127.0.0.1", 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        cfg.DATA_DIR, cfg.STATE_FILE = self._asli
        self.tmp.cleanup()

    def kirim(self, body, metode="POST"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            conn.request(metode, "/api/import", body=body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            return resp.status, json.loads(resp.read().decode("utf-8"))
        finally:
            conn.close()

    def test_import_berhasil_dan_tidak_menyimpan_apa_pun(self):
        data = base64.b64encode(xlsx("all")).decode()
        status, j = self.kirim(json.dumps({"name": "jadwal.xlsx", "data": data}).encode())
        self.assertEqual(status, 200)
        self.assertTrue(j["ok"])
        self.assertEqual(j["payload"], utuh(payload()))
        self.assertFalse(cfg.STATE_FILE.exists())

    def test_file_salah_dibalas_422_dengan_pesan_indonesia(self):
        status, j = self.kirim(json.dumps({"data": base64.b64encode(b"bukan excel").decode()}).encode())
        self.assertEqual(status, 422)
        self.assertIn("bukan file Excel", j["error"])

    def test_permintaan_aneh(self):
        for body in (b"bukan json", b"[]", json.dumps({"data": ""}).encode(), json.dumps({}).encode()):
            with self.subTest(body=body[:20]):
                status, j = self.kirim(body)
                self.assertIn(status, (400, 422))
                self.assertIn("error", j)

    def test_terlalu_besar_dibalas_413(self):
        status, j = self.kirim(b"x" * (512 * 1024 + 10))
        self.assertEqual(status, 413)

    def test_get_tidak_diizinkan(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("GET", "/api/import")
        self.assertEqual(conn.getresponse().status, 405)
        conn.close()


# Tes kartu Import di index.html
class HalamanWeb(unittest.TestCase):

    def setUp(self):
        self.html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    def test_kartu_import_ada_di_bawah_hari_dan_check(self):
        self.assertLess(self.html.index("Sesuai kalender"), self.html.index("${impBox()}"))

    def test_input_file_menerima_xlsx_dan_memakai_endpoint_import(self):
        self.assertIn('accept=".xlsx,', self.html)
        self.assertIn("fetch('/api/import'", self.html)

    def test_halaman_punya_pilihan_izin_dan_sakit_setelah_kosong(self):
        self.assertIn("[...KS,'-',...KA]", self.html)
        self.assertIn("I:['Izin'", self.html)
        self.assertIn("K:['Sakit'", self.html)
        self.assertIn("I:['#d9d2e9','#3b2f58']", self.html)
        self.assertIn("K:['#c6e0b4','#375623']", self.html)

    def test_izin_sakit_tidak_masuk_hitungan_halaman(self):
        # penghitung hanya mengenal P/S/R/L, jadi kode I/K otomatis tidak dihitung
        self.assertIn("const cnt=(k,i)=>{const c={P:0,S:0,R:0,L:0}", self.html)
        self.assertIn("if(x in c)c[x]++", self.html)

    def test_pembaca_file_punya_cadangan_untuk_webview_lama(self):
        self.assertIn("new FileReader()", self.html)

    def test_teks_dari_file_selalu_di_escape(self):
        for ekspresi in ("esc(q.name)", "esc(d.title)", "esc(w)", "esc(IM.msg)", "esc(IM.name)"):
            self.assertIn(ekspresi, self.html)

    def test_tidak_memakai_nama_bawaan_document_di_atribut(self):
        blok = self.html[self.html.index("let IM={st:"):]
        for panggilan in re.findall(r'onclick="([^"]+)"', blok):
            self.assertNotRegex(panggilan, r"(^|[^.\w])(close|open|write)\(")


if __name__ == "__main__":
    unittest.main()
