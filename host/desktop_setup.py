"""WebView2 prerequisite from the full bundle, an offline sidecar, or Microsoft's online bootstrapper."""
import hashlib
from pathlib import Path
import subprocess
import sys
import time

RUNTIME_SHA256 = '9b0142e22e8daa92855d746ae4d1e9eeef561ccaf67d1dd452165c4af3df3191'
RUNTIME_FILENAME = 'MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
RUNTIME_DOWNLOAD_URL = 'https://developer.microsoft.com/en-us/microsoft-edge/webview2/'
# Microsoft's signed Evergreen bootstrapper (go.microsoft.com/fwlink/p/?LinkId=2124703, ~2 MB);
# it downloads the runtime itself, so the lightweight EXE installs without a browser.
BOOTSTRAPPER_SHA256 = 'cf2f2445fef0c5c14e372045f84998771eeb8bb01d59be4afd00692fa160082e'
BOOTSTRAPPER_FILENAME = 'MicrosoftEdgeWebview2Setup.exe'
# The desktop selectors use :has(), implemented in Chromium 105.
MIN_RUNTIME_MAJOR = 105


def installed_runtime():
    import winreg
    suffix = r'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    found=[]
    for hive, path in ((winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\WOW6432Node\\'+suffix),
                       (winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\'+suffix),
                       (winreg.HKEY_CURRENT_USER, 'SOFTWARE\\'+suffix)):
        try:
            with winreg.OpenKey(hive, path) as key:
                version = str(winreg.QueryValueEx(key, 'pv')[0])
            parts = tuple(int(value) for value in version.split('.'))
            if len(parts) == 4 and parts > (0, 0, 0, 0):
                found.append(parts)
        except (OSError, TypeError, ValueError):
            continue
    return '.'.join(map(str,max(found))) if found else None


def supported_runtime(version):
    return bool(version) and int(version.split('.')[0]) >= MIN_RUNTIME_MAJOR


def _splash(message='安装随软件附带的微软界面组件，完成后自动打开。'):
    import tkinter as tk
    from tkinter import ttk
    window = tk.Tk()
    window.title('钢琴手套')
    window.geometry('410x138')
    window.resizable(False, False)
    window.configure(bg='#e5ebf1')
    window.protocol('WM_DELETE_WINDOW', lambda: None)
    tk.Label(window, text='正在完成首次启动准备', font=('Microsoft YaHei UI', 15),
             bg='#e5ebf1', fg='#24394c').pack(pady=(23, 8))
    tk.Label(window, text=message,
             font=('Microsoft YaHei UI', 10), bg='#e5ebf1', fg='#52687c').pack()
    progress = ttk.Progressbar(window, mode='indeterminate', length=350)
    progress.pack(pady=14)
    progress.start(12)
    window.update()
    return window


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_runtime(asset_root, show_progress=True, executable_dir=None):
    version = installed_runtime()
    if supported_runtime(version):
        return dict(installed=False, version=version)
    bundled = Path(asset_root) / 'assets' / 'runtime' / RUNTIME_FILENAME
    sidecar = Path(executable_dir if executable_dir is not None else Path(sys.executable).resolve().parent) / RUNTIME_FILENAME
    package = bundled if bundled.is_file() else sidecar
    # No offline installer: fall back to Microsoft's bundled online bootstrapper.
    online = not package.is_file()
    if online:
        package = Path(asset_root) / 'assets' / 'runtime' / BOOTSTRAPPER_FILENAME
        if not package.is_file():
            raise RuntimeError('未检测到可用的 WebView2 界面组件。\n'
                               '离线首次使用：把随附的 '+RUNTIME_FILENAME+' 放在主程序旁，再打开软件。\n'
                               '联网首次使用：先从微软官网安装 WebView2，再重新打开软件。\n'+RUNTIME_DOWNLOAD_URL)
    if _sha256_file(package) != (BOOTSTRAPPER_SHA256 if online else RUNTIME_SHA256):
        raise RuntimeError('微软界面组件校验失败，请重新获取随本版提供的离线组件或完整版 EXE。')
    from usb_driver_install import _verify_catalog
    _verify_catalog(package)
    splash = _splash('正在从微软下载并安装界面组件（需联网，约 1–3 分钟），完成后自动打开。' if online else
                     '安装本程序旁的微软界面组件，完成后自动打开。' if package == sidecar else
                     '安装随软件附带的微软界面组件，完成后自动打开。') if show_progress else None
    try:
        # Microsoft's standalone installer supports per-user installation when
        # called without elevation; it installs only because the runtime is absent.
        child = subprocess.Popen([str(package), '/silent', '/install'],
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while child.poll() is None:
            if splash:
                splash.update()
            time.sleep(.1)
        version = installed_runtime()
        if not supported_runtime(version):
            raise RuntimeError('微软界面组件未完成安装（代码 '+str(child.returncode)+'），'+
                               ('请确认电脑已连上网络，再重新打开软件。' if online else '请重新打开软件再试。'))
        return dict(installed=True, version=version, installer_exit=child.returncode)
    finally:
        if splash:
            splash.destroy()
