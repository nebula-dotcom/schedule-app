[app]

title = California
package.name = jadwalkerja
package.domain = org.jadwal

source.dir = .
source.include_exts = py,html,ttf,txt
source.exclude_dirs = tests, bin, data, assets, keystore, .github, .buildozer, __pycache__

# Nomor versi diisi otomatis oleh GitHub Actions (v1.0.0, v1.0.1, ...). Nilai di sini hanya untuk build manual.
version = 1.0.0
android.numeric_version = 1000000

# Hanya Python bawaan + Pillow (PNG) + XlsxWriter (Excel); pyjnius untuk simpan ke Downloads dan tombol kembali.
requirements = python3,pillow,xlsxwriter,pyjnius

orientation = portrait
fullscreen = 0
# Tema dasar Android (@android:style/Theme, turunan NoTitleBar di bawah) berlatar HITAM secara
# bawaan -- itu sumber splash sistem yang hitam. Theme.Light membuatnya putih.
# Tema memakai android_res/values*/jadwal_theme.xml (latar #F6F8FC; di Android 12+ juga mengatur latar splash sistem)
android.apptheme = @style/JadwalTheme
android.add_resources = android_res/values/jadwal_theme.xml:values/jadwal_theme.xml, android_res/values-v31/jadwal_theme.xml:values-v31/jadwal_theme.xml

icon.filename = %(source.dir)s/assets/icon.png
icon.adaptive_foreground.filename = %(source.dir)s/assets/icon_fg.png
icon.adaptive_background.filename = %(source.dir)s/assets/icon_bg.png
presplash.filename = %(source.dir)s/assets/presplash.png
# Layar pembuka bawaan dibuat polos (assets/presplash.png) dengan warna yang sama dengan web/loading.html,
# jadi saat aplikasi dibuka yang terlihat hanya loading.html tanpa logo.
android.presplash_color = #f6f8fc

# ---------- Android ----------
# WebView + server Python lokal. Port harus sama dengan ANDROID_PORT di jadwal/settings.py.
p4a.bootstrap = webview
# Menimpa layar loading bawaan p4a (_load.html, animasi garis bawaan) dengan tampilan
# web/loading.html sendiri, supaya yang tampil sebelum server kita menyala sama persis
# dengan sesudahnya -- lihat p4a/hook.py.
p4a.hook = p4a/hook.py
p4a.port = 8765

# Cabang develop dipakai karena cabang master (rilis 2026.05) punya galat: tahap pemasangan paket Python murni
# (xlsxwriter, six) gagal dengan "ImportError: cannot import name 'capture_logging' from pip" (p4a #3339/#3364).
# Perbaikannya (p4a #3360, 30 Jul 2026) baru ada di develop. Boleh dikembalikan ke master setelah ada rilis baru.
p4a.branch = develop

# Android 10+ (API 29): file Excel/PNG disimpan ke Downloads lewat MediaStore tanpa izin penyimpanan.
android.minapi = 29
android.api = 33
android.archs = arm64-v8a, armeabi-v7a
android.permissions = INTERNET
android.accept_sdk_license = True
android.release_artifact = apk

[buildozer]
log_level = 2
warn_on_root = 1
