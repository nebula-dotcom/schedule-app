#!/usr/bin/env python3
import argparse
import os
import threading
import traceback

from jadwal import droid
from jadwal import settings as cfg
from jadwal.server import make_server, pick_port


# Mode Android: server lokal dan loop utama
def run_android():
    server = make_server("127.0.0.1", cfg.ANDROID_PORT)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    droid.main_loop()


# Mode komputer: server untuk browser
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


# Titik masuk aplikasi
try:
    run_android() if droid.ON_ANDROID else run_desktop()
except Exception:
    traceback.print_exc()
    raise
