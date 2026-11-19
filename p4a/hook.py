"""Hook untuk python-for-android (dipanggil lewat p4a.hook di buildozer.spec).

Bootstrap "webview" p4a punya halaman loading sendiri (file bernama "_load.html",
berisi animasi garis/bar bawaan) yang tampil sendiri selagi server Python kita
belum merespons -- SEBELUM web/loading.html milik proyek ini sempat terlihat.
Ini sumber "logo + icon garis 3" yang muncul sebelum loading.html kita.

before_apk_build berjalan setelah p4a menyiapkan seluruh proyek Android (termasuk
menyalin _load.html miliknya ke dalam dist), tapi sebelum Gradle mengemasnya jadi
APK. Di titik ini kita timpa _load.html itu dengan versi kita sendiri: tampilan
sama persis dengan web/loading.html (spinner + warna #f6f8fc), tanpa skrip
pindah-halaman (karena file ini tampil sebelum server kita menyala, jadi "/app"
belum ada yang melayani; p4a sendiri yang akan memindah ke server kita begitu
server itu merespons).

Satu-satunya skrip: kalau halaman ini sampai terbuka lagi lewat tombol kembali (riwayat WebView),
ia langsung kembali ke /app supaya tidak pernah menjadi jalan buntu.

Hook ini juga memaksa tema berlatar #F6F8FC (@style/JadwalTheme, lihat android_res/) dipakai di
AndroidManifest, lalu menyalin resource temanya langsung ke proyek Android. Tanpa ini, splash sistem Android 12+
bisa tetap hitam kalau tema dari buildozer.spec tidak sampai ke manifest.
"""
import re
import shutil
from pathlib import Path

PORT = 8765        # harus sama dengan p4a.port di buildozer.spec (dan ANDROID_PORT di jadwal/settings.py)

LOADING_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Jadwal Kerja</title>
<style>
html,body{height:100%;margin:0;background:#f6f8fc}
body{display:flex;align-items:center;justify-content:center;overflow:hidden}

/* From Uiverse.io by AqFox -- sama seperti web/loading.html, supaya tidak ada
   bedanya dengan layar loading sendiri */
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
</head>
<body>
<div class="spinner"><div></div><div></div><div></div><div></div><div></div><div></div></div>
<script>
try{var n=performance.getEntriesByType('navigation')[0];if(n&&n.type==='back_forward')location.replace('http://127.0.0.1:@PORT@/app')}catch(e){}
</script>
</body>
</html>
"""


def render_loading() -> str:
    return LOADING_HTML.replace("@PORT@", str(PORT))


THEME = "@style/JadwalTheme"
ROOT = Path(__file__).resolve().parent.parent


LATAR_JAVA = "0xFFF6F8FC"       # warna dasar #F6F8FC (ARGB) untuk latar WebView -- harus sama dengan --bg di web/index.html
JAVA_TANDA = "/* jadwal: latar WebView */"
WEBVIEW_BARU = re.compile(r"(?P<lhs>[A-Za-z_][\w.]*)\s*=\s*new\s+WebView\s*\([^;]*\)\s*;")


def patch_java(text: str) -> str:
    """Beri WebView buatan p4a latar #F6F8FC segera setelah dibuat.

    WebView yang baru dibuat berlatar PUTIH sampai halaman pertamanya (_load.html) selesai digambar; di HP itu
    terlihat sebagai kilatan putih sebelum layar loading. Tema dan presplash tidak bisa mengubahnya.
    Hanya diubah kalau ada tepat satu pembuatan WebView (jadi kodenya pasti masuk akal); selain itu dibiarkan.
    """
    if JAVA_TANDA in text:
        return text
    cocok = list(WEBVIEW_BARU.finditer(text))
    if len(cocok) != 1:
        return text
    m = cocok[0]
    return text[:m.end()] + f" {m.group('lhs')}.setBackgroundColor({LATAR_JAVA}); {JAVA_TANDA}" + text[m.end():]


BACK_TANDA = "/* jadwal: tombol kembali */"
BACK_METODE = re.compile(r"\bvoid\s+onBackPressed\s*\(\s*\)\s*(?:throws[^{]*)?\{")
BACK_JAVA = """
        { android.webkit.WebView __jw = null;
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
          if (__jw != null) {
            String __ju = __jw.getUrl();
            if (__ju != null && __ju.split("[?#]")[0].replaceAll("/+$", "").endsWith("/app")) {
              __jw.evaluateJavascript("window.__back && window.__back()", null);
              return;
            }
          }
        }
"""


def patch_back(text: str) -> str:
    """Tombol kembali Activity (onBackPressed bawaan p4a) diteruskan ke window.__back di halaman aplikasi (/app).

    Tanpa ini p4a memunculkan pesan keluar bawaannya di SEMUA halaman. Sebelum /app tampil (layar loading), perilaku
    bawaan tetap dipakai. Hanya diubah kalau ada tepat satu onBackPressed(); selain itu dibiarkan.
    """
    if BACK_TANDA in text:
        return text
    cocok = list(BACK_METODE.finditer(text))
    if len(cocok) != 1:
        return text
    m = cocok[0]
    return text[:m.end()] + " " + BACK_TANDA + BACK_JAVA + text[m.end():]


def apply_back_button(dist_dir: Path) -> None:
    berkas = list(dist_dir.rglob("PythonActivity.java"))
    dipasang = False
    for java in berkas:
        old = java.read_text(encoding="utf-8")
        new = patch_back(old)
        if new != old:
            java.write_text(new, encoding="utf-8")
            print(f"[hook] tombol kembali diteruskan ke JavaScript di {java}")
            dipasang = True
        elif BACK_TANDA in old:
            dipasang = True
    if not dipasang:
        print("[hook] PERINGATAN: onBackPressed() di PythonActivity.java (file bawaan p4a, bukan file proyek ini) tidak "
              "ditemukan/ganda -- tombol kembali tidak diteruskan ke JavaScript dari sisi Activity.")
        if not berkas:
            print("[hook] PythonActivity.java tidak ada di dist ini.")
        kunci = re.compile(r"Tap again|onBackPressed|KEYCODE_BACK|onKeyDown|onKeyUp|dispatchKeyEvent|OnBackInvoked|Toast|goBack|canGoBack")
        for java in berkas[:1]:
            baris = [f"{i}: {b.strip()[:160]}" for i, b in enumerate(java.read_text(encoding="utf-8").splitlines(), 1)
                     if kunci.search(b)]
            print(f"[hook] baris terkait tombol kembali di {java}:")
            for b in baris[:40]:
                print(f"[hook]    {b}")


def apply_webview_background(dist_dir: Path) -> None:
    berkas = list(dist_dir.rglob("PythonActivity.java"))
    dipasang = False
    for java in berkas:
        old = java.read_text(encoding="utf-8")
        new = patch_java(old)
        if new != old:
            java.write_text(new, encoding="utf-8")
            print(f"[hook] latar WebView #F6F8FC dipasang di {java}")
            dipasang = True
        elif JAVA_TANDA in old:
            dipasang = True
    if not dipasang:
        print("[hook] PERINGATAN: pembuatan WebView di PythonActivity.java (file bawaan p4a di folder dist, bukan file "
              "proyek ini) tidak ditemukan/ganda -- latar WebView hanya diatur lewat droid.py setelah Python jalan, "
              "kilatan putih singkat di awal bisa masih muncul.")
        if not berkas:
            print("[hook] PythonActivity.java tidak ada di dist ini.")
        for java in berkas[:1]:                          # tunjukkan kode aslinya supaya bisa disesuaikan
            baris = [f"{i}: {b.strip()[:160]}" for i, b in enumerate(java.read_text(encoding="utf-8").splitlines(), 1)
                     if "WebView" in b or "setContentView" in b]
            print(f"[hook] baris WebView/setContentView di {java}:")
            for b in baris[:30]:
                print(f"[hook]    {b}")


THEME_ATTR = re.compile(r'android:theme="([^"]*)"')


def patch_manifest(text: str) -> str:
    """Ganti android:theme yang bernilai tetap (mis. @android:style/Theme.NoTitleBar) dengan tema kita.

    Yang TIDAK disentuh:
    - nilai berisi Jinja ({{ ... }}, {% ... %}): template p4a mengisinya dari --android-apptheme
      (android.apptheme di buildozer.spec = @style/JadwalTheme), jadi sudah benar;
    - atribut baru tidak pernah ditambahkan (activity tanpa android:theme otomatis memakai tema aplikasi).
    Dengan begitu hook tidak bisa menghasilkan atribut ganda atau sisa potongan Jinja di AndroidManifest.xml.
    """
    def ganti(m):
        nilai = m.group(1)
        if "{{" in nilai or "{%" in nilai or "{#" in nilai:
            return m.group(0)
        return f'android:theme="{THEME}"'

    return THEME_ATTR.sub(ganti, text)


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


def before_apk_build(toolchain):
    dist_dir = Path(toolchain._dist.dist_dir)
    apply_theme(dist_dir)
    apply_webview_background(dist_dir)
    apply_back_button(dist_dir)
    hits = list(dist_dir.rglob("_load.html"))   # dicari by name: lokasi persisnya bisa beda antar versi p4a
    for hit in hits:
        hit.write_text(render_loading(), encoding="utf-8")
        print(f"[hook] _load.html bawaan p4a ditimpa: {hit}")
    if not hits:
        print("[hook] PERINGATAN: _load.html bawaan p4a tidak ditemukan di dist -- "
              "mungkin lokasinya berubah di versi p4a ini, layar loading bawaan bisa masih muncul.")
