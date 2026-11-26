import copy
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

from jadwal import excel, image
from jadwal import settings as cfg
from jadwal.schedule import Schedule, ScheduleError, month_spans
from tests.sample import payload, payload_kosong

try:
    import openpyxl
except ImportError:
    openpyxl = None


# Buka hasil Excel untuk dicek
def muat(sheet, p=None):
    s = Schedule.from_payload(p or payload())
    return openpyxl.load_workbook(io.BytesIO(excel.build_workbook(s, sheet)))


# Daftar rumus di satu sheet
def daftar_rumus(ws):
    return [c.coordinate for row in ws.iter_rows() for c in row
            if isinstance(c.value, str) and c.value.startswith("=")]


# Tes validasi data jadwal
class ValidasiData(unittest.TestCase):
    def test_data_contoh_valid(self):
        s = Schedule.from_payload(payload())
        self.assertEqual(s.start, date(2026, 11, 20))
        self.assertEqual(s.period_text(),
                         "Periode: Jumat, 20 November – Kamis, 3 Desember 2026  (14 hari)")
        self.assertEqual(s.file_stem(), "jadwal_20nov-3des_2026")

    def test_data_ditolak(self):
        def coba(ubah):
            p = copy.deepcopy(payload())
            ubah(p)
            with self.assertRaises(ScheduleError):
                Schedule.from_payload(p)
        coba(lambda p: p.update(start="2026-02-30"))
        coba(lambda p: p.update(start="20-11-2026"))
        coba(lambda p: p["divisions"][0]["staff"][0].update(shifts="PPX"))
        coba(lambda p: p["divisions"][0]["staff"][0].update(shifts="P" * 13))
        coba(lambda p: p["divisions"][0]["staff"][0].update(name="   "))
        coba(lambda p: p["divisions"][0].update(key="BAR!"))
        coba(lambda p: p.update(divisions=[]))
        with self.assertRaises(ScheduleError):
            Schedule.from_payload("bukan dict")


# Tes isi file Excel
class HasilExcel(unittest.TestCase):
    def test_label_bulan_cocok_dengan_pita_bulan(self):
        for mulai in ("2026-11-20", "2026-12-25", "2026-05-31", "2027-02-20", "2028-02-20"):
            s = Schedule.from_payload(payload(mulai))
            labels = [excel.month_cell_value(s.start, k) for k in range(14)]
            for m in month_spans(s.days):
                nama = (cfg.MONTHS_SHORT if m["n"] < 2 else cfg.MONTHS_LONG)[m["m"]].upper()
                dalam = labels[m["i"]:m["i"] + m["n"]]
                self.assertEqual(dalam.count(nama), 1, (mulai, nama, labels))

    def test_bulan_satu_hari_pakai_singkatan(self):
        s = Schedule.from_payload(payload("2026-12-31"))
        self.assertEqual(excel.month_cell_value(s.start, 0), "DES")
        self.assertEqual([m["n"] for m in month_spans(s.days)], [1, 13])
        self.assertEqual(cfg.MONTHS_SHORT, ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul",
                                            "Agu", "Sept", "Okt", "Nov", "Des"])
        from jadwal.layout import build_model
        labels = [c["t"] for c in build_model(s, "adm")["cells"] if c["r"] == 3 and 2 <= c["c"] <= 15]
        self.assertEqual(labels, ["DES", "JANUARI"])

    @unittest.skipIf(openpyxl is None, "openpyxl tidak terpasang")
    def test_administrator_dan_global_saja_tanpa_rumus_dan_dropdown(self):
        for sheet, nama in (("adm", "Administrator"), ("gl", "Jadwal Global")):
            wb = muat(sheet)
            self.assertEqual(wb.sheetnames, [nama], sheet)
            self.assertEqual(wb.active.title, nama)
            ws = wb[nama]
            self.assertEqual(daftar_rumus(ws), [], sheet)
            self.assertEqual(len(ws.data_validations.dataValidation), 0, sheet)

    @unittest.skipIf(openpyxl is None, "openpyxl tidak terpasang")
    def test_isi_sheet_administrator_saja(self):
        s = Schedule.from_payload(payload())
        adm = muat("adm")["Administrator"]
        self.assertEqual(adm["A2"].value, s.period_text())
        self.assertEqual(adm["B7"].value, "Sadewa")
        self.assertEqual(adm["C7"].value, "Pagi")
        self.assertEqual(adm["T7"].value, 12)
        pita = [adm.cell(row=4, column=c).value for c in range(3, 17)]
        self.assertEqual(pita.count("NOVEMBER"), 1)
        self.assertEqual(pita.count("DESEMBER"), 1)
        self.assertEqual(adm["C5"].value, "Jum")
        self.assertEqual(adm["C6"].value, 20)

    @unittest.skipIf(openpyxl is None, "openpyxl tidak terpasang")
    def test_isi_sheet_global_saja(self):
        s = Schedule.from_payload(payload())
        gl = muat("gl")["Jadwal Global"]
        self.assertEqual(gl["A2"].value, s.period_text())
        self.assertEqual(gl["B7"].value, "Sadewa")
        self.assertEqual(gl["C7"].value, "Pagi")
        self.assertEqual(gl["R4"].value, "SHIFT BAR")
        self.assertEqual(gl["R5"].value, "Pagi")

    @unittest.skipIf(openpyxl is None, "openpyxl tidak terpasang")
    def test_semua_sheet_lengkap_dengan_rumus_dan_dropdown(self):
        s = Schedule.from_payload(payload())
        data = excel.build_workbook(s, "all")
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(data)))
        wb = openpyxl.load_workbook(io.BytesIO(data))
        self.assertEqual(wb.sheetnames, ["Config", "Administrator", "Jadwal Global"])
        self.assertEqual(wb.active.title, "Config")
        cfg_ws, adm, gl = wb["Config"], wb["Administrator"], wb["Jadwal Global"]
        self.assertEqual([len(daftar_rumus(w)) for w in (cfg_ws, adm, gl)], [3, 498, 558])
        self.assertEqual(cfg_ws["C4"].value, 20)
        self.assertEqual(cfg_ws["D4"].value, "November")
        self.assertEqual(cfg_ws["F4"].value, 2026)
        self.assertEqual(cfg_ws.column_dimensions["R"].hidden, True)
        self.assertTrue(str(cfg_ws["R4"].value).startswith('=IF(OR($C$4=""'))
        self.assertTrue(str(adm["A2"].value).startswith("=IF(Config!$R$4"))
        self.assertTrue(str(adm["C5"].value).startswith("=IF(Config!$R$4"))
        self.assertEqual(adm["B7"].value, "Sadewa")
        self.assertEqual(adm["C7"].value, "Pagi")
        self.assertEqual(adm["Q7"].value, "=COUNTIF($C7:$P7,Q$5)")
        self.assertEqual(adm["T7"].value, "=SUM(Q7:S7)")
        self.assertEqual(adm["C13"].value, "=COUNTIF(C$7:C$11,$A13)")
        self.assertTrue(str(gl["C7"].value).startswith("=IF(Administrator!"))
        self.assertEqual(gl["C6"].value, "=Administrator!C6")
        dv = adm.data_validations.dataValidation
        self.assertEqual(len(dv), 4)
        self.assertTrue(all("Malam" in d.formula1 for d in dv))
        self.assertEqual(len(cfg_ws.data_validations.dataValidation), 3)
        wv = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        self.assertEqual(wv["Administrator"]["A2"].value, s.period_text())
        self.assertEqual(wv["Jadwal Global"]["C7"].value, "Pagi")
        self.assertEqual(wv["Administrator"]["T7"].value, 12)

    def test_sheet_tidak_dikenal_ditolak(self):
        with self.assertRaises(ValueError):
            excel.build_workbook(Schedule.from_payload(payload()), "config")

    @unittest.skipIf(openpyxl is None, "openpyxl tidak terpasang")
    def test_nama_berawalan_sama_dengan_tetap_teks(self):
        p = payload()
        p["divisions"][0]["staff"][0]["name"] = '=HYPERLINK("http://x")'
        for sheet, nama in (("adm", "Administrator"), ("gl", "Jadwal Global"), ("all", "Administrator")):
            ws = muat(sheet, p)[nama]
            self.assertEqual(ws["B7"].data_type, "s", sheet)

    def test_divisi_tanpa_staff(self):
        p = payload()
        p["divisions"][2]["staff"] = []
        s = Schedule.from_payload(p)
        for sheet in ("adm", "gl", "all"):
            self.assertTrue(zipfile.is_zipfile(io.BytesIO(excel.build_workbook(s, sheet))), sheet)
        self.assertTrue(image.render(s, "adm").startswith(b"\x89PNG"))


# Tes shift malam dan sel kosong
class ShiftMalamDanKosong(unittest.TestCase):
    def test_nama_shift_malam(self):
        self.assertEqual(cfg.SHIFTS["R"][0], "Malam")
        self.assertNotIn("Sore", [v[0] for v in cfg.SHIFTS.values()])

    def test_sel_kosong_valid_dan_tidak_dihitung(self):
        s = Schedule.from_payload(payload_kosong())
        for d in s.divisions:
            for st in d.staff:
                self.assertEqual(st.shifts, "-" * 14)
            self.assertEqual([d.count(c, 0) for c in cfg.SHIFT_ORDER], [0, 0, 0, 0])
            self.assertEqual(d.totals(d.staff[0]), {c: 0 for c in cfg.SHIFT_ORDER})
        self.assertEqual(Schedule.from_payload(s.to_payload()).to_payload(), s.to_payload())

    def test_kode_ngawur_tetap_ditolak(self):
        p = payload_kosong()
        p["divisions"][0]["staff"][0]["shifts"] = "-" * 13 + "X"
        with self.assertRaises(ScheduleError):
            Schedule.from_payload(p)

    def test_tahun_mulai_2025(self):
        with self.assertRaises(ScheduleError):
            Schedule.from_payload(payload("2024-12-31"))
        Schedule.from_payload(payload("2025-01-01"))

    def test_jam_kerja_boleh_kosong(self):
        p = payload_kosong()
        for d in p["divisions"]:
            d["hours"] = {"P": "", "S": "", "R": "", "L": "Tidak bertugas"}
        s = Schedule.from_payload(p)
        self.assertEqual(s.divisions[0].hours, {"P": "", "S": "", "R": "", "L": "Tidak bertugas"})
        del p["divisions"][0]["hours"]
        self.assertEqual(Schedule.from_payload(p).divisions[0].hours["L"], "Tidak bertugas")
        self.assertEqual(Schedule.from_payload(p).divisions[0].hours["P"], "")

    @unittest.skipIf(openpyxl is None, "openpyxl tidak terpasang")
    def test_excel_jam_kosong_tidak_jadi_nol(self):
        p = payload_kosong()
        for d in p["divisions"]:
            d["hours"] = {"P": "", "S": "", "R": "", "L": "Tidak bertugas"}
        gl = muat("gl", p)["Jadwal Global"]
        self.assertIn(gl["T5"].value, (None, ""))
        self.assertEqual(gl["T8"].value, "Tidak bertugas")
        rumus = str(muat("all", p)["Jadwal Global"]["T5"].value)
        self.assertTrue(rumus.startswith('=IF(Administrator!'), rumus)

    def test_png_dan_excel_data_kosong(self):
        from PIL import Image
        s = Schedule.from_payload(payload_kosong())
        for kind in ("adm", "gl"):
            Image.open(io.BytesIO(image.render(s, kind, scale=1))).load()
        for sheet in ("adm", "gl", "all"):
            self.assertTrue(zipfile.is_zipfile(io.BytesIO(excel.build_workbook(s, sheet))), sheet)

    @unittest.skipIf(openpyxl is None, "openpyxl tidak terpasang")
    def test_excel_sel_kosong_dan_malam(self):
        for sheet in ("adm", "all"):
            adm = muat(sheet, payload_kosong())["Administrator"]
            self.assertIn(adm["B7"].value, ("Sadewa",))
            for kol in "CDEFGHIJKLMNOP":
                self.assertIn(adm[f"{kol}7"].value, (None, ""), (sheet, kol))
            teks = " ".join(str(c.value) for row in adm.iter_rows() for c in row if c.value)
            self.assertIn("Malam", teks)
            self.assertNotIn("Sore", teks)
        dv = [d.formula1 for d in adm.data_validations.dataValidation]
        self.assertTrue(any("Malam" in (x or "") for x in dv), dv)


# Tes gambar PNG
class HasilPNG(unittest.TestCase):
    def test_png_kedua_sheet(self):
        from PIL import Image
        s = Schedule.from_payload(payload())
        for kind in ("adm", "gl"):
            png = image.render(s, kind, scale=3)
            im = Image.open(io.BytesIO(png))
            self.assertEqual(im.format, "PNG")
            self.assertGreater(im.size[0], 2000)
            self.assertGreater(im.size[1], 2000)

    def test_font_ditemukan(self):
        self.assertIsNotNone(image._font_path(False))
        self.assertIsNotNone(image._font_path(True))


# Balasan HTTP untuk tes
class Balasan:

    def __init__(self, resp, data):
        self.status_code, self.headers, self.data = resp.status, resp.msg, data

    def get_json(self):
        return json.loads(self.data.decode("utf-8"))


# Tes API server HTTP
class ApiServer(unittest.TestCase):

    def setUp(self):
        from jadwal import server as aplikasi
        self.aplikasi = aplikasi
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._asli = (cfg.DATA_DIR, cfg.STATE_FILE)
        cfg.DATA_DIR, cfg.STATE_FILE = base, base / "state.json"
        self._skala = image.SCALE
        image.SCALE = 2
        self.server = aplikasi.make_server("127.0.0.1", 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        image.SCALE = self._skala
        cfg.DATA_DIR, cfg.STATE_FILE = self._asli
        self.tmp.cleanup()

    def minta(self, metode, jalur, json_body=None, mentah=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            body = mentah if mentah is not None else (
                json.dumps(json_body).encode() if json_body is not None else None)
            conn.request(metode, jalur, body=body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            return Balasan(resp, resp.read())
        finally:
            conn.close()

    def get(self, jalur):
        return self.minta("GET", jalur)

    def put(self, jalur, json=None):
        return self.minta("PUT", jalur, json)

    def post(self, jalur, json=None, data=None):
        return self.minta("POST", jalur, json, None if data is None else data.encode())

    def test_simpan_tema_memberi_tahu_splash_android(self):
        panggilan = []
        asli = (self.aplikasi.droid.ON_ANDROID, self.aplikasi.droid.apply_splash_theme)
        self.aplikasi.droid.apply_splash_theme = lambda tema=None: panggilan.append(tema)
        try:
            self.assertEqual(self.put("/api/theme", {"theme": "light"}).status_code, 200)     # bukan Android: tidak dipanggil
            self.assertEqual(panggilan, [])
            self.aplikasi.droid.ON_ANDROID = True
            self.assertEqual(self.put("/api/theme", {"theme": "dark"}).status_code, 200)
            self.assertEqual(self.put("/api/theme", {"theme": "ungu"}).status_code, 400)       # tema asing: tidak dipanggil
        finally:
            self.aplikasi.droid.ON_ANDROID, self.aplikasi.droid.apply_splash_theme = asli
        self.assertEqual(panggilan, ["dark"])
        self.assertEqual((Path(self.tmp.name) / "theme.txt").read_text(encoding="utf-8"), "dark")

    def test_halaman_loading_lalu_aplikasi(self):
        r = self.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"spinner", r.data)
        self.assertIn(b"location.replace('/app')", r.data)
        self.assertIn(b"LOADING_MS = 2000", r.data)
        r = self.get("/app")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"/api/export/", r.data)
        self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_halaman_tak_dikenal(self):
        self.assertEqual(self.get("/tidak-ada").status_code, 404)
        self.assertEqual(self.get("/favicon.ico").status_code, 204)
        self.assertEqual(self.post("/app", json={}).status_code, 405)

    def test_simpan_dan_muat_state(self):
        self.assertEqual(self.get("/api/state").get_json(), {})
        self.assertEqual(self.put("/api/state", json=payload()).status_code, 200)
        data = self.get("/api/state").get_json()
        self.assertEqual(data["start"], "2026-11-20")
        self.assertEqual(data["divisions"][0]["staff"][0]["name"], "Sadewa")
        self.assertEqual(self.put("/api/state", json={"start": "x"}).status_code, 422)

    def test_export(self):
        for jenis, sheet, nama, awal in (
                ("xlsx", "adm", "jadwal_20nov-3des_2026_admin.xlsx", b"PK"),
                ("xlsx", "gl", "jadwal_20nov-3des_2026_global.xlsx", b"PK"),
                ("xlsx", "all", "jadwal_kerja.xlsx", b"PK"),
                ("png", "adm", "jadwal_20nov-3des_2026_admin.png", b"\x89PNG"),
                ("png", "gl", "jadwal_20nov-3des_2026_global.png", b"\x89PNG"),
                ("pdf", "adm", "jadwal_20nov-3des_2026_admin.pdf", b"%PDF-"),
                ("pdf", "gl", "jadwal_20nov-3des_2026_global.pdf", b"%PDF-")):
            r = self.post(f"/api/export/{jenis}", json={**payload(), "sheet": sheet})
            self.assertEqual(r.status_code, 200, (jenis, sheet))
            self.assertIn(nama, r.headers["Content-Disposition"])
            self.assertTrue(r.data.startswith(awal))
            self.assertEqual(list(Path(self.tmp.name).iterdir()), [], (jenis, sheet))
            self.assertFalse((cfg.BASE_DIR / "output").exists(), (jenis, sheet))

    def test_export_android_langsung_ke_downloads(self):
        tersimpan = []
        asli = (self.aplikasi.droid.ON_ANDROID, self.aplikasi.droid.save_to_downloads)
        self.aplikasi.droid.ON_ANDROID = True
        self.aplikasi.droid.save_to_downloads = lambda nama, data, mime: tersimpan.append((nama, data, mime))
        try:
            r = self.post("/api/export/xlsx", json={**payload(), "sheet": "all"})
            r2 = self.post("/api/export/png", json={**payload(), "sheet": "gl"})
            r3 = self.post("/api/export/pdf", json={**payload(), "sheet": "adm"})
        finally:
            self.aplikasi.droid.ON_ANDROID, self.aplikasi.droid.save_to_downloads = asli
        self.assertEqual(r.get_json(), {"saved": "jadwal_kerja.xlsx", "folder": "Download"})
        self.assertEqual(r2.get_json()["saved"], "jadwal_20nov-3des_2026_global.png")
        self.assertEqual(r3.get_json()["saved"], "jadwal_20nov-3des_2026_admin.pdf")
        self.assertIn("application/json", r.headers["Content-Type"])
        self.assertIsNone(r.headers["Content-Disposition"])
        self.assertEqual([t[0] for t in tersimpan], ["jadwal_kerja.xlsx", "jadwal_20nov-3des_2026_global.png",
                                                     "jadwal_20nov-3des_2026_admin.pdf"])
        self.assertTrue(tersimpan[0][1].startswith(b"PK"))
        self.assertEqual(tersimpan[1][2], "image/png")
        self.assertEqual(tersimpan[2][2], "application/pdf")
        self.assertTrue(tersimpan[2][1].startswith(b"%PDF-"))
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_png_dan_pdf_semua_sheet_ditolak(self):
        for jenis, label in (("png", "Save PNG"), ("pdf", "PDF - A4")):
            r = self.post(f"/api/export/{jenis}", json={**payload(), "sheet": "all"})
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.get_json()["error"], f"{label} hanya untuk Administrator atau Jadwal Global.")

    @unittest.skipIf(openpyxl is None, "openpyxl tidak terpasang")
    def test_export_excel_sesuai_pilihan(self):
        for sheet, nama in (("adm", ["Administrator"]), ("gl", ["Jadwal Global"]),
                            ("all", ["Config", "Administrator", "Jadwal Global"])):
            r = self.post("/api/export/xlsx", json={**payload(), "sheet": sheet})
            wb = openpyxl.load_workbook(io.BytesIO(r.data))
            self.assertEqual(wb.sheetnames, nama, sheet)
        r = self.post("/api/export/xlsx", json={**payload(), "sheet": "config"})
        self.assertEqual(openpyxl.load_workbook(io.BytesIO(r.data)).sheetnames, ["Administrator"])

    def test_galat_berupa_json(self):
        p = payload()
        p["divisions"][0]["staff"][0]["shifts"] = "PPX"
        r = self.post("/api/export/xlsx", json=p)
        self.assertEqual(r.status_code, 422)
        self.assertIn("error", r.get_json())
        self.assertEqual(self.post("/api/export/docx", json=payload()).status_code, 404)
        self.assertEqual(self.post("/api/export/xlsx", data="halo").status_code, 422)

    def test_isi_terlalu_besar_ditolak(self):
        r = self.post("/api/export/xlsx", data="x" * (600 * 1024))
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.get_json()["error"], "File terlalu besar.")

    def test_keluar_hanya_di_android(self):
        self.assertEqual(self.post("/api/exit", json={}).get_json(), {"ok": False})
        diminta, dipanggil = [], threading.Event()
        asli = (self.aplikasi.droid.ON_ANDROID, self.aplikasi.droid.exit_app)
        self.aplikasi.droid.ON_ANDROID = True
        self.aplikasi.droid.exit_app = lambda: (diminta.append(1), dipanggil.set())
        try:
            r = self.post("/api/exit", json={})
            self.assertTrue(dipanggil.wait(5))
        finally:
            self.aplikasi.droid.ON_ANDROID, self.aplikasi.droid.exit_app = asli
        self.assertEqual(r.get_json(), {"ok": True})
        self.assertEqual(diminta, [1])


# Tes paket dan berkas Android
class PaketAndroid(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.spec = (cfg.BASE_DIR / "buildozer.spec").read_text(encoding="utf-8")

    def nilai(self, kunci):
        m = re.search(rf"^{re.escape(kunci)}\s*=\s*(.+)$", self.spec, re.M)
        self.assertIsNotNone(m, kunci)
        return m.group(1).strip()

    def test_port_dan_bootstrap(self):
        self.assertEqual(int(self.nilai("p4a.port")), cfg.ANDROID_PORT)
        self.assertEqual(self.nilai("p4a.bootstrap"), "webview")
        self.assertNotIn(cfg.ANDROID_PORT, cfg.BLOCKED_PORTS)

    def test_dependensi_tanpa_flask(self):
        req = self.nilai("requirements").lower()
        self.assertNotIn("flask", req)
        for nama in ("python3", "pillow", "xlsxwriter", "pyjnius"):
            self.assertIn(nama, req)

    def test_penyimpanan_downloads_butuh_android_10(self):
        self.assertGreaterEqual(int(self.nilai("android.minapi")), 29)

    def test_versi_dan_ikon(self):
        self.assertRegex(self.nilai("version"), r"^\d+\.\d+\.\d+$")
        self.assertTrue(self.nilai("android.numeric_version").isdigit())
        for kunci in ("icon.filename", "icon.adaptive_foreground.filename",
                      "icon.adaptive_background.filename", "presplash.filename"):
            rel = self.nilai(kunci).replace("%(source.dir)s/", "")
            self.assertTrue((cfg.BASE_DIR / rel).is_file(), rel)

    def test_main_dan_halaman_ada(self):
        self.assertTrue((cfg.BASE_DIR / "main.py").is_file())
        self.assertTrue((cfg.WEB_DIR / "loading.html").is_file())

    def test_hanya_satu_skrip_di_luar_folder(self):
        skrip = sorted(f.name for f in cfg.BASE_DIR.glob("*.py"))
        self.assertEqual(skrip, ["main.py"])

    def test_workflow_versi_dan_release(self):
        wf = (cfg.BASE_DIR / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
        for kata in ("KEYSTORE_BASE64", "KEYSTORE_PASSWORD", "P4A_RELEASE_KEYSTORE", "action-gh-release",
                     "buildozer -v android release", "next_version.sh"):
            self.assertIn(kata, wf)

    def test_nomor_versi_naik_dengan_carry(self):
        import shutil
        import subprocess
        if shutil.which("bash") is None:
            self.skipTest("bash tidak ada")
        skrip = cfg.BASE_DIR / ".github" / "next_version.sh"

        def berikut(tag):
            out = subprocess.run(["bash", str(skrip), tag], capture_output=True, text=True, check=True).stdout
            versi, kode = out.split()
            return versi, int(kode)

        kasus = [("", "1.0.0"), ("v1.0.0", "1.0.1"), ("v1.0.8", "1.0.9"), ("v1.0.9", "1.1.0"),
                 ("v1.1.9", "1.2.0"), ("v1.8.9", "1.9.0"), ("v1.9.8", "1.9.9"), ("v1.9.9", "2.0.0"),
                 ("v2.0.0", "2.0.1"), ("v2.9.9", "3.0.0"), ("v1.0.10", "1.1.0")]
        for tag, harapan in kasus:
            self.assertEqual(berikut(tag)[0], harapan, tag)
        tag, urut, kode_lama = "", [], 0
        for _ in range(1000):
            versi, kode = berikut(tag)
            self.assertTrue(all(0 <= int(x) <= 9 for x in versi.split(".")[1:]), versi)
            self.assertGreater(kode, kode_lama, versi)
            urut.append(versi)
            tag, kode_lama = "v" + versi, kode
        self.assertEqual(urut[:3], ["1.0.0", "1.0.1", "1.0.2"])
        self.assertEqual(urut[9:11], ["1.0.9", "1.1.0"])
        self.assertEqual(urut[99:101], ["1.9.9", "2.0.0"])

    def test_data_di_folder_pribadi_android(self):
        import importlib
        import os
        asli = os.environ.get("ANDROID_PRIVATE")
        os.environ["ANDROID_PRIVATE"] = "/data/data/org.jadwal.jadwalkerja/files"
        try:
            importlib.reload(cfg)
            self.assertEqual(cfg.DATA_DIR, Path("/data/data/org.jadwal.jadwalkerja/files/data"))
        finally:
            if asli is None:
                os.environ.pop("ANDROID_PRIVATE")
            else:
                os.environ["ANDROID_PRIVATE"] = asli
            importlib.reload(cfg)


# Tes pemilihan port
class PilihPort(unittest.TestCase):
    def test_port_5000_dilewati(self):
        from jadwal import server as aplikasi
        self.assertNotEqual(aplikasi.pick_port("127.0.0.1", 5000), 5000)

    def test_port_default(self):
        self.assertEqual(cfg.DEFAULT_PORT, 8888)
        self.assertIn(5000, cfg.BLOCKED_PORTS)



# Tes performa: startup ringan dan PNG tidak dikompres berlebihan
class PerformaRingan(unittest.TestCase):
    def test_server_tidak_memuat_modul_berat_saat_start(self):
        import subprocess
        import sys
        from pathlib import Path

        kode = ("import sys, jadwal.server; "
                "print(','.join(m for m in ('PIL', 'xlsxwriter', 'jadwal.excel', 'jadwal.image', 'jadwal.importer') "
                "if m in sys.modules))")
        root = Path(__file__).resolve().parent.parent
        hasil = subprocess.run([sys.executable, "-c", kode], cwd=root, capture_output=True, text=True, check=True)
        self.assertEqual(hasil.stdout.strip(), "")

    def test_png_memakai_kompresi_cepat_dan_hasilnya_valid(self):
        import io

        from PIL import Image

        from jadwal import image
        from jadwal.schedule import Schedule
        from tests.sample import payload

        self.assertIn(image.PNG_COMPRESS, range(1, 8))
        data = image.render(Schedule.from_payload(payload()), "gl", scale=2)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertGreater(Image.open(io.BytesIO(data)).size[0], 1000)


if __name__ == "__main__":
    unittest.main()
