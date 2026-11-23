from __future__ import annotations

import json
import os
import re
import socket
import tempfile
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import droid
from . import settings as cfg
from .schedule import Schedule, ScheduleError

# Konstanta server dan daftar halaman
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEETS = {"adm": "admin", "gl": "global"}
ALL_NAME = "jadwal_kerja"
MAX_BODY = 512 * 1024
PAGES = {"/": "loading.html", "/app": "index.html"}
EXPORT_PATH = re.compile(r"^/api/export/([^/]+)$")


# Galat HTTP dengan kode status
class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# Penanganan request HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "JadwalKerja"
    sys_version = ""

    # Matikan log request
    def log_message(self, fmt, *args):
        pass

    # Kirim respons
    def _send(self, status: int, body: bytes, ctype: str, headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    # Kirim respons JSON
    def _json(self, obj, status: int = 200):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    # Baca isi JSON dari request
    def _read_json(self):
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise HttpError(400, "Permintaan tidak valid.")
        if size > MAX_BODY:
            self.rfile.read(min(size, 8 * 1024 * 1024))
            raise HttpError(413, "File terlalu besar.")
        raw = self.rfile.read(size) if size else b""
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    # Metode HTTP GET, PUT, POST
    def do_GET(self):
        self._run("GET")

    def do_PUT(self):
        self._run("PUT")

    def do_POST(self):
        self._run("POST")

    # Jalankan rute dan ubah galat jadi respons
    def _run(self, method: str):
        try:
            self._route(method, urlsplit(self.path).path)
        except HttpError as err:
            self._json({"error": err.message}, err.status)
        except ScheduleError as err:
            self._json({"error": str(err)}, 422)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as err:
            traceback.print_exc()
            self._json({"error": f"Terjadi galat di server: {err}"}, 500)

    # Daftar rute
    def _route(self, method: str, path: str):
        if path in PAGES and method == "GET":
            return self._send(200, (cfg.WEB_DIR / PAGES[path]).read_bytes(), "text/html; charset=utf-8")
        if path == "/favicon.ico" and method == "GET":
            return self._send(204, b"", "image/x-icon")
        if path == "/api/state":
            if method == "GET":
                return self._get_state()
            if method == "PUT":
                return self._put_state()
        match = EXPORT_PATH.match(path)
        if match and method == "POST":
            return self._export(match.group(1))
        if path == "/api/exit" and method == "POST":
            return self._exit()
        if path == "/api/import" and method == "POST":
            return self._import()
        known = path in PAGES or path in ("/favicon.ico", "/api/state", "/api/exit", "/api/import") or match
        raise HttpError(405 if known else 404, "Metode tidak diizinkan." if known else "Tidak ditemukan.")

    # Rute GET /api/state
    def _get_state(self):
        try:
            data = json.loads(cfg.STATE_FILE.read_text(encoding="utf-8"))
            self._json(Schedule.from_payload(data).to_payload())
        except (OSError, ValueError):
            self._json({})

    # Rute PUT /api/state
    def _put_state(self):
        sched = Schedule.from_payload(self._read_json())
        cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=cfg.DATA_DIR, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(sched.to_payload(), fh, ensure_ascii=False, indent=1)
        os.replace(tmp, cfg.STATE_FILE)
        self._json({"ok": True})

    # Rute POST /api/import
    def _import(self):
        body = self._read_json()
        if not isinstance(body, dict):
            raise HttpError(400, "Permintaan tidak valid.")
        from . import importer

        self._json({"ok": True, **importer.parse_b64(body.get("data"))})

    # Rute POST /api/export/xlsx dan /api/export/png
    def _export(self, kind: str):
        if kind not in ("xlsx", "png"):
            raise HttpError(404, "Jenis file tidak dikenal.")
        body = self._read_json()
        sched = Schedule.from_payload(body)
        sheet = body.get("sheet") if body.get("sheet") in (*SHEETS, "all") else "adm"
        if kind == "png" and sheet == "all":
            raise HttpError(400, "Save PNG hanya untuk Administrator atau Jadwal Global.")

        if kind == "xlsx":
            from . import excel

            data, mime = excel.build_workbook(sched, sheet), XLSX_MIME
        else:
            from . import image

            data, mime = image.render(sched, sheet), "image/png"
        name = f"{ALL_NAME}.xlsx" if sheet == "all" else f"{sched.file_stem()}_{SHEETS[sheet]}.{kind}"

        if droid.ON_ANDROID:
            droid.save_to_downloads(name, data, mime)
            return self._json({"saved": name, "folder": "Download"})
        self._send(200, data, mime, {"Content-Disposition": f'attachment; filename="{name}"'})

    # Rute POST /api/exit
    def _exit(self):
        if not droid.ON_ANDROID:
            return self._json({"ok": False})
        self._json({"ok": True})
        droid.exit_app()


# Buat server HTTP
def make_server(host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


# Cek port kosong
def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


# Pilih port kosong pertama
def pick_port(host: str, wanted: int) -> int:
    for port in range(wanted, min(wanted + cfg.PORT_TRIES, 65536)):
        if port in cfg.BLOCKED_PORTS:
            print(f"  (port {port} dilewati: dipakai aplikasi lain)")
        elif port_free(host, port):
            return port
        else:
            print(f"  (port {port} sedang dipakai, mencoba berikutnya)")
    raise SystemExit(f"Tidak menemukan port kosong mulai dari {wanted}.")
