"""Tes bagian Android yang bisa dijalankan tanpa HP: pembersih riwayat WebView dan hook p4a."""
import importlib.util
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

    def test_splash_sistem_f6f8fc(self):
        xml = (ROOT / "android_res" / "values-v31" / "jadwal_theme.xml").read_text(encoding="utf-8")
        self.assertRegex(xml, r'(?i)windowSplashScreenBackground">#F6F8FC<')
        self.assertRegex(xml, r'(?i)windowBackground">#F6F8FC<')
        lama = (ROOT / "android_res" / "values" / "jadwal_theme.xml").read_text(encoding="utf-8")
        self.assertRegex(lama, r'(?i)windowBackground">#F6F8FC<')   # Android < 12: latar jendela = splash
        self.assertIn("forceDarkAllowed", xml)
        self.assertIn("windowSplashScreenAnimatedIcon\">@android:color/transparent<", xml)


class HookTema(unittest.TestCase):
    def test_manifest_dan_resource_dipaksa_tema(self):
        import tempfile
        from types import SimpleNamespace
        spec = importlib.util.spec_from_file_location("p4a_hook2", ROOT / "p4a" / "hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "templates").mkdir()
            mf = dist / "templates" / "AndroidManifest.tmpl.xml"
            mf.write_text('<manifest><application android:theme="{{args.theme}}" android:label="x">'
                          '<activity android:name="org.kivy.android.PythonActivity" android:label="y">'
                          '</activity></application></manifest>', encoding="utf-8")
            hook.before_apk_build(SimpleNamespace(_dist=SimpleNamespace(dist_dir=str(dist))))
            out = mf.read_text(encoding="utf-8")
            self.assertEqual(out.count('android:theme="@style/JadwalTheme"'), 2)
            self.assertNotIn("{{args.theme}}", out)
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
