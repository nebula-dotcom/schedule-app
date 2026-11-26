import re
import shutil
from pathlib import Path

# Port server aplikasi
PORT = 8765

# Layar loading bawaan p4a
LOADING_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Jadwal Kerja</title>
<style>
html,body{height:100%;margin:0;background:#121212}
html.t-light,html.t-light body{background:#f6f8fc}
body{display:flex;align-items:center;justify-content:center;overflow:hidden}

/* From Uiverse.io by AqFox */
.spinner{width:44px;height:44px;animation:spinner-y0fdc1 2s infinite ease;transform-style:preserve-3d}
.spinner>div{background-color:rgba(0,77,255,0.2);height:100%;position:absolute;width:100%;border:2px solid #004dff}
.spinner div:nth-of-type(1){transform:translateZ(-22px) rotateY(180deg)}
.spinner div:nth-of-type(2){transform:rotateY(-270deg) translateX(50%);transform-origin:top right}
.spinner div:nth-of-type(3){transform:rotateY(270deg) translateX(-50%);transform-origin:center left}
.spinner div:nth-of-type(4){transform:rotateX(90deg) translateY(-50%);transform-origin:top center}
.spinner div:nth-of-type(5){transform:rotateX(-90deg) translateY(50%);transform-origin:bottom center}
.spinner div:nth-of-type(6){transform:translateZ(22px)}
@keyframes spinner-y0fdc1{
 0%{transform:rotate(45deg) rotateX(-25deg) rotateY(25deg)}
 50%{transform:rotate(45deg) rotateX(-385deg) rotateY(25deg)}
 100%{transform:rotate(45deg) rotateX(-385deg) rotateY(385deg)}
}
</style>
<script>
/* Tema tersimpan dari patch Java lewat user-agent; tanpa penanda tetap gelap */
if(navigator.userAgent.indexOf('JadwalTema/light')>=0)document.documentElement.className='t-light';
</script>
</head>
<body>
<div class="spinner"><div></div><div></div><div></div><div></div><div></div><div></div></div>
<script>
try{var n=performance.getEntriesByType('navigation')[0];if(n&&n.type==='back_forward')location.replace('http://127.0.0.1:@PORT@/app')}catch(e){}
</script>
</body>
</html>
"""


# Isi layar loading dengan port
def render_loading() -> str:
    return LOADING_HTML.replace("@PORT@", str(PORT))


# Tema dan folder proyek
THEME = "@style/JadwalTheme"
ROOT = Path(__file__).resolve().parent.parent


# Patch latar WebView
LATAR_JAVA = "0xFF121212"
LATAR_JAVA_TERANG = "0xFFF6F8FC"
JAVA_TANDA = "/* jadwal: latar WebView */"
WEBVIEW_BARU = re.compile(r"(?P<lhs>[A-Za-z_][\w.]*)\s*=\s*new\s+WebView\s*\([^;]*\)\s*;")

# Kode Java: baca tema tersimpan, atur latar WebView dan jendela, beri penanda tema di user-agent
LATAR_KODE = (
    "{ boolean __jt = false; "
    "try { java.io.File __jf = new java.io.File(@L@.getContext().getFilesDir(), \"data/theme.txt\"); "
    "if (__jf.isFile()) { "
    "java.io.BufferedReader __jr = new java.io.BufferedReader(new java.io.FileReader(__jf)); "
    "try { String __jl = __jr.readLine(); if (__jl != null && \"light\".equals(__jl.trim())) { __jt = true; } } "
    "finally { __jr.close(); } } } catch (Exception __je) { } "
    "int __jc = __jt ? @TERANG@ : @GELAP@; "
    "@L@.setBackgroundColor(__jc); "
    "if (@L@.getContext() instanceof android.app.Activity) { "
    "((android.app.Activity) @L@.getContext()).getWindow().setBackgroundDrawable("
    "new android.graphics.drawable.ColorDrawable(__jc)); } "
    "@L@.getSettings().setUserAgentString(@L@.getSettings().getUserAgentString() "
    "+ (__jt ? \" JadwalTema/light\" : \" JadwalTema/dark\")); } "
)


# Sisipkan latar WebView di PythonActivity.java
def patch_java(text: str) -> str:
    if JAVA_TANDA in text:
        return text
    cocok = list(WEBVIEW_BARU.finditer(text))
    if len(cocok) != 1:
        return text
    m = cocok[0]
    kode = LATAR_KODE.replace("@L@", m.group("lhs")).replace("@TERANG@", LATAR_JAVA_TERANG).replace("@GELAP@", LATAR_JAVA)
    return text[:m.end()] + " " + kode + JAVA_TANDA + text[m.end():]


# Patch tombol kembali
BACK_TANDA = "/* jadwal: tombol kembali */"
BACK_KEYDOWN = re.compile(r"\bboolean\s+onKeyDown\s*\(\s*(?:final\s+)?int\s+(?P<k>\w+)\s*,\s*"
                          r"(?:final\s+)?(?:android\.view\.)?KeyEvent\s+(?P<e>\w+)\s*\)\s*(?:throws[^{]*)?\{")
BACK_METODE = re.compile(r"\bvoid\s+onBackPressed\s*\(\s*\)\s*(?:throws[^{]*)?\{")
BACK_CARI = """
          android.webkit.WebView __jw = null;
          java.util.ArrayDeque<android.view.View> __jq = new java.util.ArrayDeque<android.view.View>();
          __jq.add(getWindow().getDecorView());
          while (!__jq.isEmpty() && __jw == null) {
            android.view.View __jv = __jq.poll();
            if (__jv instanceof android.webkit.WebView) { __jw = (android.webkit.WebView) __jv; }
            else if (__jv instanceof android.view.ViewGroup) {
              android.view.ViewGroup __jg = (android.view.ViewGroup) __jv;
              for (int __ji = 0; __ji < __jg.getChildCount(); __ji++) { __jq.add(__jg.getChildAt(__ji)); }
            }
          }
          String __ju = (__jw == null) ? null : __jw.getUrl();
          boolean __japp = __ju != null && __ju.split("[?#]")[0].replaceAll("/+$", "").endsWith("/app");
"""
BACK_KEYDOWN_JAVA = """
        if (@K@ == android.view.KeyEvent.KEYCODE_BACK) {""" + BACK_CARI + """          if (__japp) {
            if (@E@.getRepeatCount() == 0) { __jw.evaluateJavascript("window.__back && window.__back()", null); }
            return true;
          }
        }
"""
BACK_JAVA = """
        {""" + BACK_CARI + """          if (__japp) {
            __jw.evaluateJavascript("window.__back && window.__back()", null);
            return;
          }
        }
"""


# Sisipkan tombol kembali di PythonActivity.java
def patch_back(text: str) -> str:
    if BACK_TANDA in text:
        return text
    sisip = []
    kd = list(BACK_KEYDOWN.finditer(text))
    if len(kd) == 1:
        m = kd[0]
        sisip.append((m.end(), BACK_KEYDOWN_JAVA.replace("@K@", m.group("k")).replace("@E@", m.group("e"))))
    bp = list(BACK_METODE.finditer(text))
    if len(bp) == 1:
        sisip.append((bp[0].end(), BACK_JAVA))
    for pos, kode in sorted(sisip, key=lambda x: x[0], reverse=True):
        text = text[:pos] + " " + BACK_TANDA + kode + text[pos:]
    return text


# Cari PythonActivity.java di dist
def activity_files(dist_dir: Path) -> list:
    return list(dist_dir.rglob("PythonActivity.java"))


# Terapkan patch ke semua PythonActivity.java
def patch_activity_files(files: list, patch, marker: str, message: str) -> bool:
    installed = False
    for java in files:
        old = java.read_text(encoding="utf-8")
        new = patch(old)
        if new != old:
            java.write_text(new, encoding="utf-8")
            print(message.format(java=java))
            installed = True
        elif marker in old:
            installed = True
    return installed


# Cetak baris terkait untuk diagnosa
def print_related_lines(files: list, match, title: str, limit: int) -> None:
    for java in files[:1]:
        lines = [f"{i}: {b.strip()[:160]}" for i, b in enumerate(java.read_text(encoding="utf-8").splitlines(), 1)
                 if match(b)]
        print(title.format(java=java))
        for line in lines[:limit]:
            print(f"[hook]    {line}")


# Pasang tombol kembali
def apply_back_button(dist_dir: Path) -> None:
    files = activity_files(dist_dir)
    if patch_activity_files(files, patch_back, BACK_TANDA, "[hook] tombol kembali diteruskan ke JavaScript di {java}"):
        return
    print("[hook] PERINGATAN: onKeyDown()/onBackPressed() di PythonActivity.java (file bawaan p4a, bukan file proyek ini) tidak "
          "ditemukan/ganda -- tombol kembali tidak diteruskan ke JavaScript dari sisi Activity.")
    if not files:
        print("[hook] PythonActivity.java tidak ada di dist ini.")
    keys = re.compile(r"Tap again|onBackPressed|KEYCODE_BACK|onKeyDown|onKeyUp|dispatchKeyEvent|OnBackInvoked|Toast|goBack|canGoBack")
    print_related_lines(files, keys.search, "[hook] baris terkait tombol kembali di {java}:", 40)


# Pasang latar WebView
def apply_webview_background(dist_dir: Path) -> None:
    files = activity_files(dist_dir)
    if patch_activity_files(files, patch_java, JAVA_TANDA, "[hook] latar WebView (ikut tema tersimpan) dipasang di {java}"):
        return
    print("[hook] PERINGATAN: pembuatan WebView di PythonActivity.java (file bawaan p4a di folder dist, bukan file "
          "proyek ini) tidak ditemukan/ganda -- latar WebView hanya diatur lewat droid.py setelah Python jalan, "
          "kilatan putih singkat di awal bisa masih muncul.")
    if not files:
        print("[hook] PythonActivity.java tidak ada di dist ini.")
    print_related_lines(files, lambda b: "WebView" in b or "setContentView" in b,
                        "[hook] baris WebView/setContentView di {java}:", 30)


# Patch pemilih file Import Excel
FILE_TANDA = "/* jadwal: pemilih file */"
FILE_MANIFEST_TANDA = "org.jadwal.FilePickActivity"
FILE_JAVA = """ @L@.setWebChromeClient(new android.webkit.WebChromeClient() {
            @Override
            public boolean onShowFileChooser(android.webkit.WebView __w, android.webkit.ValueCallback<android.net.Uri[]> __cb,
                                             android.webkit.WebChromeClient.FileChooserParams __p) {
              return org.jadwal.FilePickActivity.start(__w.getContext(), __cb);
            }
          }); """ + FILE_TANDA

# Kelas Java FilePickActivity
FILE_PICK_ACTIVITY = """package org.jadwal;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;

// Activity pemilih file untuk Import Excel
public class FilePickActivity extends Activity {
    private static final int REQ = 7711;
    private static ValueCallback<Uri[]> sCallback;

    // Mulai pemilih file
    public static boolean start(Context ctx, ValueCallback<Uri[]> cb) {
        if (sCallback != null) {
            sCallback.onReceiveValue(null);
            sCallback = null;
        }
        sCallback = cb;
        try {
            Intent i = new Intent(ctx, FilePickActivity.class);
            if (!(ctx instanceof Activity)) {
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            }
            ctx.startActivity(i);
        } catch (Exception e) {
            deliver(null);
        }
        return true;
    }

    // Buka pemilih file sistem
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (state != null) {
            return;
        }
        if (sCallback == null) {
            finish();
            return;
        }
        try {
            Intent pick = new Intent(Intent.ACTION_GET_CONTENT);
            pick.addCategory(Intent.CATEGORY_OPENABLE);
            pick.setType("*/*");
            startActivityForResult(pick, REQ);
        } catch (Exception e) {
            deliver(null);
            finish();
        }
    }

    // Terima hasil pilihan file
    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        Uri[] hasil = null;
        if (requestCode == REQ && resultCode == RESULT_OK && data != null) {
            hasil = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
        }
        deliver(hasil);
        finish();
    }

    // Balas halaman bila ditutup tanpa hasil
    @Override
    protected void onDestroy() {
        if (isFinishing()) {
            deliver(null);
        }
        super.onDestroy();
    }

    // Kirim hasil ke halaman web
    private static void deliver(Uri[] hasil) {
        ValueCallback<Uri[]> cb = sCallback;
        sCallback = null;
        if (cb != null) {
            cb.onReceiveValue(hasil);
        }
    }
}
"""
# Daftar activity di manifest
ACTIVITY_XML = ('<activity android:name="org.jadwal.FilePickActivity" android:exported="false" '
                'android:excludeFromRecents="true" android:theme="@android:style/Theme.Translucent.NoTitleBar" />')


# Sisipkan pemilih file di PythonActivity.java
def patch_file_chooser(text: str) -> str:
    if FILE_TANDA in text or "setWebChromeClient" in text:
        return text
    cocok = list(WEBVIEW_BARU.finditer(text))
    if len(cocok) != 1:
        return text
    m = cocok[0]
    return text[:m.end()] + FILE_JAVA.replace("@L@", m.group("lhs")) + text[m.end():]


# Daftarkan FilePickActivity di manifest
def patch_manifest_file_picker(text: str) -> str:
    if FILE_MANIFEST_TANDA in text or text.count("</application>") != 1:
        return text
    return text.replace("</application>", "    " + ACTIVITY_XML + "\n    </application>", 1)


# Pasang pemilih file
def apply_file_chooser(dist_dir: Path) -> None:
    files = activity_files(dist_dir)
    installed = False
    for java in files:
        old = java.read_text(encoding="utf-8")
        new = patch_file_chooser(old)
        if new != old:
            java.write_text(new, encoding="utf-8")
            print(f"[hook] pemilih file (Import Excel) dipasang di {java}")
        if new != old or FILE_TANDA in old:
            installed = True
            write_pick_activity(java)
    if installed:
        register_pick_activity(dist_dir)
        return
    print("[hook] PERINGATAN: pemilih file untuk Import Excel TIDAK terpasang (pembuatan WebView di PythonActivity.java "
          "tidak ditemukan/ganda, atau sudah ada setWebChromeClient) -- tombol Pilih file di halaman tidak akan membuka apa-apa.")
    print_related_lines(files, lambda b: "WebView" in b or "WebChromeClient" in b,
                        "[hook] baris WebView/WebChromeClient di {java}:", 30)


# Tulis kelas FilePickActivity
def write_pick_activity(java: Path) -> None:
    root = next((p for p in java.parents if p.name == "java"), java.parent)
    kelas = root / "org" / "jadwal" / "FilePickActivity.java"
    kelas.parent.mkdir(parents=True, exist_ok=True)
    kelas.write_text(FILE_PICK_ACTIVITY, encoding="utf-8")
    print(f"[hook] FilePickActivity ditulis: {kelas}")


# Daftarkan FilePickActivity di semua manifest
def register_pick_activity(dist_dir: Path) -> None:
    for manifest in dist_dir.rglob("AndroidManifest*.xml"):
        old = manifest.read_text(encoding="utf-8")
        new = patch_manifest_file_picker(old)
        if new != old:
            manifest.write_text(new, encoding="utf-8")
            print(f"[hook] FilePickActivity didaftarkan di {manifest}")


# Patch tema manifest
THEME_ATTR = re.compile(r'android:theme="([^"]*)"')


# Ganti tema di manifest
def patch_manifest(text: str) -> str:
    def ganti(m):
        nilai = m.group(1)
        if "{{" in nilai or "{%" in nilai or "{#" in nilai:
            return m.group(0)
        return f'android:theme="{THEME}"'

    simpan = "\0jadwal-filepick\0"
    return THEME_ATTR.sub(ganti, text.replace(ACTIVITY_XML, simpan)).replace(simpan, ACTIVITY_XML)


# Pasang tema dan resource
def apply_theme(dist_dir: Path) -> None:
    for manifest in dist_dir.rglob("AndroidManifest*.xml"):
        old = manifest.read_text(encoding="utf-8")
        new = patch_manifest(old)
        manifest.write_text(new, encoding="utf-8")
        print(f"[hook] tema {THEME} dipasang di {manifest}" if new != old else f"[hook] tema sudah sesuai di {manifest}")
    res_src = ROOT / "android_res"
    if not res_src.is_dir():
        print(f"[hook] PERINGATAN: folder {res_src} tidak ditemukan, resource tema hanya dari android.add_resources.")
        return
    for src in res_src.rglob("*.xml"):
        dest = dist_dir / "src" / "main" / "res" / src.relative_to(res_src)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
        print(f"[hook] resource tema disalin: {dest}")


# Hook build APK p4a
def before_apk_build(toolchain):
    dist_dir = Path(toolchain._dist.dist_dir)
    apply_theme(dist_dir)
    apply_webview_background(dist_dir)
    apply_back_button(dist_dir)
    apply_file_chooser(dist_dir)
    hits = list(dist_dir.rglob("_load.html"))
    for hit in hits:
        hit.write_text(render_loading(), encoding="utf-8")
        print(f"[hook] _load.html bawaan p4a ditimpa: {hit}")
    if not hits:
        print("[hook] PERINGATAN: _load.html bawaan p4a tidak ditemukan di dist -- "
              "mungkin lokasinya berubah di versi p4a ini, layar loading bawaan bisa masih muncul.")
