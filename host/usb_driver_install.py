"""Explicit, single-flight installation of the official CP210x Windows driver.

No installation runs at import, startup, polling, or USB reconnection. The caller
must invoke start() after the user clicks the installation button. Windows owns
the UAC prompt and driver-signature enforcement; no existing driver is removed.
"""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path, PurePosixPath
import platform
import sys
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid
import zipfile

from usb_driver import DRIVER_DOWNLOAD_URL, DRIVER_PAGE_URL, get_driver_status

# Official Microsoft Update Catalog mirror of the vendor's 11.5.0.417 package.
# Discovered from update 34213758-173c-47ec-951d-16b2c9463881. The signed INF
# includes the vendor's x86/x64/ARM/ARM64 payloads and USB VID_10C4&PID_EA60.
MICROSOFT_DRIVER_URL = 'https://catalog.s.download.windowsupdate.com/c/msdownload/update/driver/drvs/2026/02/3bc68c22-eb83-4383-b451-4c581d06d3fb_6092f1062939e09f524b5d8e9108530f7f516f13.cab'
MICROSOFT_DRIVER_SHA256 = '7ea8a03769a05c7bb78718c360b5079be354ed6437623408d51b9c1e8f5a122a'


class InstallationCancelled(Exception):
    pass


def _diagnose():
    from serial.tools.list_ports import comports
    return get_driver_status(list(comports()), refresh=True)


def _download_from(url, archive, microsoft=False):
    request = Request(url, headers={'User-Agent': 'PianoGlove-DriverSetup/1.0'})
    with urlopen(request, timeout=30) as response, archive.open('wb') as target:
        destination = urlsplit(response.geturl())
        host = destination.hostname or ''
        trusted = host.endswith('.download.windowsupdate.com') if microsoft else host == 'silabs.com' or host.endswith('.silabs.com')
        if destination.scheme != 'https' or not trusted:
            raise ValueError('official_download_redirect_rejected')
        size = 0
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > 32 * 1024 * 1024:
                raise ValueError('driver_package_too_large')
            target.write(chunk)
    if microsoft and hashlib.sha256(archive.read_bytes()).hexdigest() != MICROSOFT_DRIVER_SHA256:
        raise ValueError('microsoft_driver_hash_mismatch')
    return archive


def _native_architecture():
    return (os.environ.get('PROCESSOR_ARCHITEW6432') or
            os.environ.get('PROCESSOR_ARCHITECTURE') or platform.machine()).upper()


def _download_package(directory):
    try:
        return _download_from(DRIVER_DOWNLOAD_URL, directory / 'CP210x_Universal_Windows_Driver.zip')
    except Exception:
        # Silicon Labs' CDN can reject otherwise normal clients with HTTP403.
        # Use the same vendor driver distributed by Microsoft's official
        # catalog, with an immutable URL and independently recorded SHA256.
        if _native_architecture() not in ('AMD64', 'X86_64'):
            raise
        return _download_from(MICROSOFT_DRIVER_URL, directory / 'CP210x_Windows_Update.cab', microsoft=True)


def _expand_cab(archive, destination):
    executable = Path(os.environ['SystemRoot']) / 'System32' / 'expand.exe'
    result = subprocess.run([str(executable), '-F:*', str(archive), str(destination)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('microsoft_driver_cab_extract_failed')


def _extract_package(archive, directory):
    destination = directory / 'package'
    destination.mkdir()
    if archive.suffix.lower() == '.cab':
        if hashlib.sha256(archive.read_bytes()).hexdigest() != MICROSOFT_DRIVER_SHA256:
            raise ValueError('microsoft_driver_hash_mismatch')
        _expand_cab(archive, destination)
    else:
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
            if len(entries) > 1024 or sum(v.file_size for v in entries) > 128 * 1024 * 1024:
                raise ValueError('driver_package_too_large')
            paths = set()
            for entry in entries:
                relative = PurePosixPath(entry.filename.replace('\\', '/'))
                if relative.is_absolute() or '..' in relative.parts or ':' in entry.filename:
                    raise ValueError('unsafe_driver_archive_path')
                output = destination.joinpath(*relative.parts).resolve()
                if not output.is_relative_to(destination.resolve()) or output in paths:
                    raise ValueError('unsafe_driver_archive_path')
                paths.add(output)
            if package.testzip() is not None:
                raise ValueError('driver_package_corrupt')
            package.extractall(destination)
    candidates = [p for p in destination.rglob('*') if p.name.lower() == 'silabser.inf']
    if len(candidates) != 1:
        raise ValueError('official_driver_inf_missing')
    inf = candidates[0]
    catalogs = [p for p in inf.parent.iterdir() if p.name.lower() == 'silabser.cat']
    if len(catalogs) != 1:
        raise ValueError('official_driver_catalog_missing')
    raw = inf.read_bytes()
    text = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig', errors='replace')
    if 'vid_10c4&pid_ea60' not in text.lower():
        raise ValueError('cp2102_hardware_id_missing')
    return inf, catalogs[0]


def _verify_catalog(path):
    """Use Windows Authenticode trust verification before requesting elevation."""
    if sys.platform != 'win32':
        raise OSError('Windows is required')

    class GUID(ctypes.Structure):
        _fields_ = [('data', ctypes.c_ubyte * 16)]

    class FILE_INFO(ctypes.Structure):
        _fields_ = [('cbStruct', wintypes.DWORD), ('pcwszFilePath', wintypes.LPCWSTR),
                    ('hFile', wintypes.HANDLE), ('pgKnownSubject', ctypes.c_void_p)]

    class TRUST_DATA(ctypes.Structure):
        _fields_ = [('cbStruct', wintypes.DWORD), ('pPolicyCallbackData', ctypes.c_void_p),
                    ('pSIPClientData', ctypes.c_void_p), ('dwUIChoice', wintypes.DWORD),
                    ('fdwRevocationChecks', wintypes.DWORD), ('dwUnionChoice', wintypes.DWORD),
                    ('pFile', ctypes.POINTER(FILE_INFO)), ('dwStateAction', wintypes.DWORD),
                    ('hWVTStateData', wintypes.HANDLE), ('pwszURLReference', wintypes.LPCWSTR),
                    ('dwProvFlags', wintypes.DWORD), ('dwUIContext', wintypes.DWORD),
                    ('pSignatureSettings', ctypes.c_void_p)]

    action = GUID.from_buffer_copy(uuid.UUID('00aac56b-cd44-11d0-8cc2-00c04fc295ee').bytes_le)
    file = FILE_INFO(ctypes.sizeof(FILE_INFO), str(path), None, None)
    data = TRUST_DATA()
    data.cbStruct = ctypes.sizeof(data)
    data.dwUIChoice = 2  # WTD_UI_NONE; no trust UI or bypass prompt.
    data.dwUnionChoice = 1  # WTD_CHOICE_FILE
    data.pFile = ctypes.pointer(file)
    data.dwStateAction = 1  # WTD_STATEACTION_VERIFY
    library = ctypes.WinDLL('wintrust', use_last_error=True)
    library.WinVerifyTrust.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), ctypes.POINTER(TRUST_DATA)]
    library.WinVerifyTrust.restype = wintypes.LONG
    try:
        result = library.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(data))
        if result != 0:
            raise ValueError('driver_signature_not_trusted')
    finally:
        data.dwStateAction = 2  # WTD_STATEACTION_CLOSE
        library.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(data))


def _install_inf(inf, update):
    """Ask Windows to elevate its own PnP utility, then wait for that process."""
    if sys.platform != 'win32':
        raise OSError('Windows is required')

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
                    ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR),
                    ('lpParameters', wintypes.LPCWSTR), ('lpDirectory', wintypes.LPCWSTR),
                    ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
                    ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR),
                    ('hkeyClass', wintypes.HANDLE), ('dwHotKey', wintypes.DWORD),
                    ('hIcon', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]

    system = Path(os.environ['SystemRoot']) / 'System32'
    native = Path(os.environ['SystemRoot']) / 'Sysnative' / 'pnputil.exe'
    executable = native if native.exists() else system / 'pnputil.exe'
    if not executable.is_file():
        raise OSError('Windows pnputil.exe not found')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFO)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    execute = SHELLEXECUTEINFO()
    execute.cbSize = ctypes.sizeof(execute)
    execute.fMask = 0x40 | 0x100  # NOCLOSEPROCESS | NOASYNC
    execute.lpVerb = 'runas'
    execute.lpFile = str(executable)
    execute.lpParameters = '/add-driver "' + str(inf) + '" /install'
    execute.lpDirectory = str(inf.parent)
    execute.nShow = 0  # Hide only the utility console; Windows still presents UAC.
    update(phase='authorize', progress=55, message='请在 Windows 管理员授权窗口中点击“是”，随后会自动完成。')
    if not shell.ShellExecuteExW(ctypes.byref(execute)):
        code = ctypes.get_last_error()
        if code == 1223:
            raise InstallationCancelled()
        raise ctypes.WinError(code)
    if not execute.hProcess:
        raise OSError('Windows did not return an installer process')
    try:
        update(phase='install', progress=70, message='正在安装官方串口驱动…')
        # This is the dedicated installer thread. Do not start another installer
        # while Windows is still working or awaiting its administrator prompt.
        if kernel.WaitForSingleObject(execute.hProcess, 0xffffffff) != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(execute.hProcess, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value
    finally:
        kernel.CloseHandle(execute.hProcess)


def _rescan_devices():
    # PnPUtil /install already applies the driver to matching present devices.
    # Request one additional device-tree refresh if this process has permission.
    config = ctypes.WinDLL('cfgmgr32', use_last_error=True)
    node = wintypes.DWORD()
    config.CM_Locate_DevNodeW.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.ULONG]
    config.CM_Locate_DevNodeW.restype = wintypes.ULONG
    config.CM_Reenumerate_DevNode.argtypes = [wintypes.DWORD, wintypes.ULONG]
    config.CM_Reenumerate_DevNode.restype = wintypes.ULONG
    if config.CM_Locate_DevNodeW(ctypes.byref(node), None, 0) == 0:
        config.CM_Reenumerate_DevNode(node, 0)


class USBDriverInstaller:
    def __init__(self):
        self._lock = threading.RLock()
        self._data = dict(busy=False, state='idle', phase='idle', progress=0,
                          message='', error='', verified=False, ports=[], restart_required=False)

    def status(self):
        with self._lock:
            return dict(self._data, ports=[dict(p) for p in self._data['ports']],
                        driver_page_url=DRIVER_PAGE_URL, driver_download_url=DRIVER_DOWNLOAD_URL)

    def _update(self, **values):
        with self._lock:
            self._data.update(values)

    def start(self):
        with self._lock:
            if self._data['busy']:
                return self.status()
            self._data.update(busy=True, state='running', phase='detect', progress=5,
                              message='正在检查主控与驱动…', error='', verified=False,
                              restart_required=False, ports=[])
            worker = threading.Thread(target=self._worker, name='piano-usb-driver', daemon=True)
            try:
                worker.start()
            except Exception:
                self._data.update(busy=False, state='failed', phase='failed',
                                  error='installer_start_failed', message='驱动安装服务未能启动，请重试。')
            return self.status()

    def _worker(self):
        stage = 'detect'
        try:
            if sys.platform != 'win32':
                self._update(state='unsupported', phase='complete', message='自动安装仅用于 Windows 10 / 11。')
                return
            diagnostic = _diagnose()
            if diagnostic['state'] == 'ready' and diagnostic.get('port_available'):
                self._update(state='ready', phase='complete', progress=100, verified=True,
                             ports=diagnostic.get('ports', []), message='串口驱动已就绪，正在连接主控。')
                return
            if diagnostic['state'] not in ('missing_driver', 'device_error'):
                self._update(state='waiting_usb' if diagnostic['state'] == 'unplugged' else 'waiting_port',
                             phase='complete', message=diagnostic.get('message', '请连接主控 USB 后重新检测。'))
                return
            base = Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()) / 'PianoGloveSoftware' / 'drivers'
            base.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix='cp210x-', dir=base))
            stage = 'download'
            self._update(phase=stage, progress=15, message='正在从 Silicon Labs 下载官方驱动…')
            archive = _download_package(directory)
            stage = 'verify'
            self._update(phase=stage, progress=40, message='正在验证驱动包和数字签名…')
            inf, catalog = _extract_package(archive, directory)
            _verify_catalog(catalog)
            self._update(package_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                         package_source='microsoft_update_catalog' if archive.suffix.lower() == '.cab' else 'silicon_labs')
            stage = 'install'
            code = _install_inf(inf, self._update)
            if code not in (0, 3010):
                self._update(state='failed', phase='failed', error='windows_install_failed',
                             message='Windows 未完成驱动安装（返回代码 '+str(code)+'）。可重试或查看官方安装说明。')
                return
            _rescan_devices()
            self._update(phase='detect', progress=90, message='驱动安装已结束，正在等待 COM 串口出现…')
            deadline = time.monotonic() + 20
            while True:
                diagnostic = _diagnose()
                if diagnostic['state'] == 'ready' and diagnostic.get('port_available'):
                    self._update(state='ready', phase='complete', progress=100, verified=True,
                                 ports=diagnostic.get('ports', []), message='驱动已安装并检测到串口，正在自动连接。')
                    return
                if time.monotonic() >= deadline:
                    break
                time.sleep(.5)
            self._update(state='restart_required' if code == 3010 else 'waiting_port', phase='complete',
                         progress=95, restart_required=code == 3010,
                         message='Windows 要求重启电脑后才能使用新驱动；请保存工作后手动重启。' if code == 3010 else
                         '安装已结束，尚未检测到 COM 口。请重新插拔主控 USB，页面会继续检测。')
        except InstallationCancelled:
            self._update(state='cancelled', phase='complete', error='cancelled',
                         message='Windows 管理员授权已取消。需要时可再次点击自动安装。')
        except Exception:
            messages = {'detect': '暂时无法核对 USB 设备，请重新检测。',
                        'download': '官方下载未完成，请检查网络后重试，或打开官方驱动页面。',
                        'verify': '驱动包或数字签名验证未通过，未执行安装。请重新下载官方驱动。',
                        'install': 'Windows 未确认安装完成，请重新检测或查看官方安装说明。'}
            self._update(state='failed', phase='failed', error=stage+'_failed', message=messages[stage])
        finally:
            self._update(busy=False)
