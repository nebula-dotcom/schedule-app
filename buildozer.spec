[app]

title = California
package.name = jadwalkerja
package.domain = org.jadwal

source.dir = .
source.include_exts = py,html,ttf,txt
source.exclude_dirs = tests, bin, data, assets, keystore, .github, .buildozer, __pycache__

# Versi aplikasi
version = 1.0.0
android.numeric_version = 1000000

# Dependensi Python
requirements = python3,pillow,xlsxwriter,pyjnius

orientation = portrait
fullscreen = 0
# Tema aplikasi
android.apptheme = @style/JadwalTheme
android.add_resources = android_res/values/jadwal_theme.xml:values/jadwal_theme.xml, android_res/values-v31/jadwal_theme.xml:values-v31/jadwal_theme.xml

icon.filename = %(source.dir)s/assets/icon.png
icon.adaptive_foreground.filename = %(source.dir)s/assets/icon_fg.png
icon.adaptive_background.filename = %(source.dir)s/assets/icon_bg.png
presplash.filename = %(source.dir)s/assets/presplash.png
# Warna layar pembuka
android.presplash_color = #f6f8fc

# Bootstrap WebView dan port server
p4a.bootstrap = webview
# Hook build p4a
p4a.hook = p4a/hook.py
p4a.port = 8765

# Cabang p4a
p4a.branch = develop

# Versi API, arsitektur, dan izin Android
android.minapi = 29
android.api = 33
android.archs = arm64-v8a, armeabi-v7a
android.permissions = INTERNET
android.accept_sdk_license = True
android.release_artifact = apk

[buildozer]
log_level = 2
warn_on_root = 1
