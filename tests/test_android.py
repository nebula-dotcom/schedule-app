"""Tes bagian Android yang bisa dijalankan tanpa HP: pembersih riwayat WebView dan hook p4a."""
import importlib.util
import re
import unittest
from pathlib import Path

from jadwal import droid
from jadwal import settings as cfg

ROOT = Path(__file__).resolve().parent.parent


class WebViewPalsu:
    def __init__(self, url, bisa_kembali=True, fokus=True):
        self.url, self.bisa_kembali, self.fokus = url, bisa_kembali, fokus
        self.dibersihkan = self.minta_fokus = False

    def getUrl(self):
        return self.url

    def canGoBack(self):
        return self.bisa_kembali

    def clearHistory(self):
        self.dibersihkan, self.bisa_kembali = True, False

    def hasFocus(self):
        return self.fokus

    def requestFocus(self):
        self.minta_fokus = True


class BersihkanRiwayat(unittest.TestCase):
    def test_riwayat_dihapus_saat_aplikasi_tampil(self):
        w = WebViewPalsu("http://127.0.0.1:8765/app")
        droid._tidy(w)
        self.assertTrue(w.dibersihkan)

    def test_riwayat_dibiarkan_saat_layar_loading(self):
        for url in ("http://127.0.0.1:8765/", "file:///data/_load.html", None):
            w = WebViewPalsu(url)
            droid._tidy(w)
            self.assertFalse(w.dibersihkan, url)

    def test_fokus_diminta_lagi_kalau_hilang(self):
        w = WebViewPalsu("http://127.0.0.1:8765/app", fokus=False)
        droid._tidy(w)
        self.assertTrue(w.minta_fokus)
        w2 = WebViewPalsu("http://127.0.0.1:8765/app", fokus=True)
        droid._tidy(w2)
        self.assertFalse(w2.minta_fokus)


class HookP4a(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("p4a_hook", ROOT / "p4a" / "hook.py")
        self.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hook)

    def test_port_sama_dengan_aplikasi(self):
        self.assertEqual(self.hook.PORT, cfg.ANDROID_PORT)

    def test_load_html_kembali_ke_aplikasi_lewat_riwayat(self):
        html = self.hook.render_loading()
        self.assertIn("back_forward", html)
        self.assertIn(f"http://127.0.0.1:{cfg.ANDROID_PORT}/app", html)
        self.assertNotIn("@PORT@", html)


class TemaLatar(unittest.TestCase):
    def test_tema_dan_resource_terpasang(self):
        spec = (ROOT / "buildozer.spec").read_text(encoding="utf-8")
        self.assertRegex(spec, r"(?m)^android\.apptheme\s*=\s*@style/JadwalTheme\s*$")
        for sub in ("values", "values-v31"):
            self.assertIn(f"android_res/{sub}/jadwal_theme.xml:{sub}/jadwal_theme.xml", spec)
            self.assertTrue((ROOT / "android_res" / sub / "jadwal_theme.xml").is_file())

    def test_splash_sistem_tanpa_ikon_dan_force_dark(self):
        xml = (ROOT / "android_res" / "values-v31" / "jadwal_theme.xml").read_text(encoding="utf-8")
        self.assertIn("forceDarkAllowed", xml)
        self.assertIn("windowSplashScreenAnimatedIcon\">@android:color/transparent<", xml)


class WarnaSeragam(unittest.TestCase):
    """Satu warna dasar untuk semuanya: --bg di web/index.html = web/loading.html = layar loading bawaan hook
    = latar jendela dan splash Android = presplash (buildozer.spec + assets/presplash.png).
    Mau ganti warna dasar? Ubah --bg di index.html, lalu tes ini menunjukkan file mana yang masih berbeda."""

    HEX = r"(#[0-9a-fA-F]{6})"

    @staticmethod
    def _baca(*bagian):
        return ROOT.joinpath(*bagian).read_text(encoding="utf-8")

    def _cari(self, pola, teks, nama):
        m = re.search(pola, teks)
        self.assertIsNotNone(m, f"warna tidak ditemukan di {nama}")
        return m.group(1).lower()

    def setUp(self):
        self.dasar = self._cari(r":root\{--bg:" + self.HEX, self._baca("web", "index.html"), "web/index.html (--bg)")

    def test_loading_html(self):
        warna = self._cari(r"html,body\{[^}]*background:" + self.HEX, self._baca("web", "loading.html"), "web/loading.html")
        self.assertEqual(warna, self.dasar, "web/loading.html")

    def test_loading_bawaan_hook(self):
        spec = importlib.util.spec_from_file_location("p4a_hook3", ROOT / "p4a" / "hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        warna = self._cari(r"html,body\{[^}]*background:" + self.HEX, hook.render_loading(), "p4a/hook.py (LOADING_HTML)")
        self.assertEqual(warna, self.dasar, "p4a/hook.py (LOADING_HTML)")

    def test_tema_android(self):
        untuk = {"values": ("windowBackground",), "values-v31": ("windowBackground", "windowSplashScreenBackground")}
        for folder, kunci in untuk.items():
            xml = self._baca("android_res", folder, "jadwal_theme.xml")
            for k in kunci:
                warna = self._cari(k + r'">' + self.HEX + "<", xml, f"android_res/{folder}/jadwal_theme.xml ({k})")
                self.assertEqual(warna, self.dasar, f"android_res/{folder}/jadwal_theme.xml ({k})")

    def test_latar_webview(self):
        spec = importlib.util.spec_from_file_location("p4a_hook4", ROOT / "p4a" / "hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        self.assertEqual("#" + hook.LATAR_JAVA[4:].lower(), self.dasar, "p4a/hook.py (LATAR_JAVA)")
        self.assertTrue(hook.LATAR_JAVA.upper().startswith("0XFF"), "latar WebView harus tidak transparan (alfa FF)")
        self.assertEqual(droid.LATAR_WEBVIEW.lower(), self.dasar, "jadwal/droid.py (LATAR_WEBVIEW)")

    def test_presplash(self):
        warna = self._cari(r"(?m)^android\.presplash_color\s*=\s*" + self.HEX, self._baca("buildozer.spec"),
                           "buildozer.spec (android.presplash_color)")
        self.assertEqual(warna, self.dasar, "buildozer.spec (android.presplash_color)")
        from PIL import Image
        gambar = Image.open(ROOT / "assets" / "presplash.png").convert("RGB")
        for titik in ((0, 0), (gambar.width // 2, gambar.height // 2), (gambar.width - 1, gambar.height - 1)):
            self.assertEqual("#%02x%02x%02x" % gambar.getpixel(titik), self.dasar, f"assets/presplash.png {titik}")


class HookTema(unittest.TestCase):
    @staticmethod
    def _hook():
        spec = importlib.util.spec_from_file_location("p4a_hook2", ROOT / "p4a" / "hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        return hook

    def test_manifest_hanya_ganti_tema_tetap(self):
        """Nilai Jinja dibiarkan, tema bernilai tetap diganti, dan tidak ada atribut yang ditambah."""
        hook = self._hook()
        jinja_app = ('android:theme="{{args.android_apptheme}}'
                     '{% if not args.android_apptheme %}@android:style/Theme.NoTitleBar{% endif %}"')
        jinja_kutip = 'android:theme="{% if args.x == "y" %}@style/A{% endif %}"'      # ada tanda kutip di dalam Jinja
        sumber = ('<manifest><application ' + jinja_app + ' android:label="x">'
                  '<activity android:name="{{ args.android_entrypoint }}" {% if args.min_sdk_version >= 9 %}'
                  'android:label="y"{% endif %}></activity>'
                  '<activity android:name="org.kivy.android.PythonActivity" android:label="z"></activity>'
                  '<activity android:name="a.Izin" android:theme="@android:style/Theme.Translucent"></activity>'
                  '<activity android:name="a.Lain" ' + jinja_kutip + '></activity>'
                  '</application></manifest>')
        out = hook.patch_manifest(sumber)
        self.assertIn(jinja_app, out)
        self.assertIn(jinja_kutip, out)
        self.assertNotIn("Theme.Translucent", out)
        self.assertEqual(out.count('android:theme="@style/JadwalTheme"'), 1)
        self.assertEqual(out.count("android:theme="), sumber.count("android:theme="))     # tidak ada atribut ditambah
        self.assertEqual(hook.patch_manifest(out), out)                                   # aman dijalankan berulang

    def test_latar_webview_dipasang_di_java(self):
        hook = self._hook()
        sumber = ("public class PythonActivity extends Activity {\n"
                  "  protected void onPostExecute(String r) {\n"
                  "    PythonActivity.mActivity.mWebView = new WebView(PythonActivity.mActivity);\n"
                  "    mWebView.getSettings().setJavaScriptEnabled(true);\n  }\n}\n")
        out = hook.patch_java(sumber)
        self.assertIn("PythonActivity.mActivity.mWebView.setBackgroundColor(0xFFF6F8FC);", out)
        self.assertLess(out.index("setBackgroundColor"), out.index("getSettings"))      # segera setelah dibuat
        self.assertEqual(hook.patch_java(out), out)                                      # aman dijalankan berulang
        lokal = hook.patch_java("void f(){ WebView w = new WebView(this); w.loadUrl(u); }")
        self.assertIn("w.setBackgroundColor(0xFFF6F8FC);", lokal)
        # tidak ada / lebih dari satu pembuatan WebView: dibiarkan apa adanya (lebih baik tidak mengubah daripada salah)
        for tidak_pasti in ("class A { void f(){} }",
                            "class A { void f(){ a = new WebView(x); b = new WebView(y); } }"):
            self.assertEqual(hook.patch_java(tidak_pasti), tidak_pasti)

    def test_tombol_kembali_onkeydown_p4a_diteruskan_ke_javascript(self):
        """Bentuk asli dari log build p4a: onKeyDown(int keyCode, KeyEvent event) -> goBack() / toast bawaan."""
        hook = self._hook()
        sumber = ("public class PythonActivity extends Activity {\n"
                  "  @Override\n  public boolean onKeyDown(int keyCode, KeyEvent event) {\n"
                  "    if (keyCode == KeyEvent.KEYCODE_BACK) {\n"
                  "      mWebView.goBack();\n"
                  '      Toast.makeText(this, "Tap again to close the app", Toast.LENGTH_LONG).show();\n'
                  "      return true;\n    }\n    return super.onKeyDown(keyCode, event);\n  }\n}\n")
        out = hook.patch_back(sumber)
        self.assertIn("window.__back && window.__back()", out)
        self.assertIn("if (keyCode == android.view.KeyEvent.KEYCODE_BACK)", out)         # nama parameter ikut dari kode asli
        self.assertIn("event.getRepeatCount() == 0", out)
        self.assertLess(out.index("window.__back"), out.index("Tap again"))               # sebelum kode bawaan p4a
        self.assertLess(out.index("@Override"), out.index("onKeyDown"))                    # anotasi tidak terpisah dari metodenya
        self.assertEqual(out.count("{") - out.count("}"), sumber.count("{") - sumber.count("}"))   # kurung seimbang
        self.assertEqual(hook.patch_back(out), out)                                        # aman dijalankan berulang
        lain = hook.patch_back("class A { boolean onKeyDown(final int k, final android.view.KeyEvent ev) { return false; } }")
        self.assertIn("if (k == android.view.KeyEvent.KEYCODE_BACK)", lain)
        self.assertIn("ev.getRepeatCount()", lain)
        for tidak_pasti in ("class A { void f(){} }",
                            "class A { boolean onKeyDown(int k, KeyEvent e){return false;} boolean onKeyDown(int k, KeyEvent e){return false;} }"):
            self.assertEqual(hook.patch_back(tidak_pasti), tidak_pasti)

    def test_tombol_kembali_onbackpressed_juga_ditangani_kalau_ada(self):
        hook = self._hook()
        sumber = "public class P extends Activity {\n  @Override\n  public void onBackPressed() {\n    super.onBackPressed();\n  }\n}\n"
        out = hook.patch_back(sumber)
        self.assertIn("window.__back && window.__back()", out)
        self.assertLess(out.index("@Override"), out.index("onBackPressed"))
        self.assertEqual(out.count("{") - out.count("}"), sumber.count("{") - sumber.count("}"))
        self.assertEqual(hook.patch_back(out), out)

    def test_peringatan_tombol_kembali_menampilkan_kode_asli(self):
        import contextlib, io, tempfile
        hook = self._hook()
        with tempfile.TemporaryDirectory() as tmp:
            java = Path(tmp) / "PythonActivity.java"
            java.write_text('class P {\n  boolean onKeyDown(int k){ toast("Tap again to close the app"); }\n}\n', encoding="utf-8")
            keluar = io.StringIO()
            with contextlib.redirect_stdout(keluar):
                hook.apply_back_button(Path(tmp))
            self.assertIn("PERINGATAN", keluar.getvalue())
            self.assertIn("Tap again to close the app", keluar.getvalue())

    def test_peringatan_menampilkan_kode_asli_kalau_webview_tidak_ketemu(self):
        import contextlib, io, tempfile
        hook = self._hook()
        with tempfile.TemporaryDirectory() as tmp:
            java = Path(tmp) / "src" / "main" / "java" / "PythonActivity.java"
            java.parent.mkdir(parents=True)
            java.write_text("class P {\n  void f(){ setContentView(buatTampilan()); WebView w = buat(); }\n}\n", encoding="utf-8")
            keluar = io.StringIO()
            with contextlib.redirect_stdout(keluar):
                hook.apply_webview_background(Path(tmp))
            teks = keluar.getvalue()
            self.assertIn("PERINGATAN", teks)
            self.assertIn("setContentView(buatTampilan())", teks)

    def test_manifest_dan_resource_dipasang(self):
        import tempfile
        from types import SimpleNamespace
        hook = self._hook()
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "templates").mkdir()
            mf = dist / "templates" / "AndroidManifest.tmpl.xml"
            mf.write_text('<manifest><application android:theme="@android:style/Theme.NoTitleBar" android:label="x">'
                          '</application></manifest>', encoding="utf-8")
            hook.before_apk_build(SimpleNamespace(_dist=SimpleNamespace(dist_dir=str(dist))))
            self.assertIn('android:theme="@style/JadwalTheme"', mf.read_text(encoding="utf-8"))
            java = dist / "src" / "main" / "java" / "org" / "kivy" / "android" / "PythonActivity.java"
            java.parent.mkdir(parents=True)
            java.write_text("class P { void f(){ mWebView = new WebView(this); } }", encoding="utf-8")
            hook.before_apk_build(SimpleNamespace(_dist=SimpleNamespace(dist_dir=str(dist))))
            self.assertIn("mWebView.setBackgroundColor(0xFFF6F8FC);", java.read_text(encoding="utf-8"))
            java.write_text("class P { boolean onKeyDown(int keyCode, KeyEvent event) { return false; } }", encoding="utf-8")
            hook.before_apk_build(SimpleNamespace(_dist=SimpleNamespace(dist_dir=str(dist))))
            self.assertIn("window.__back", java.read_text(encoding="utf-8"))
            for sub in ("values", "values-v31"):
                self.assertTrue((dist / "src" / "main" / "res" / sub / "jadwal_theme.xml").is_file(), sub)


class TombolKembaliHalaman(unittest.TestCase):
    """index.html: satu tekan kembali hanya diproses sekali, dan jebakan riwayat tidak dipasang di Android WebView."""

    def setUp(self):
        self.html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    def test_tekan_ganda_diabaikan(self):
        self.assertRegex(self.html, r"function onBack\(\)\{\s*const now=Date\.now\(\);if\(now-_bl<200\)return;_bl=now;")

    def test_jebakan_riwayat_hanya_di_browser(self):
        self.assertIn("if(!/; wv\\)/.test(navigator.userAgent)){history.replaceState", self.html)


if __name__ == "__main__":
    unittest.main()
