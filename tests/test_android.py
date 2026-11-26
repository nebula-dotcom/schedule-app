import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from jadwal import droid
from jadwal import settings as cfg

# Folder proyek
ROOT = Path(__file__).resolve().parent.parent


# WebView palsu untuk tes droid.py
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


# Tes perapian riwayat WebView
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


# Tes hook p4a: layar loading
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


# Tes tema dan latar WebView
class TemaLatar(unittest.TestCase):
    def test_tema_dan_resource_terpasang(self):
        spec = (ROOT / "buildozer.spec").read_text(encoding="utf-8")
        self.assertRegex(spec, r"(?m)^android\.apptheme\s*=\s*@style/JadwalTheme\s*$")
        for sub in ("values", "values-v31"):
            self.assertIn(f"android_res/{sub}/jadwal_theme.xml:{sub}/jadwal_theme.xml", spec)
            self.assertTrue((ROOT / "android_res" / sub / "jadwal_theme.xml").is_file())

    def test_resource_splash_terdaftar(self):
        spec = (ROOT / "buildozer.spec").read_text(encoding="utf-8")
        self.assertIn("android_res/values-v31/jadwal_splash.xml:values-v31/jadwal_splash.xml", spec)
        self.assertTrue((ROOT / "android_res" / "values-v31" / "jadwal_splash.xml").is_file())

    def test_splash_sistem_tanpa_ikon_dan_force_dark(self):
        xml = (ROOT / "android_res" / "values-v31" / "jadwal_theme.xml").read_text(encoding="utf-8")
        self.assertIn("forceDarkAllowed", xml)
        self.assertIn("windowSplashScreenAnimatedIcon\">@android:color/transparent<", xml)


# Tes warna seragam Android dan web
class WarnaSeragam(unittest.TestCase):

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
        self.terang = self._cari(r"\[data-theme=light\]\{--bg:" + self.HEX, self._baca("web", "index.html"),
                                 "web/index.html (--bg tema terang)")

    def test_loading_html(self):
        warna = self._cari(r"html,body\{[^}]*background:" + self.HEX, self._baca("web", "loading.html"), "web/loading.html")
        self.assertEqual(warna, self.dasar, "web/loading.html")

    def test_loading_bawaan_hook(self):
        spec = importlib.util.spec_from_file_location("p4a_hook3", ROOT / "p4a" / "hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        warna = self._cari(r"html,body\{[^}]*background:" + self.HEX, hook.render_loading(), "p4a/hook.py (LOADING_HTML)")
        self.assertEqual(warna, self.dasar, "p4a/hook.py (LOADING_HTML)")
        html = hook.render_loading()
        terang = self._cari(r"html\.t-light,html\.t-light body\{[^}]*background:" + self.HEX, html, "p4a/hook.py (LOADING_HTML terang)")
        self.assertEqual(terang, self.terang, "p4a/hook.py (LOADING_HTML terang)")
        self.assertIn("JadwalTema/light", html)
        self.assertIn("t-light", html)

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
        self.assertEqual("#" + hook.LATAR_JAVA_TERANG[4:].lower(), self.terang, "p4a/hook.py (LATAR_JAVA_TERANG)")
        self.assertTrue(hook.LATAR_JAVA_TERANG.upper().startswith("0XFF"), "latar WebView terang harus tidak transparan")
        self.assertEqual(droid.LATAR_WEBVIEW_TERANG.lower(), self.terang, "jadwal/droid.py (LATAR_WEBVIEW_TERANG)")

    def test_presplash_transparan(self):
        """Layar pembuka p4a tidak boleh berwarna sendiri: warna latar datang dari jendela (hook, sesuai tema tersimpan)."""
        warna = self._cari(r"(?m)^android\.presplash_color\s*=\s*(#[0-9a-fA-F]{8})", self._baca("buildozer.spec"),
                           "buildozer.spec (android.presplash_color)")
        self.assertEqual(warna, "#00000000", "buildozer.spec (android.presplash_color)")
        from PIL import Image
        gambar = Image.open(ROOT / "assets" / "presplash.png").convert("RGBA")
        self.assertLessEqual(gambar.width * gambar.height, 64, "presplash.png dibuat sekecil mungkin")
        for x in range(gambar.width):
            for y in range(gambar.height):
                self.assertEqual(gambar.getpixel((x, y))[3], 0, f"assets/presplash.png ({x},{y}) harus transparan")

    def test_splash_sistem_per_tema(self):
        import xml.etree.ElementTree as ET
        akar = ET.parse(ROOT / "android_res" / "values-v31" / "jadwal_splash.xml").getroot()
        warna = {}
        for gaya in akar.iter("style"):
            for butir in gaya.iter("item"):
                if butir.get("name") == "android:windowSplashScreenBackground":
                    warna[gaya.get("name")] = butir.text.strip().lower()
        self.assertEqual(warna.get(droid.SPLASH_GELAP), self.dasar, "gaya splash gelap")
        self.assertEqual(warna.get(droid.SPLASH_TERANG), self.terang, "gaya splash terang")
        self.assertEqual(droid.nama_splash("light"), droid.SPLASH_TERANG)
        for lain in ("dark", "", "ngawur"):
            self.assertEqual(droid.nama_splash(lain), droid.SPLASH_GELAP, lain)


class HookTema(unittest.TestCase):
    @staticmethod
    def _hook():
        spec = importlib.util.spec_from_file_location("p4a_hook2", ROOT / "p4a" / "hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        return hook

    def test_manifest_hanya_ganti_tema_tetap(self):
        hook = self._hook()
        jinja_app = ('android:theme="{{args.android_apptheme}}'
                     '{% if not args.android_apptheme %}@android:style/Theme.NoTitleBar{% endif %}"')
        jinja_kutip = 'android:theme="{% if args.x == "y" %}@style/A{% endif %}"'
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
        self.assertEqual(out.count("android:theme="), sumber.count("android:theme="))
        self.assertEqual(hook.patch_manifest(out), out)

    def test_latar_webview_dipasang_di_java(self):
        hook = self._hook()
        sumber = ("public class PythonActivity extends Activity {\n"
                  "  protected void onPostExecute(String r) {\n"
                  "    PythonActivity.mActivity.mWebView = new WebView(PythonActivity.mActivity);\n"
                  "    mWebView.getSettings().setJavaScriptEnabled(true);\n  }\n}\n")
        out = hook.patch_java(sumber)
        self.assertIn("PythonActivity.mActivity.mWebView.setBackgroundColor(__jc);", out)
        self.assertIn("__jt ? 0xFFF6F8FC : 0xFF121212", out)
        self.assertIn('"data/theme.txt"', out)
        self.assertIn("JadwalTema/light", out)
        self.assertLess(out.index("setBackgroundColor"), out.index("getSettings"))
        self.assertEqual(hook.patch_java(out), out)
        lokal = hook.patch_java("void f(){ WebView w = new WebView(this); w.loadUrl(u); }")
        self.assertIn("w.setBackgroundColor(__jc);", lokal)
        for tidak_pasti in ("class A { void f(){} }",
                            "class A { void f(){ a = new WebView(x); b = new WebView(y); } }"):
            self.assertEqual(hook.patch_java(tidak_pasti), tidak_pasti)

    def test_latar_jendela_awal_dipasang_di_oncreate(self):
        hook = self._hook()
        sumber = ("public class PythonActivity extends Activity {\n"
                  "  @Override\n  protected void onCreate(Bundle savedInstanceState) {\n"
                  "    super.onCreate(savedInstanceState);\n    showLoadingScreen();\n  }\n}\n")
        out = hook.patch_awal(sumber)
        self.assertIn("data/theme.txt", out)
        self.assertIn("__jat ? 0xFFF6F8FC : 0xFF121212", out)
        self.assertLess(out.index("setBackgroundDrawable"), out.index("super.onCreate"))      # paling awal
        self.assertLess(out.index("@Override"), out.index("onCreate"))
        self.assertEqual(out.count("{") - out.count("}"), sumber.count("{") - sumber.count("}"))
        self.assertEqual(hook.patch_awal(out), out)                                          # aman diulang
        for tidak_pasti in ("class A { void f(){} }",
                            "class A { void onCreate(Bundle a){} void onCreate(Bundle b){} }"):
            self.assertEqual(hook.patch_awal(tidak_pasti), tidak_pasti)

    def test_latar_jendela_awal_ikut_before_apk_build_dan_ada_peringatan(self):
        import contextlib, io, tempfile
        from types import SimpleNamespace
        hook = self._hook()
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "templates").mkdir()
            java = dist / "src" / "main" / "java" / "org" / "kivy" / "android" / "PythonActivity.java"
            java.parent.mkdir(parents=True)
            java.write_text("class P { void onCreate(Bundle b) { super.onCreate(b); } }", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                hook.before_apk_build(SimpleNamespace(_dist=SimpleNamespace(dist_dir=str(dist))))
            self.assertIn("setBackgroundDrawable", java.read_text(encoding="utf-8"))
            java.write_text("class P { void mulai() { } }", encoding="utf-8")
            keluar = io.StringIO()
            with contextlib.redirect_stdout(keluar):
                hook.apply_early_background(dist)
            self.assertIn("PERINGATAN", keluar.getvalue())

    def test_lapisan_penutup_dipasang_di_java(self):
        hook = self._hook()
        out = hook.patch_java(self.JAVA_P)
        # kotak polos berwarna tema di decor view (tidak hilang saat p4a memanggil setContentView)
        self.assertIn("getWindow().getDecorView()", out)
        self.assertIn("__jo.setBackgroundColor(__jk);", out)
        self.assertIn("final int __jk = __jc;", out)
        # dilepas saat halaman memberi sinyal, dengan batas waktu agar tidak menutup selamanya
        self.assertIn(f'}}, "{hook.SPLASH_JS}");', out)
        self.assertIn("@android.webkit.JavascriptInterface public void ready()", out)
        self.assertIn(f"postDelayed(__jx, {hook.SPLASH_MAKS_MS});", out)
        self.assertGreater(hook.SPLASH_MAKS_MS, 0)
        # latar WebView dipasang ulang setelah kode p4a sendiri selesai
        self.assertIn("__jh.post(new Runnable() { public void run() { __jv.setBackgroundColor(__jk); } });", out)
        # satu kali saja
        self.assertEqual(out.count("addJavascriptInterface"), 1)
        self.assertEqual(hook.patch_java(out), out)

    def test_halaman_loading_memberi_sinyal_ke_java(self):
        hook = self._hook()
        for nama, html in (("p4a/hook.py (LOADING_HTML)", hook.render_loading()),
                           ("web/loading.html", (ROOT / "web" / "loading.html").read_text(encoding="utf-8"))):
            self.assertIn(f"{hook.SPLASH_JS}.ready()", html, nama)
            self.assertIn("requestAnimationFrame", html, nama)
            self.assertIn(f"window.{hook.SPLASH_JS}", html, nama)

    def test_tombol_kembali_onkeydown_p4a_diteruskan_ke_javascript(self):
        hook = self._hook()
        sumber = ("public class PythonActivity extends Activity {\n"
                  "  @Override\n  public boolean onKeyDown(int keyCode, KeyEvent event) {\n"
                  "    if (keyCode == KeyEvent.KEYCODE_BACK) {\n"
                  "      mWebView.goBack();\n"
                  '      Toast.makeText(this, "Tap again to close the app", Toast.LENGTH_LONG).show();\n'
                  "      return true;\n    }\n    return super.onKeyDown(keyCode, event);\n  }\n}\n")
        out = hook.patch_back(sumber)
        self.assertIn("window.__back && window.__back()", out)
        self.assertIn("if (keyCode == android.view.KeyEvent.KEYCODE_BACK)", out)
        self.assertIn("event.getRepeatCount() == 0", out)
        self.assertLess(out.index("window.__back"), out.index("Tap again"))
        self.assertLess(out.index("@Override"), out.index("onKeyDown"))
        self.assertEqual(out.count("{") - out.count("}"), sumber.count("{") - sumber.count("}"))
        self.assertEqual(hook.patch_back(out), out)
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
            self.assertIn("mWebView.setBackgroundColor(__jc);", java.read_text(encoding="utf-8"))
            java.write_text("class P { boolean onKeyDown(int keyCode, KeyEvent event) { return false; } }", encoding="utf-8")
            hook.before_apk_build(SimpleNamespace(_dist=SimpleNamespace(dist_dir=str(dist))))
            self.assertIn("window.__back", java.read_text(encoding="utf-8"))
            for sub in ("values", "values-v31"):
                self.assertTrue((dist / "src" / "main" / "res" / sub / "jadwal_theme.xml").is_file(), sub)


    JAVA_P = ("public class PythonActivity extends Activity {\n"
              "  protected void onPostExecute(String r) {\n"
              "    PythonActivity.mActivity.mWebView = new WebView(PythonActivity.mActivity);\n"
              "    mWebView.getSettings().setJavaScriptEnabled(true);\n  }\n}\n")

    def test_pemilih_file_dipasang_di_java(self):
        hook = self._hook()
        out = hook.patch_file_chooser(self.JAVA_P)
        self.assertIn("PythonActivity.mActivity.mWebView.setWebChromeClient(new android.webkit.WebChromeClient()", out)
        self.assertIn("onShowFileChooser", out)
        self.assertIn("org.jadwal.FilePickActivity.start(__w.getContext(), __cb)", out)
        self.assertLess(out.index("setWebChromeClient"), out.index("getSettings"))
        self.assertEqual(hook.patch_file_chooser(out), out)
        self.assertIn("w.setWebChromeClient(", hook.patch_file_chooser("void f(){ WebView w = new WebView(this); }"))
        self.assertEqual(out.count("{"), out.count("}"))
        self.assertEqual(out.count("("), out.count(")"))

    def test_pemilih_file_tidak_mengubah_kalau_tidak_pasti(self):
        hook = self._hook()
        for tidak_pasti in ("class A { void f(){} }",
                            "class A { void f(){ a = new WebView(x); b = new WebView(y); } }",
                            "class A { void f(){ w = new WebView(x); w.setWebChromeClient(c); } }"):
            self.assertEqual(hook.patch_file_chooser(tidak_pasti), tidak_pasti)

    def test_patch_latar_dan_pemilih_file_bisa_dipakai_bersama_dalam_urutan_apa_pun(self):
        hook = self._hook()
        a = hook.patch_file_chooser(hook.patch_java(self.JAVA_P))
        b = hook.patch_java(hook.patch_file_chooser(self.JAVA_P))
        for out in (a, b):
            self.assertIn("setBackgroundColor(__jc);", out)
            self.assertIn("onShowFileChooser", out)
            self.assertEqual(out.count("{"), out.count("}"))
            self.assertEqual(hook.patch_file_chooser(hook.patch_java(out)), out)

    def test_kelas_filepickactivity_lengkap(self):
        hook = self._hook()
        j = hook.FILE_PICK_ACTIVITY
        for harus in ("package org.jadwal;", "public class FilePickActivity extends Activity", "ACTION_GET_CONTENT",
                      "CATEGORY_OPENABLE", "FileChooserParams.parseResult", "startActivityForResult",
                      "public static boolean start(Context ctx, ValueCallback<Uri[]> cb)"):
            self.assertIn(harus, j)
        self.assertEqual(j.count("{"), j.count("}"))
        self.assertEqual(j.count("("), j.count(")"))
        self.assertGreaterEqual(j.count("deliver("), 5)

    def test_manifest_mendaftarkan_activity_sekali(self):
        hook = self._hook()
        mf = '<manifest><application android:label="x"><activity android:name="a"/></application></manifest>'
        out = hook.patch_manifest_file_picker(mf)
        self.assertEqual(out.count("org.jadwal.FilePickActivity"), 1)
        self.assertIn("Theme.Translucent.NoTitleBar", out)
        self.assertLess(out.index("org.jadwal.FilePickActivity"), out.index("</application>"))
        self.assertEqual(hook.patch_manifest_file_picker(out), out)
        for tidak_pasti in ("<manifest/>", "<application></application><application></application>"):
            self.assertEqual(hook.patch_manifest_file_picker(tidak_pasti), tidak_pasti)

    def test_tema_transparan_filepickactivity_tidak_ditimpa_tema_aplikasi(self):
        hook = self._hook()
        mf = hook.patch_manifest_file_picker('<application android:theme="@android:style/Theme.NoTitleBar"></application>')
        out = hook.patch_manifest(mf)
        self.assertIn('android:theme="@style/JadwalTheme"', out)
        self.assertIn("Theme.Translucent.NoTitleBar", out)
        self.assertEqual(hook.patch_manifest(out), out)

    def test_before_apk_build_memasang_pemilih_file_lengkap_dan_aman_diulang(self):
        import contextlib
        import io
        import tempfile
        from types import SimpleNamespace
        hook = self._hook()
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            mf = dist / "src" / "main" / "AndroidManifest.xml"
            java = dist / "src" / "main" / "java" / "org" / "kivy" / "android" / "PythonActivity.java"
            mf.parent.mkdir(parents=True)
            java.parent.mkdir(parents=True)
            mf.write_text('<manifest><application android:theme="@android:style/Theme.NoTitleBar"></application></manifest>',
                          encoding="utf-8")
            java.write_text(self.JAVA_P, encoding="utf-8")
            jalankan = lambda: hook.before_apk_build(SimpleNamespace(_dist=SimpleNamespace(dist_dir=str(dist))))
            with contextlib.redirect_stdout(io.StringIO()):
                jalankan()
                jalankan()
            kelas = dist / "src" / "main" / "java" / "org" / "jadwal" / "FilePickActivity.java"
            self.assertTrue(kelas.is_file())
            self.assertEqual(kelas.read_text(encoding="utf-8"), hook.FILE_PICK_ACTIVITY)
            teks_java = java.read_text(encoding="utf-8")
            self.assertEqual(teks_java.count("onShowFileChooser"), 1)
            teks_mf = mf.read_text(encoding="utf-8")
            self.assertEqual(teks_mf.count("org.jadwal.FilePickActivity"), 1)
            self.assertIn("Theme.Translucent.NoTitleBar", teks_mf)
            self.assertIn('android:theme="@style/JadwalTheme"', teks_mf)

    def test_pemilih_file_tidak_dipasang_dan_ada_peringatan_kalau_webview_tidak_ketemu(self):
        import contextlib
        import io
        import tempfile
        hook = self._hook()
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            java = dist / "src" / "main" / "java" / "org" / "kivy" / "android" / "PythonActivity.java"
            mf = dist / "AndroidManifest.xml"
            java.parent.mkdir(parents=True)
            java.write_text("class P { void f(){ WebView w = buat(); } }", encoding="utf-8")
            mf.write_text("<manifest><application></application></manifest>", encoding="utf-8")
            keluar = io.StringIO()
            with contextlib.redirect_stdout(keluar):
                hook.apply_file_chooser(dist)
            self.assertIn("PERINGATAN: pemilih file", keluar.getvalue())
            self.assertIn("WebView w = buat();", keluar.getvalue())
            self.assertFalse((dist / "src" / "main" / "java" / "org" / "jadwal").exists())
            self.assertNotIn("FilePickActivity", mf.read_text(encoding="utf-8"))


# Tes tombol kembali di halaman web
class TombolKembaliHalaman(unittest.TestCase):

    def setUp(self):
        self.html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    def test_tekan_ganda_diabaikan(self):
        self.assertRegex(self.html, r"function onBack\(\)\{\s*const now=Date\.now\(\);if\(now-_bl<200\)return;_bl=now;")

    def test_jebakan_riwayat_hanya_di_browser(self):
        self.assertIn("if(!/; wv\\)/.test(navigator.userAgent)){history.replaceState", self.html)


# Tes animasi tekan tombol: kilau menyapu
class AnimasiTekan(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    def test_memakai_kilau_menyapu_bukan_riak_dari_titik_sentuh(self):
        self.assertIn("function prSweep(el)", self.html)
        self.assertIn("@keyframes sw{", self.html)
        self.assertNotIn("prRipple", self.html)
        self.assertNotIn("Math.hypot(x-r.left", self.html)

    def test_skala_tekan_seragam_dan_tombol_x_tetap_berputar(self):
        self.assertIn("button,a[onclick]{--ps:.97;", self.html)
        self.assertIn(".spx.pr svg{transform:rotate(45deg)", self.html)


# Tema tersimpan dipakai bersama server dan droid
class TemaTersimpan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(cfg, "DATA_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _simpan(self, isi):
        (Path(self.tmp.name) / "theme.txt").write_text(isi, encoding="utf-8")

    def test_bawaan_gelap(self):
        self.assertEqual(cfg.read_theme(), "dark")
        self.assertEqual(droid.latar_tema(), droid.LATAR_WEBVIEW)

    def test_terang_dan_nilai_asing(self):
        self._simpan("light\n")
        self.assertEqual(cfg.read_theme(), "light")
        self.assertEqual(droid.latar_tema(), droid.LATAR_WEBVIEW_TERANG)
        for isi in ("dark", "", "LIGHT", "ngawur"):
            self._simpan(isi)
            self.assertEqual(cfg.read_theme(), "dark", isi)
            self.assertEqual(droid.latar_tema(), droid.LATAR_WEBVIEW, isi)

    def test_server_memakai_fungsi_yang_sama(self):
        from jadwal import server
        self._simpan("light")
        self.assertEqual(server.read_theme(), "light")


# Penerapan latar WebView dan jendela sesuai tema
class LatarSesuaiTema(unittest.TestCase):
    class Warna:
        @staticmethod
        def parseColor(teks):
            return int(teks[1:], 16)

    class Jendela:
        def __init__(self):
            self.latar = None

        def setBackgroundDrawable(self, d):
            self.latar = d.nilai

    class WebViewLatar:
        def __init__(self):
            self.latar, self.dipasang = None, 0

        def setBackgroundColor(self, nilai):
            self.latar, self.dipasang = nilai, self.dipasang + 1

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.object(cfg, "DATA_DIR", Path(self.tmp.name)),
                  mock.patch.object(droid, "_latar", [None])):
            p.start()
            self.addCleanup(p.stop)

        jendela = self.jendela = self.Jendela()

        class ColorDrawable:
            def __init__(self, nilai):
                self.nilai = nilai

        kelas = {"android.graphics.Color": self.Warna, "android.graphics.drawable.ColorDrawable": ColorDrawable}
        palsu = types.SimpleNamespace(autoclass=lambda nama: kelas[nama])
        aktivitas = types.SimpleNamespace(getWindow=lambda: jendela)
        for p in (mock.patch.dict(sys.modules, {"jnius": palsu}), mock.patch.object(droid, "_activity", lambda: aktivitas)):
            p.start()
            self.addCleanup(p.stop)

    def _tema(self, nama):
        (Path(self.tmp.name) / "theme.txt").write_text(nama, encoding="utf-8")

    def test_webview_dan_jendela_ikut_tema(self):
        w = self.WebViewLatar()
        droid._latar_tema(w, paksa=True)
        self.assertEqual((w.latar, self.jendela.latar), (0x121212, 0x121212))
        self._tema("light")
        droid._latar_tema(w)
        self.assertEqual((w.latar, self.jendela.latar), (0xF6F8FC, 0xF6F8FC))

    def test_tidak_diulang_kalau_tema_sama(self):
        w = self.WebViewLatar()
        droid._latar_tema(w, paksa=True)
        droid._latar_tema(w)
        droid._latar_tema(w)
        self.assertEqual(w.dipasang, 1)

    def test_webview_baru_selalu_dipasang_lagi(self):
        droid._latar_tema(self.WebViewLatar(), paksa=True)
        w2 = self.WebViewLatar()
        droid._latar_tema(w2, paksa=True)
        self.assertEqual(w2.dipasang, 1)


# Build CI harus memakai dist baru agar patch hook terbaru benar-benar masuk APK
class DistSelaluBaru(unittest.TestCase):
    def test_dist_dari_cache_dihapus_sebelum_build(self):
        """Patch hook dilewati bila penandanya sudah ada, jadi dist lama dari cache tidak boleh dipakai ulang."""
        alur = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
        hapus = "rm -rf .buildozer/android/platform/build-*/dists"
        self.assertIn(hapus, alur)
        self.assertLess(alur.index("actions/cache@"), alur.index(hapus))
        self.assertLess(alur.index(hapus), alur.index("buildozer -v android release"))


# Patch Java hasil hook harus bisa dikompilasi (dilewati bila javac tidak ada)
@unittest.skipUnless(shutil.which("javac"), "javac tidak tersedia")
class PatchJavaTerkompilasi(unittest.TestCase):
    STUB = {
        "android/content/Context.java": "package android.content; public class Context { public java.io.File getFilesDir(){return null;} }",
        "android/app/Activity.java": "package android.app; public class Activity extends android.content.Context "
                                     "{ public android.view.Window getWindow(){return null;} "
                                     "protected void onCreate(android.os.Bundle b){} }",
        "android/os/Bundle.java": "package android.os; public class Bundle {}",
        "android/view/Window.java": "package android.view; public class Window "
                                    "{ public View getDecorView(){return null;} "
                                    "public void setBackgroundDrawable(android.graphics.drawable.Drawable d){} }",
        "android/view/ViewParent.java": "package android.view; public interface ViewParent {}",
        "android/view/View.java": "package android.view; public class View { public View(android.content.Context c){} "
                                  "public android.content.Context getContext(){return null;} public void setBackgroundColor(int c){} "
                                  "public void setClickable(boolean b){} public ViewParent getParent(){return null;} }",
        "android/view/ViewGroup.java": "package android.view; public class ViewGroup extends View implements ViewParent "
                                       "{ public ViewGroup(android.content.Context c){super(c);} "
                                       "public static class LayoutParams { public LayoutParams(int w,int h){} } "
                                       "public void addView(View v, LayoutParams p){} public void removeView(View v){} }",
        "android/widget/FrameLayout.java": "package android.widget; public class FrameLayout extends android.view.ViewGroup "
                                           "{ public FrameLayout(android.content.Context c){super(c);} "
                                           "public static class LayoutParams extends android.view.ViewGroup.LayoutParams "
                                           "{ public LayoutParams(int w,int h){super(w,h);} } }",
        "android/os/Looper.java": "package android.os; public class Looper { public static Looper getMainLooper(){return null;} }",
        "android/os/Handler.java": "package android.os; public class Handler { public Handler(Looper l){} "
                                   "public boolean post(Runnable r){return true;} "
                                   "public boolean postDelayed(Runnable r,long ms){return true;} }",
        "android/webkit/JavascriptInterface.java": "package android.webkit; import java.lang.annotation.*; "
                                                   "@Retention(RetentionPolicy.RUNTIME) @Target(ElementType.METHOD) "
                                                   "public @interface JavascriptInterface {}",
        "android/graphics/drawable/Drawable.java": "package android.graphics.drawable; public class Drawable {}",
        "android/graphics/drawable/ColorDrawable.java": "package android.graphics.drawable; "
                                                        "public class ColorDrawable extends Drawable { public ColorDrawable(int c){} }",
        "android/webkit/WebSettings.java": "package android.webkit; public class WebSettings { public String getUserAgentString(){return \"\";} "
                                           "public void setUserAgentString(String s){} public void setJavaScriptEnabled(boolean b){} }",
        "android/webkit/WebView.java": "package android.webkit; public class WebView extends android.view.ViewGroup "
                                       "{ public WebView(android.content.Context c){super(c);} "
                                       "public WebSettings getSettings(){return null;} public void loadUrl(String u){} "
                                       "public void addJavascriptInterface(Object o, String n){} }",
    }
    ASLI = ("package org.kivy.android;\nimport android.app.Activity;\nimport android.webkit.WebView;\n"
            "public class PythonActivity extends Activity {\n  public static PythonActivity mActivity; public WebView mWebView;\n"
            "  private class UnpackFilesTask {\n    protected void onPostExecute(String r) {\n"
            "      PythonActivity.mActivity.mWebView = new WebView(PythonActivity.mActivity);\n"
            "      PythonActivity.mActivity.mWebView.getSettings().setJavaScriptEnabled(true);\n    }\n  }\n}\n")

    def test_kode_java_hasil_patch_bisa_dikompilasi(self):
        spec = importlib.util.spec_from_file_location("p4a_hook5", ROOT / "p4a" / "hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for nama, isi in self.STUB.items():
                (tmp / nama).parent.mkdir(parents=True, exist_ok=True)
                (tmp / nama).write_text(isi, encoding="utf-8")
            sumber = tmp / "org" / "kivy" / "android" / "PythonActivity.java"
            sumber.parent.mkdir(parents=True)
            sumber.write_text(hook.patch_java(self.ASLI), encoding="utf-8")
            hasil = subprocess.run(["javac", "-Xlint:all", "-d", str(tmp / "out"), *map(str, tmp.rglob("*.java"))],
                                   capture_output=True, text=True)
            self.assertEqual(hasil.returncode, 0, hasil.stderr)
            self.assertNotIn("warning", hasil.stderr.lower(), hasil.stderr)

    def test_latar_jendela_awal_bisa_dikompilasi(self):
        spec = importlib.util.spec_from_file_location("p4a_hook6", ROOT / "p4a" / "hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        asli = ("package org.kivy.android;\nimport android.app.Activity;\nimport android.os.Bundle;\n"
                "public class PythonActivity extends Activity {\n  @Override\n"
                "  protected void onCreate(Bundle savedInstanceState) {\n    super.onCreate(savedInstanceState);\n  }\n}\n")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for nama, isi in self.STUB.items():
                (tmp / nama).parent.mkdir(parents=True, exist_ok=True)
                (tmp / nama).write_text(isi, encoding="utf-8")
            sumber = tmp / "org" / "kivy" / "android" / "PythonActivity.java"
            sumber.parent.mkdir(parents=True)
            sumber.write_text(hook.patch_awal(asli), encoding="utf-8")
            hasil = subprocess.run(["javac", "-Xlint:all", "-d", str(tmp / "out"), *map(str, tmp.rglob("*.java"))],
                                   capture_output=True, text=True)
            self.assertEqual(hasil.returncode, 0, hasil.stderr)
            self.assertNotIn("warning", hasil.stderr.lower(), hasil.stderr)


if __name__ == "__main__":
    unittest.main()


# Tes pekerjaan Java di thread utama
class PekerjaanJavaDiThreadUtama(unittest.TestCase):

    def setUp(self):
        self.hook_thread = []
        self.patches = [mock.patch.object(droid, "ON_ANDROID", True),
                        mock.patch.object(droid, "_activity", lambda: None),
                        mock.patch.object(droid, "_hook_once", lambda: self.hook_thread.append(threading.get_ident()) or True)]
        for p in self.patches:
            p.start()
        self.stop = threading.Event()
        self.loop = threading.Thread(target=droid.main_loop, args=(self.stop,), daemon=True)
        self.loop.start()
        t0 = time.time()
        while droid._main_id[0] is None and time.time() - t0 < 5:
            time.sleep(0.01)

    def tearDown(self):
        self.stop.set()
        self.loop.join(5)
        for p in self.patches:
            p.stop()

    def dari_thread_lain(self, fn):
        out = {}

        def kerja():
            try:
                out["hasil"] = fn()
            except BaseException as err:
                out["galat"] = err
        t = threading.Thread(target=kerja)
        t.start()
        t.join(10)
        return out.get("hasil"), out.get("galat")

    def test_pekerjaan_dari_thread_lain_berjalan_di_thread_utama(self):
        hasil, galat = self.dari_thread_lain(lambda: droid.run_on_main(threading.get_ident))
        self.assertIsNone(galat)
        self.assertEqual(hasil, self.loop.ident)
        self.assertNotEqual(hasil, threading.get_ident())

    def test_galat_dikirim_balik_ke_pemanggil(self):
        def gagal():
            raise ValueError("galat uji")
        _, galat = self.dari_thread_lain(lambda: droid.run_on_main(gagal))
        self.assertIsInstance(galat, ValueError)
        self.assertEqual(str(galat), "galat uji")
        hasil, galat = self.dari_thread_lain(lambda: droid.run_on_main(lambda: 7))
        self.assertEqual((hasil, galat), (7, None))

    def test_simpan_ke_downloads_dititipkan_ke_thread_utama(self):
        tercatat = []
        with mock.patch.object(droid, "_save_to_downloads",
                               lambda *a: tercatat.append((threading.get_ident(), a))):
            _, galat = self.dari_thread_lain(lambda: droid.save_to_downloads("a.xlsx", b"PK", "m/x"))
        self.assertIsNone(galat)
        self.assertEqual(tercatat, [(self.loop.ident, ("a.xlsx", b"PK", "m/x"))])

    def test_keluar_menutup_activity_dari_thread_utama(self):
        tercatat = []
        with mock.patch.object(droid, "_finish", lambda: tercatat.append(threading.get_ident())), \
                mock.patch.object(droid.os, "_exit") as keluar:
            droid.exit_app(delay=0)
            t0 = time.time()
            while not keluar.called and time.time() - t0 < 5:
                time.sleep(0.02)
            keluar.assert_called_once_with(0)
        self.assertEqual(tercatat, [self.loop.ident])

    def test_tombol_kembali_dipasang_dari_thread_utama(self):
        t0 = time.time()
        while not self.hook_thread and time.time() - t0 < 5:
            time.sleep(0.02)
        self.assertIn(self.loop.ident, self.hook_thread)

    def test_di_luar_android_langsung_dijalankan(self):
        with mock.patch.object(droid, "ON_ANDROID", False):
            hasil, _ = self.dari_thread_lain(lambda: droid.run_on_main(threading.get_ident))
        self.assertNotEqual(hasil, self.loop.ident)


# Tes main.py mode Android
class MainPyAndroid(unittest.TestCase):
    def test_server_di_thread_sendiri_dan_java_di_thread_utama(self):
        kode = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("target=server.serve_forever", kode)
        self.assertIn("droid.main_loop()", kode)
        self.assertNotIn("install_back_hook", kode)


# Tes popup file tersimpan
class PopupSimpan(unittest.TestCase):

    def setUp(self):
        self.html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    def test_popup_isi_dan_tombol_tutup(self):
        self.assertIn("function savedPop(title,name){open(`", self.html)
        self.assertIn("Tersimpan di folder Download: <b>${esc(name)}</b>", self.html)
        self.assertRegex(self.html, r'class="spx"[^>]*aria-label="Tutup"[^>]*onclick="closeSheet\(\)"')
        self.assertIn("x:'<path", self.html)

    def test_judul_sesuai_jenis_file(self):
        self.assertIn("const EXP={xlsx:'Download Excel',png:'Save PNG',pdf:'PDF - A4'};", self.html)
        self.assertIn("savedPop(EXP[kind],j.saved)", self.html)

    def test_toast_lama_tidak_dipakai_untuk_hasil_simpan(self):
        self.assertNotIn("toast('Tersimpan", self.html)

    def test_tombol_di_atribut_tidak_memakai_nama_bawaan_document(self):
        bentrok = re.findall(r'\bon[a-z]+=\\?"[^"]*?(?<![\w.$])(close|open|write|writeln)\(', self.html)
        self.assertEqual(bentrok, [], "pakai closeSheet() / nama lain di atribut onclick")
        self.assertIn("function closeSheet(){", self.html)
        self.assertIn("function close(){closeSheet()}", self.html)


# Splash sistem ikut tema tersimpan (Android 13+)
class SplashSesuaiTema(unittest.TestCase):
    class Aktivitas:
        def __init__(self):
            self.dipilih, self.dicari = [], []

        def getResources(self):
            return self

        def getIdentifier(self, nama, jenis, paket):
            self.dicari.append((nama, jenis, paket))
            return 77 if nama in (droid.SPLASH_GELAP, droid.SPLASH_TERANG) else 0

        def getPackageName(self):
            return "org.contoh"

        def getSplashScreen(self):
            return self

        def setSplashScreenTheme(self, res_id):
            self.dipilih.append(res_id)

    def _jalankan(self, sdk, tema):
        akt = self.Aktivitas()
        palsu = types.SimpleNamespace(autoclass=lambda nama: types.SimpleNamespace(SDK_INT=sdk))
        with mock.patch.dict(sys.modules, {"jnius": palsu}), mock.patch.object(droid, "_activity", lambda: akt):
            droid._terapkan_splash(droid.nama_splash(tema))
        return akt

    def test_terang_dan_gelap_memilih_gaya_masing_masing(self):
        for tema, nama in (("light", droid.SPLASH_TERANG), ("dark", droid.SPLASH_GELAP)):
            akt = self._jalankan(33, tema)
            self.assertEqual(akt.dicari, [(nama, "style", "org.contoh")], tema)
            self.assertEqual(akt.dipilih, [77], tema)

    def test_android_di_bawah_13_dilewati(self):
        self.assertEqual(self._jalankan(32, "light").dipilih, [])

    def test_gaya_tidak_ada_tidak_dipakai(self):
        akt = self.Aktivitas()
        akt.getIdentifier = lambda nama, jenis, paket: 0
        palsu = types.SimpleNamespace(autoclass=lambda nama: types.SimpleNamespace(SDK_INT=34))
        with mock.patch.dict(sys.modules, {"jnius": palsu}), mock.patch.object(droid, "_activity", lambda: akt):
            droid._terapkan_splash(droid.SPLASH_GELAP)
        self.assertEqual(akt.dipilih, [])

    def test_bukan_android_tidak_melakukan_apa_apa(self):
        with mock.patch.object(droid, "ON_ANDROID", False), mock.patch.object(droid, "run_on_main") as jalan:
            droid.apply_splash_theme("light")
        jalan.assert_not_called()

    def test_di_android_dijalankan_di_thread_utama_tanpa_menunggu(self):
        with mock.patch.object(droid, "ON_ANDROID", True), mock.patch.object(droid, "run_on_main") as jalan:
            droid.apply_splash_theme("light")
            droid.apply_splash_theme("dark")
        self.assertEqual([c.args for c in jalan.call_args_list],
                         [(droid._terapkan_splash_aman, droid.SPLASH_TERANG), (droid._terapkan_splash_aman, droid.SPLASH_GELAP)])
        self.assertTrue(all(c.kwargs == {"wait": False} for c in jalan.call_args_list))

    def test_galat_tidak_pernah_naik(self):
        with mock.patch.object(droid, "_activity", side_effect=RuntimeError("tak ada")), \
                mock.patch.dict(sys.modules, {"jnius": types.SimpleNamespace(
                    autoclass=lambda nama: types.SimpleNamespace(SDK_INT=34))}):
            droid._terapkan_splash_aman(droid.SPLASH_GELAP)                       # tidak boleh melempar
        with mock.patch.object(droid, "ON_ANDROID", True), mock.patch.object(droid, "run_on_main", side_effect=TimeoutError()):
            droid.apply_splash_theme("light")                                       # tidak boleh melempar
