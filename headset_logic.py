import hid
import time

# --- HID CONSTANTS ---
VENDOR_ID = 0x03F0
PRODUCT_IDS = [0x05B7, 0x0C9D]

CMD_GET_WIRELESS_STATUS = 0x82
CMD_GET_SIDE_TONE       = 0x84
CMD_GET_AUTO_SHUTDOWN   = 0x85
CMD_GET_MUTE            = 0x86
CMD_GET_BATTERY         = 0x89
CMD_GET_CHARGING        = 0x8A
CMD_GET_SIDE_TONE_VOL   = 0x88

CMD_SET_SIDE_TONE       = 0x01
CMD_SET_AUTO_SHUTDOWN   = 0x02
CMD_SET_MUTE            = 0x03
CMD_SET_SIDE_TONE_VOL   = 0x05

RESP_MUTE            = 0x0A
RESP_WIRELESS_STATUS = 0x0B
RESP_CHARGING        = 0x0C
RESP_BATTERY         = 0x0D

def find_device():
    try:
        devices = hid.enumerate()
        matching = [d for d in devices if d['vendor_id'] == VENDOR_ID and d['product_id'] in PRODUCT_IDS]
        matching.sort(key=lambda x: x['usage_page'], reverse=True)
        for info in matching:
            try:
                device = hid.device()
                device.open_path(info['path'])
                return device
            except: continue
    except: pass
    return None

def send_packet(device, cmd, data=0x00):
    packet = [0x66, cmd, data] + [0x00] * 59 
    try:
        device.write(packet)
        return True
    except: return False

def read_response(device, timeout=1000):
    try:
        res = device.read(64, timeout)
        if res and res[0] == 0x66:
            return list(res)
        return None
    except: return None

def get_battery(device):
    if send_packet(device, CMD_GET_BATTERY):
        time.sleep(0.05)
        data = read_response(device)
        if data and data[1] in [CMD_GET_BATTERY, RESP_BATTERY]:
            if data[2] != 0 or data[3] != 0:
                return data[4]
    return None

def get_charging(device):
    for _ in range(2):
        if send_packet(device, CMD_GET_CHARGING):
            time.sleep(0.2)
            data = read_response(device)
            if data and data[1] in [CMD_GET_CHARGING, RESP_CHARGING]:
                mapping = {0: "Not charging", 1: "Charging", 2: "Full"}
                return mapping.get(int(data[2]), "Unknown")
        time.sleep(0.2)
    return None

def get_mute(device):
    if send_packet(device, CMD_GET_MUTE):
        time.sleep(0.05)
        data = read_response(device)
        if data and data[1] in [CMD_GET_MUTE, RESP_MUTE]:
            return data[2] == 1
    return None

def set_mute(device, mute):
    return send_packet(device, CMD_SET_MUTE, 1 if mute else 0)

def get_side_tone(device):
    if send_packet(device, CMD_GET_SIDE_TONE):
        time.sleep(0.05)
        data = read_response(device)
        if data and data[1] == CMD_GET_SIDE_TONE:
            return data[2] == 1
    return None

def set_side_tone(device, enable):
    return send_packet(device, CMD_SET_SIDE_TONE, 1 if enable else 0)

def get_side_tone_volume(device):
    if send_packet(device, CMD_GET_SIDE_TONE_VOL):
        time.sleep(0.05)
        data = read_response(device)
        if data and data[1] == CMD_GET_SIDE_TONE_VOL:
            return data[2]
    return None

def set_side_tone_volume(device, volume):
    return send_packet(device, CMD_SET_SIDE_TONE_VOL, volume)

def get_auto_shutdown(device):
    if send_packet(device, CMD_GET_AUTO_SHUTDOWN):
        time.sleep(0.05)
        data = read_response(device)
        if data and data[1] == CMD_GET_AUTO_SHUTDOWN:
            return data[2]
    return None

def set_auto_shutdown(device, minutes):
    return send_packet(device, CMD_SET_AUTO_SHUTDOWN, minutes)

def get_wireless_status(device):
    if send_packet(device, CMD_GET_WIRELESS_STATUS):
        time.sleep(0.05)
        data = read_response(device)
        if data and data[1] in [CMD_GET_WIRELESS_STATUS, RESP_WIRELESS_STATUS]:
            return data[2] == 1
    return None
