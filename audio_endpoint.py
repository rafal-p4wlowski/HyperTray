"""Volume of the headset's Windows audio endpoints (speakers and microphone).

The headset firmware has no volume or microphone gain command; NGENUITY sets
these on the Windows side as well. This talks to Windows Core Audio
(IMMDeviceEnumerator / IAudioEndpointVolume) through plain ctypes COM calls,
so no extra package is needed. Calls are cheap and are made on the GUI thread.
"""
import ctypes
import logging
import sys
from ctypes import POINTER, byref, c_float, c_int, c_uint, c_void_p, c_wchar_p

log = logging.getLogger(__name__)

DEVICE_NAME = "HyperX Cloud III Wireless"
RENDER, CAPTURE = 0, 1            # EDataFlow: eRender, eCapture
DEVICE_STATE_ACTIVE = 1
CLSCTX_ALL = 0x17
STGM_READ = 0
VT_LPWSTR = 31
COINIT_APARTMENTTHREADED = 0x2

# IUnknown: 0 QueryInterface, 1 AddRef, 2 Release
ENUM_AUDIO_ENDPOINTS = 3          # IMMDeviceEnumerator
COLLECTION_COUNT, COLLECTION_ITEM = 3, 4
DEVICE_ACTIVATE, DEVICE_OPEN_PROPERTY_STORE = 3, 4
PROPERTY_STORE_GET_VALUE = 5
SET_MASTER_SCALAR, GET_MASTER_SCALAR = 7, 9      # IAudioEndpointVolume


class GUID(ctypes.Structure):
    _fields_ = [("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16), ("data3", ctypes.c_uint16),
                ("data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text):
        h = text.replace("-", "")
        return cls(int(h[:8], 16), int(h[8:12], 16), int(h[12:16], 16),
                   (ctypes.c_ubyte * 8)(*bytes.fromhex(h[16:])))


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_uint32)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("reserved", ctypes.c_ushort * 3), ("value", c_void_p),
                ("pad", c_void_p)]


CLSID_MMDEVICE_ENUMERATOR = GUID.parse("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDEVICE_ENUMERATOR = GUID.parse("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAUDIO_ENDPOINT_VOLUME = GUID.parse("5CDF2C82-841E-4546-9722-0CF74078229A")
# The adapter name ("HyperX Cloud III Wireless"); the endpoint name is localised ("Mikrofon (...)").
PKEY_DEVICE_INTERFACE_FRIENDLY_NAME = PROPERTYKEY(GUID.parse("026E516E-B814-414B-83CD-856D6FEF4822"), 2)


def _method(ptr, index, *argtypes):
    """Bound COM method number `index` of interface pointer `ptr`."""
    vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)
    fn = proto(vtable[index])
    return lambda *args: fn(ptr, *args)


def _release(ptr):
    if ptr:
        vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
        ctypes.WINFUNCTYPE(c_uint, c_void_p)(vtable[2])(ptr)


class EndpointVolume:
    """Master volume of one endpoint. Raises OSError when the
    endpoint went away (headset dongle unplugged)."""

    def __init__(self, ptr):
        self._ptr = ptr

    def volume(self):
        level = c_float()
        _method(self._ptr, GET_MASTER_SCALAR, POINTER(c_float))(byref(level))
        return round(level.value * 100)

    def set_volume(self, percent):
        _method(self._ptr, SET_MASTER_SCALAR, c_float, c_void_p)(max(0, min(100, percent)) / 100, None)

    def close(self):
        _release(self._ptr)
        self._ptr = None

    def __del__(self):
        if self._ptr:
            self.close()


def _init_com():
    # Qt already initialised the GUI thread (S_FALSE / RPC_E_CHANGED_MODE are fine).
    try:
        ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    except OSError:
        pass


def _adapter_name(device):
    store = c_void_p()
    _method(device, DEVICE_OPEN_PROPERTY_STORE, c_uint, POINTER(c_void_p))(STGM_READ, byref(store))
    try:
        var = PROPVARIANT()
        _method(store, PROPERTY_STORE_GET_VALUE, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))(
            byref(PKEY_DEVICE_INTERFACE_FRIENDLY_NAME), byref(var))
        try:
            return c_wchar_p(var.value).value if var.vt == VT_LPWSTR and var.value else ""
        finally:
            ctypes.windll.ole32.PropVariantClear(byref(var))
    finally:
        _release(store)


def find_endpoints(name=DEVICE_NAME):
    """{RENDER: EndpointVolume, CAPTURE: EndpointVolume} for the active endpoints
    of the named audio device; missing flows are left out."""
    if sys.platform != "win32":
        return {}
    _init_com()
    found = {}
    enumerator = c_void_p()
    try:
        ole32 = ctypes.windll.ole32
        ole32.CoCreateInstance.argtypes = [POINTER(GUID), c_void_p, c_uint, POINTER(GUID), POINTER(c_void_p)]
        ole32.CoCreateInstance.restype = ctypes.HRESULT
        ole32.CoCreateInstance(byref(CLSID_MMDEVICE_ENUMERATOR), None, CLSCTX_ALL,
                               byref(IID_IMMDEVICE_ENUMERATOR), byref(enumerator))
        for flow in (RENDER, CAPTURE):
            collection = c_void_p()
            _method(enumerator, ENUM_AUDIO_ENDPOINTS, c_int, c_uint, POINTER(c_void_p))(
                flow, DEVICE_STATE_ACTIVE, byref(collection))
            try:
                count = c_uint()
                _method(collection, COLLECTION_COUNT, POINTER(c_uint))(byref(count))
                for i in range(count.value):
                    device = c_void_p()
                    _method(collection, COLLECTION_ITEM, c_uint, POINTER(c_void_p))(i, byref(device))
                    try:
                        if flow in found or _adapter_name(device) != name:
                            continue
                        volume = c_void_p()
                        _method(device, DEVICE_ACTIVATE, POINTER(GUID), c_uint, c_void_p, POINTER(c_void_p))(
                            byref(IID_IAUDIO_ENDPOINT_VOLUME), CLSCTX_ALL, None, byref(volume))
                        found[flow] = EndpointVolume(volume.value)
                    finally:
                        _release(device)
            finally:
                _release(collection)
    except OSError as e:
        log.warning("Cannot read the Windows audio devices: %s", e)
    finally:
        _release(enumerator)
    return found
