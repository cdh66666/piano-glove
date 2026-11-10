"""Measure cold/hot startup of the customer executable.

Usage:
  python tools/measure_startup.py <exe-path> [runs]

Reports, for each run:
  * `spawn_ms`   – process creation returned
  * `window_ms`  – first top-level window of that PID appeared (hidden counts)
  * `total_ms`   – process exited (only when --self-test style arg is passed)

Kept dependency-free: no psutil, only ctypes + subprocess, so it runs on the
same interpreters used for packaging.
"""
import ctypes
import ctypes.wintypes as wt
import json
import subprocess
import sys
import time
from pathlib import Path

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]


def _window_pids():
    found = []

    def callback(hwnd, _):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append(pid.value)
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(callback), 0)
    return found


def measure(exe, args, timeout=180):
    started = time.perf_counter()
    proc = subprocess.Popen([str(exe), *args],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            cwd=str(Path(exe).parent))
    spawn_ms = (time.perf_counter() - started) * 1000
    window_ms = None
    while time.perf_counter() - started < timeout:
        if proc.poll() is not None:
            break
        if window_ms is None and proc.pid in _window_pids():
            window_ms = (time.perf_counter() - started) * 1000
        if window_ms is not None:
            break
        time.sleep(0.02)
    # Let a --self-test process finish so the exit time is comparable.
    if proc.poll() is None and window_ms is None:
        proc.wait(timeout=timeout)
    total_ms = (time.perf_counter() - started) * 1000
    if proc.poll() is None:
        proc.kill()
        proc.wait()
    return dict(spawn_ms=round(spawn_ms), window_ms=None if window_ms is None else round(window_ms),
                total_ms=round(total_ms), pid=proc.pid)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    exe = Path(sys.argv[1]).resolve()
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    extra = sys.argv[3:]
    results = []
    for index in range(1, runs + 1):
        row = measure(exe, extra)
        row.update(run=index)
        results.append(row)
        print(json.dumps(row, ensure_ascii=False))
    windows = [row['window_ms'] for row in results if row['window_ms']]
    if windows:
        print('window median: %d ms' % sorted(windows)[len(windows) // 2])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
