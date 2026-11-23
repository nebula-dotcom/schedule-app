from __future__ import annotations

import os
import queue
import threading
import time

# Deteksi Android
ON_ANDROID = "ANDROID_ARGUMENT" in os.environ

# Konstanta tombol kembali dan latar WebView
KEYCODE_BACK = 4
LATAR_WEBVIEW = "#F6F8FC"
ACTION_UP = 1
# State hook WebView dan antrean tugas
_hooked = None
_keep = []
_tidy_job = None
_last_back = [0]
_tasks = queue.Queue()
_main_id = [None]


# Activity utama Android
def _activity():
    from jnius import autoclass
    return autoclass("org.kivy.android.PythonActivity").mActivity


# Tugas untuk thread utama
class _Task:
    def __init__(self, fn, args):
        self.fn, self.args = fn, args
        self.done, self.result, self.error = threading.Event(), None, None


# Jalankan fungsi di thread utama Android
def run_on_main(fn, *args, wait: bool = True, timeout: float = 30.0):
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


# Loop thread utama: tugas dan pasang hook
def main_loop(stop: threading.Event | None = None) -> None:
    _main_id[0] = threading.get_ident()
    try:
        try:
            _activity()
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
                except BaseException as err:
                    task.error = err
                task.done.set()
            if time.monotonic() >= next_hook:
                try:
                    ok = _hook_once()
                except Exception as err:
                    print("install_back_hook:", err)
                    ok = False
                next_hook = time.monotonic() + (3 if ok else 0.5)
    finally:
        _main_id[0] = None


# Simpan file ke folder Download
def save_to_downloads(name: str, data: bytes, mime: str) -> None:
    run_on_main(_save_to_downloads, name, data, mime)


# Simpan file lewat MediaStore
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


# Keluar aplikasi
def exit_app(delay: float = 0.3) -> None:
    def work():
        time.sleep(delay)
        try:
            run_on_main(_finish, timeout=3.0)
        except Exception as err:
            print("exit_app:", err)
        time.sleep(0.4)
        os._exit(0)
    threading.Thread(target=work, daemon=True).start()


# Tutup activity
def _finish() -> None:
    _activity().finishAndRemoveTask()


# Cari WebView di tampilan
def _find_webview(view):
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


# Rapikan WebView: riwayat dan fokus
def _tidy(webview) -> None:
    url = webview.getUrl() or ""
    if url.split("?")[0].split("#")[0].rstrip("/").endswith("/app") and webview.canGoBack():
        webview.clearHistory()
    if not webview.hasFocus():
        webview.requestFocus()


# Runnable perapian WebView
def _tidy_runnable():
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
                except Exception as err:
                    print("tidy_webview:", err)

        _tidy_job = Tidy()
    return _tidy_job


# Pasang tombol kembali dan latar WebView
def _hook_once() -> bool:
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
                if now - _last_back[0] >= 200:
                    _last_back[0] = now
                    webview.evaluateJavascript("window.__back && window.__back()", None)
            return True

    class OnUi(PythonJavaClass):
        __javainterfaces__ = ["java/lang/Runnable"]
        __javacontext__ = "app"

        @java_method("()V")
        def run(self):
            try:
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
