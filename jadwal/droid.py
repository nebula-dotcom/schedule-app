"""Bagian khusus Android (python-for-android, bootstrap webview).

Di luar Android (Termux/PC) `ON_ANDROID` bernilai False dan tidak ada yang dijalankan di sini.
Semua akses ke Java lewat pyjnius dan di-import saat dipakai saja.
"""
from __future__ import annotations

import os
import queue
import threading
import time

ON_ANDROID = "ANDROID_ARGUMENT" in os.environ     # diisi otomatis oleh python-for-android

KEYCODE_BACK = 4
LATAR_WEBVIEW = "#F6F8FC"   # latar WebView (sebelum/antar halaman); harus sama dengan --bg di web/index.html
ACTION_UP = 1
_hooked = None            # WebView yang sudah dipasangi pendengar tombol kembali
_keep = []                # cegah pendengar Python dibuang oleh garbage collector
_tidy_job = None          # Runnable pembersih riwayat/fokus WebView (dibuat sekali, dipakai ulang)
_last_back = [0]         # waktu (ms) tekan kembali terakhir yang diteruskan ke JavaScript
_tasks = queue.Queue()   # pekerjaan Java yang dititipkan ke thread utama
_main_id = [None]        # id thread utama yang menjalankan main_loop()


def _activity():
    from jnius import autoclass
    return autoclass("org.kivy.android.PythonActivity").mActivity


# ----------------------------------------------------------------- semua pekerjaan Java lewat thread utama
class _Task:
    def __init__(self, fn, args):
        self.fn, self.args = fn, args
        self.done, self.result, self.error = threading.Event(), None, None


def run_on_main(fn, *args, wait: bool = True, timeout: float = 30.0):
    """Jalankan fn(*args) di thread utama Python dan kembalikan hasilnya.

    Hanya thread utama (yang menjalankan main.py) bisa menemukan kelas Java milik aplikasi, mis.
    org.kivy.android.PythonActivity. Thread buatan Python (termasuk thread pelayan server) memakai class loader
    sistem dan gagal dengan "ClassNotFoundException: org.kivy.android.PythonActivity". Karena itu semua yang
    menyentuh kelas aplikasi dititipkan ke sini. Di luar Android, atau kalau dipanggil dari thread utama, langsung dijalankan."""
    if not ON_ANDROID or _main_id[0] is None or threading.get_ident() == _main_id[0]:
        return fn(*args)
    task = _Task(fn, args)
    _tasks.put(task)
    if not wait:
        return None
    if not task.done.wait(timeout):
        raise TimeoutError("Android tidak merespons (thread utama sibuk).")
    if task.error is not None:
        raise task.error
    return task.result


def main_loop(stop: threading.Event | None = None) -> None:
    """Dijalankan di THREAD UTAMA (dari main.py) dan tidak pernah selesai: melayani pekerjaan Java dari
    run_on_main, memasang/memeriksa pendengar tombol kembali di WebView, sekaligus menjaga proses tetap hidup.
    `stop` hanya untuk tes."""
    _main_id[0] = threading.get_ident()
    try:
        try:
            _activity()                                  # sekali di awal: memanaskan pyjnius, galat langsung tampak di logcat
        except Exception as err:
            print("main_loop: activity belum siap:", err)
        next_hook = 0.0
        while stop is None or not stop.is_set():
            try:
                task = _tasks.get(timeout=max(0.05, min(1.0, next_hook - time.monotonic())))
            except queue.Empty:
                task = None
            if task is not None:
                try:
                    task.result = task.fn(*task.args)
                except BaseException as err:             # dikirim balik ke thread yang menunggu
                    task.error = err
                task.done.set()
            if time.monotonic() >= next_hook:
                try:
                    ok = _hook_once()
                except Exception as err:                 # kegagalan di sini tidak boleh mematikan aplikasi
                    print("install_back_hook:", err)
                    ok = False
                next_hook = time.monotonic() + (3 if ok else 0.5)
    finally:
        _main_id[0] = None


# ----------------------------------------------------------------- simpan ke Downloads
def save_to_downloads(name: str, data: bytes, mime: str) -> None:
    """Simpan file langsung ke folder Downloads HP lewat MediaStore (Android 10+, tanpa izin penyimpanan).

    Nama yang sudah ada otomatis menjadi "nama (1).ext" oleh Android; tidak ada salinan lain di mana pun.
    Dipanggil dari thread pelayan server, jadi pekerjaan Java-nya dititipkan ke thread utama."""
    run_on_main(_save_to_downloads, name, data, mime)


def _save_to_downloads(name: str, data: bytes, mime: str) -> None:
    from jnius import autoclass
    if autoclass("android.os.Build$VERSION").SDK_INT < 29:
        raise OSError("Menyimpan ke Downloads butuh Android 10 atau lebih baru.")
    ContentValues = autoclass("android.content.ContentValues")
    Columns = autoclass("android.provider.MediaStore$MediaColumns")
    Downloads = autoclass("android.provider.MediaStore$Downloads")
    Environment = autoclass("android.os.Environment")

    resolver = _activity().getContentResolver()
    values = ContentValues()
    values.put(Columns.DISPLAY_NAME, name)
    values.put(Columns.MIME_TYPE, mime)
    values.put(Columns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
    uri = resolver.insert(Downloads.EXTERNAL_CONTENT_URI, values)
    if uri is None:
        raise OSError("Android menolak membuat file di Downloads.")
    out = resolver.openOutputStream(uri)
    try:
        out.write(data)
        out.flush()
    finally:
        out.close()


# ----------------------------------------------------------------- keluar dari aplikasi
def exit_app(delay: float = 0.3) -> None:
    """Tutup aplikasi sepenuhnya (activity ditutup, lalu proses dihentikan)."""
    def work():
        time.sleep(delay)                                # beri waktu balasan HTTP terkirim
        try:
            run_on_main(_finish, timeout=3.0)
        except Exception as err:                         # tetap lanjut hentikan proses
            print("exit_app:", err)
        time.sleep(0.4)
        os._exit(0)
    threading.Thread(target=work, daemon=True).start()


def _finish() -> None:
    _activity().finishAndRemoveTask()


# ----------------------------------------------------------------- tombol kembali
def _find_webview(view):
    """Cari WebView di dalam tampilan activity (bootstrap webview tidak membukanya ke Python)."""
    from jnius import autoclass, cast
    Class = autoclass("java.lang.Class")
    if Class.forName("android.webkit.WebView").isInstance(view):
        return cast("android.webkit.WebView", view)
    if Class.forName("android.view.ViewGroup").isInstance(view):
        group = cast("android.view.ViewGroup", view)
        for i in range(group.getChildCount()):
            found = _find_webview(group.getChildAt(i))
            if found is not None:
                return found
    return None


def _tidy(webview) -> None:
    """Dijalankan di thread UI, berulang selama aplikasi hidup.

    1) Begitu aplikasi (/app) tampil, riwayat WebView dihapus. Di bawah aplikasi masih ada halaman pembuka
       bawaan p4a (_load.html); tombol/gestur kembali yang lolos dari pendengar (mis. saat fokus WebView
       hilang) akan membawa ke sana dan layar loading jadi jalan buntu. Tanpa riwayat tidak ada lagi tujuan "kembali".
    2) WebView diminta memegang fokus lagi kalau kehilangannya, supaya pendengar tombol kembali selalu dipanggil."""
    url = webview.getUrl() or ""
    if url.split("?")[0].split("#")[0].rstrip("/").endswith("/app") and webview.canGoBack():
        webview.clearHistory()
    if not webview.hasFocus():
        webview.requestFocus()


def _tidy_runnable():
    """Runnable untuk _tidy; dibuat sekali supaya tidak menumpuk objek Java/Python tiap beberapa detik."""
    global _tidy_job
    if _tidy_job is None:
        from jnius import PythonJavaClass, java_method

        class Tidy(PythonJavaClass):
            __javainterfaces__ = ["java/lang/Runnable"]
            __javacontext__ = "app"

            @java_method("()V")
            def run(self):
                try:
                    if _hooked is not None:
                        _tidy(_hooked)
                except Exception as err:                 # gagal membersihkan tidak boleh mematikan aplikasi
                    print("tidy_webview:", err)

        _tidy_job = Tidy()
    return _tidy_job


def _hook_once() -> bool:
    """(Thread utama, dipanggil main_loop) Pasang pendengar tombol kembali di WebView. Tombol/gestur kembali diteruskan ke JavaScript
    (window.__back), supaya halaman yang mengatur: tutup popup, halaman sebelumnya, atau keluar 2x."""
    global _hooked
    from jnius import PythonJavaClass, java_method

    activity = _activity()
    webview = _find_webview(activity.getWindow().getDecorView())
    if webview is None:
        return False
    if _hooked is not None and _hooked.equals(webview):
        activity.runOnUiThread(_tidy_runnable())
        return True

    class BackListener(PythonJavaClass):
        __javainterfaces__ = ["android/view/View$OnKeyListener"]
        __javacontext__ = "app"

        @java_method("(Landroid/view/View;ILandroid/view/KeyEvent;)Z")
        def onKey(self, view, key_code, event):
            if key_code != KEYCODE_BACK:
                return False
            if event.getAction() == ACTION_UP:
                now = event.getEventTime()
                if now - _last_back[0] >= 200:           # satu tekan bisa sampai 2x ke pendengar ini: hanya yang pertama diteruskan
                    _last_back[0] = now
                    webview.evaluateJavascript("window.__back && window.__back()", None)
            return True                                  # tombol kembali selalu "dipakai" di sini

    class OnUi(PythonJavaClass):
        __javainterfaces__ = ["java/lang/Runnable"]
        __javacontext__ = "app"

        @java_method("()V")
        def run(self):
            try:                                         # WebView berlatar putih bawaan -> samakan dengan warna aplikasi
                from jnius import autoclass
                webview.setBackgroundColor(autoclass("android.graphics.Color").parseColor(LATAR_WEBVIEW))
            except Exception as err:
                print("latar_webview:", err)
            listener = BackListener()
            _keep.append(listener)
            webview.setFocusableInTouchMode(True)
            webview.setOnKeyListener(listener)
            webview.requestFocus()

    task = OnUi()
    _keep.append(task)
    activity.runOnUiThread(task)
    _hooked = webview
    activity.runOnUiThread(_tidy_runnable())
    return True
