#!/usr/bin/env python3
"""Jadwal Kerja: skrip utama (satu-satunya skrip di luar folder).

Komputer/Termux:  python main.py            lalu buka  http://localhost:8888
                  python main.py --port 9000        port lain
                  python main.py --host 0.0.0.0     bisa dibuka dari perangkat lain di Wi-Fi yang sama

Android (APK): python-for-android menjalankan file ini (harus bernama main.py di folder utama).
Server berjalan di 127.0.0.1:<ANDROID_PORT> dan WebView aplikasi membukanya
(port yang sama diatur di buildozer.spec -> p4a.port).

Semua logika ada di paket `jadwal/`; halaman web di `web/`.
"""
import argparse
import os
import threading
import traceback

from jadwal import droid
from jadwal import settings as cfg
from jadwal.server import make_server, pick_port


def run_android():
    threading.Thread(target=droid.install_back_hook, daemon=True).start()
    make_server("127.0.0.1", cfg.ANDROID_PORT).serve_forever()


def run_desktop():
    ap = argparse.ArgumentParser(description="Jadwal Kerja")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", cfg.DEFAULT_PORT)))
    args = ap.parse_args()

    port = pick_port(args.host, args.port)
    shown = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    print(f"\n  Jadwal Kerja siap. Buka di browser:  http://{shown}:{port}\n"
          f"  Hentikan dengan Ctrl+C.\n")
    try:
        make_server(args.host, port).serve_forever()
    except KeyboardInterrupt:
        print("\n  Dihentikan.")


try:                                   # dipanggil langsung (tanpa penjaga __name__) agar pasti jalan di Android
    run_android() if droid.ON_ANDROID else run_desktop()
except Exception:
    traceback.print_exc()              # terlihat di logcat kalau server gagal start
    raise
