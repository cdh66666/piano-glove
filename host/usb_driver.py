"""Read-only CP210x driver diagnostics, including USB devices without a COM port.

Windows SetupAPI can see a CP2102 with missing drivers (problem 28), while
pyserial's COM-port list cannot. This module never opens a serial handle,
installs a driver, changes a device, or requests elevation.
"""
import ctypes
from ctypes import wintypes
import re
import sys
import threading
import time

DRIVER_PAGE_URL = 'https://www.silabs.com/software-and-tools/usb-to-uart-bridge-vcp-drivers'
DRIVER_DOWNLOAD_URL = 'https://www.silabs.com/documents/public/software/CP210x_Universal_Windows_Driver.zip'
CACHE_SECONDS = 5.0
_cache = None
_cache_at = 0.0
_lock = threading.Lock()


def _is_target(hardware_id):
    return bool(re.search(r'(?:VID_10C4&PID_EA60|VID:PID=10C4:EA60)\b', str(hardware_id).upper()))


def _read_driver_version(driver_key):
    """Optional installed-version label; failure must not hide USB detection."""
    if not re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}\\\d{4}', str(driver_key)):
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                'SYSTEM\\CurrentControlSet\\Control\\Class\\' + driver_key) as key:
            value = winreg.QueryValueEx(key, 'DriverVersion')[0]
        return value if re.fullmatch(r'\d+(?:\.\d+){1,3}', str(value)) else None
    except (ImportError, OSError):
        return None


def _scan_windows_devices():
    """Return present CP210x names and Config Manager problem codes only."""
    if sys.platform != 'win32':
        raise NotImplementedError('Windows SetupAPI is not available')

    class GUID(ctypes.Structure):
        _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD),
                    ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]

    class SP_DEVINFO_DATA(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('ClassGuid', GUID),
                    ('DevInst', wintypes.DWORD), ('Reserved', ctypes.c_size_t)]

    setup = ctypes.WinDLL('setupapi', use_last_error=True)
    config = ctypes.WinDLL('cfgmgr32', use_last_error=True)
    setup.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    setup.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    setup.SetupDiEnumDeviceInfo.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(SP_DEVINFO_DATA)]
    setup.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
    setup.SetupDiGetDeviceRegistryPropertyW.argtypes = [wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA),
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(ctypes.c_ubyte),
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    setup.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
    setup.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
    setup.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
    config.CM_Get_DevNode_Status.argtypes = [ctypes.POINTER(wintypes.ULONG),
        ctypes.POINTER(wintypes.ULONG), wintypes.DWORD, wintypes.ULONG]
    config.CM_Get_DevNode_Status.restype = wintypes.ULONG

    handle = setup.SetupDiGetClassDevsW(None, 'USB', None, 0x02 | 0x04)  # PRESENT | ALLCLASSES
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())

    def property_strings(info, property_id, optional=False):
        needed, kind = wintypes.DWORD(), wintypes.DWORD()
        setup.SetupDiGetDeviceRegistryPropertyW(handle, ctypes.byref(info), property_id,
            ctypes.byref(kind), None, 0, ctypes.byref(needed))
        if not needed.value:
            if not optional and ctypes.get_last_error() not in (0, 13):
                raise ctypes.WinError(ctypes.get_last_error())
            return []
        buffer = (ctypes.c_ubyte * needed.value)()
        if not setup.SetupDiGetDeviceRegistryPropertyW(handle, ctypes.byref(info), property_id,
                ctypes.byref(kind), buffer, needed, ctypes.byref(needed)):
            if optional:
                return []
            raise ctypes.WinError(ctypes.get_last_error())
        return [part for part in bytes(buffer).decode('utf-16-le').rstrip('\0').split('\0') if part]

    devices = []
    try:
        index = 0
        while True:
            info = SP_DEVINFO_DATA()
            info.cbSize = ctypes.sizeof(info)
            if not setup.SetupDiEnumDeviceInfo(handle, index, ctypes.byref(info)):
                if ctypes.get_last_error() == 259:  # NO_MORE_ITEMS
                    break
                raise ctypes.WinError(ctypes.get_last_error())
            index += 1
            if not any(_is_target(value) for value in property_strings(info, 1)):  # HARDWAREID
                continue
            names = property_strings(info, 12, optional=True) or property_strings(info, 0, optional=True)
            flags, problem = wintypes.ULONG(), wintypes.ULONG()
            result = config.CM_Get_DevNode_Status(ctypes.byref(flags), ctypes.byref(problem), info.DevInst, 0)
            device = {'name': names[0] if names else 'CP2102 USB to UART Bridge Controller',
                      'problem_code': int(problem.value) if result == 0 else None}
            driver_keys = property_strings(info, 9, optional=True)  # SPDRP_DRIVER
            version = _read_driver_version(driver_keys[0]) if driver_keys else None
            if version:
                device['driver_version'] = version
            devices.append(device)
    finally:
        setup.SetupDiDestroyDeviceInfoList(handle)
    return devices


def classify_driver_status(devices, ports=(), error=None):
    """Classify real OS evidence without interpreting an empty COM list as missing drivers."""
    available_ports = []
    for port in ports or ():
        if isinstance(port, dict):
            target = _is_target(port.get('hwid', ''))
            name, desc = port.get('device', ''), port.get('desc', '')
        else:
            target = (getattr(port, 'vid', None), getattr(port, 'pid', None)) == (0x10C4, 0xEA60)
            name, desc = getattr(port, 'device', ''), getattr(port, 'description', '')
        if target and name:
            available_ports.append({'device': str(name), 'desc': str(desc or '')})
    # Keep only public diagnostics. Hardware instance IDs may contain a unique serial.
    devices = [dict(name=str(v.get('name') or 'CP210x USB 主控'),
                    problem_code=v.get('problem_code'),
                    **({'driver_version': str(v['driver_version'])}
                       if re.fullmatch(r'\d+(?:\.\d+){1,3}', str(v.get('driver_version', ''))) else {}))
               for v in devices or ()]
    result = dict(state='unavailable', title='暂时无法检测串口驱动',
                  message='请打开设备管理器核对 CP2102，并查看驱动安装说明。',
                  problem_code=None, devices=devices, ports=available_ports,
                  port_available=bool(available_ports), driver_page_url=DRIVER_PAGE_URL,
                  driver_download_url=DRIVER_DOWNLOAD_URL)
    if available_ports:
        result.update(state='ready', title='CP210x 串口驱动已就绪',
                      message='已找到主控串口 '+ '、'.join(v['device'] for v in available_ports)+'，可以继续连接。',
                      problem_code=0)
    elif error:
        # Do not expose raw OS errors or label enumeration failure as no device.
        result['diagnostic_error'] = str(error)
    elif not devices:
        result.update(state='unplugged', title='尚未检测到主控 USB',
                      message='请连接主控 USB 数据线；若设备管理器出现黄色感叹号，可查看驱动安装说明。')
    else:
        missing = next((v for v in devices if v['problem_code'] == 28), None)
        failed = next((v for v in devices if v['problem_code'] not in (None, 0)), None)
        if missing:
            result.update(state='missing_driver', title='已找到主控，但尚未安装串口驱动',
                          message='Windows 已检测到 CP2102（错误代码 28）。请安装 Silicon Labs CP210x 驱动，再点击重新检测。',
                          problem_code=28)
        elif failed:
            result.update(state='device_error', title='主控 USB 驱动或设备异常',
                          message='Windows 报告设备错误代码 '+str(failed['problem_code'])+'。请检查设备管理器中的设备状态；这不一定是缺少驱动。',
                          problem_code=failed['problem_code'])
        elif all(v['problem_code'] == 0 for v in devices):
            result.update(state='ready', title='Windows 已识别 CP210x 主控',
                          message='设备状态正常，正在等待 COM 串口出现；请点击重新检测。', problem_code=0)
    return result


def get_driver_status(ports=None, refresh=False):
    """Return diagnostics; cache only the read-only PnP enumeration for five seconds.

    Pass the bridge's freshly enumerated ports. COM ports are evaluated on every
    call, so a new driver installation can be recognized without waiting for the
    PnP cache. ``refresh=True`` forces a new enumeration after a user retry.
    """
    global _cache, _cache_at
    with _lock:
        now = time.monotonic()
        if refresh or _cache is None or now - _cache_at >= CACHE_SECONDS:
            try:
                _cache = (_scan_windows_devices(), None)
            except Exception as exc:
                _cache = ([], type(exc).__name__)
            _cache_at = now
        devices, error = _cache
        return classify_driver_status(devices, ports, error)
