import sys
import threading
import time
import signal
from typing import Optional
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer, QCoreApplication

from headset_logic import (
    find_device, get_battery, get_charging, get_mute, set_mute,
    get_side_tone, set_side_tone, get_side_tone_volume, set_side_tone_volume,
    get_auto_shutdown, set_auto_shutdown, get_wireless_status
)
from ui_components import get_battery_color, create_qicon, DARK_MENU_STYLE

# --- WORKER THREAD ---
class HeadsetWorker(QObject):
    updated = pyqtSignal(dict)
    
    def __init__(self, lock):
        super().__init__()
        self.lock = lock
        self.device = None
        self.failure_count = 0
        self.timer: Optional[QTimer] = None
        self.state = {
            "battery": None,
            "charging": "No data",
            "muted": False,
            "side_tone": False,
            "side_tone_vol": 0,
            "auto_shutdown": 0,
            "connected": False
        }

    def setup_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_logic_and_emit)
        self.timer.start(300000) # Every 5 minutes
        self.update_logic_and_emit()

    def cleanup(self):
        """Called within the worker thread before exit."""
        if self.timer:
            self.timer.stop()
            self.timer.deleteLater()
        with self.lock:
            if self.device:
                try:
                    self.device.close()
                except: pass
                self.device = None

    def update_logic_and_emit(self):
        self.update_logic()
        self.updated.emit(self.state.copy())

    def _clear_state(self):
        self.state["battery"] = None
        self.state["charging"] = "No data"
        self.state["connected"] = False

    def change_mute(self, muted):
        if self.device:
            with self.lock:
                if set_mute(self.device, muted):
                    self.state["muted"] = muted
                    time.sleep(0.5)
                    self.update_logic_and_emit()

    def change_side_tone(self, enabled):
        if self.device:
            with self.lock:
                if set_side_tone(self.device, enabled):
                    self.state["side_tone"] = enabled
                    self.update_logic_and_emit()

    def change_side_tone_vol(self, vol):
        if self.device:
            with self.lock:
                if set_side_tone_volume(self.device, vol):
                    self.state["side_tone_vol"] = vol
                    self.update_logic_and_emit()

    def change_shutdown(self, mins):
        if self.device:
            with self.lock:
                if set_auto_shutdown(self.device, mins):
                    self.state["auto_shutdown"] = mins
                    self.update_logic_and_emit()

    def update_logic(self):
        with self.lock:
            if not self.device:
                self.device = find_device()
                if not self.device:
                    self._clear_state()
                    return
            try:
                battery = get_battery(self.device)
                if battery is not None:
                    self.state["battery"] = battery
                    self.state["connected"] = True
                    self.failure_count = 0
                else:
                    wireless = get_wireless_status(self.device)
                    if wireless == 0:
                        self._clear_state()
                        return
                    self.failure_count += 1
                    if self.failure_count > 5: raise Exception()

                if self.state["connected"]:
                    time.sleep(0.1)
                    val = get_charging(self.device)
                    if val: self.state["charging"] = val
                    time.sleep(0.1)
                    val = get_mute(self.device)
                    if val is not None: self.state["muted"] = val
                    time.sleep(0.1)
                    val = get_side_tone(self.device)
                    if val is not None: self.state["side_tone"] = val
                    time.sleep(0.1)
                    val = get_side_tone_volume(self.device)
                    if val is not None: self.state["side_tone_vol"] = val
                    time.sleep(0.1)
                    val = get_auto_shutdown(self.device)
                    if val is not None: self.state["auto_shutdown"] = val
            except:
                self.failure_count = 0
                try: 
                    if self.device: self.device.close()
                except: pass
                self.device = None
                self._clear_state()

# --- MAIN APP ---
class HeadsetApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(False)
        self.lock = threading.RLock()
        self.worker = HeadsetWorker(self.lock)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.setup_timer)
        self.worker.updated.connect(self.sync_state)
        
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(create_qicon("...", "#9CA3AF"))
        self.menu = QMenu()
        self.menu.setStyleSheet(DARK_MENU_STYLE)
        self.tray.setContextMenu(self.menu)
        self.state = {}
        self.tray.show()
        self.thread.start()
        
        # Periodic timer to allow Python to process SIGINT/KeyboardInterrupt
        self.interrupt_timer = QTimer()
        self.interrupt_timer.start(500)
        self.interrupt_timer.timeout.connect(lambda: None) 

    def sync_state(self, state):
        self.state = state
        self.refresh_menu()
        self.update_icon()

    def update_icon(self):
        bat = self.state.get("battery")
        color = get_battery_color(bat)
        text = str(bat) if bat is not None else "..."
        self.tray.setIcon(create_qicon(text, color))
        if bat is not None:
            self.tray.setToolTip(f"Charging status: {self.state['charging']}\nBattery level: {bat}%")
        else:
            self.tray.setToolTip("Not connected")

    def refresh_menu(self):
        self.menu.clear()
        
        charging_info = QAction(f"Charging status: {self.state['charging']}", self)
        charging_info.setEnabled(False)
        self.menu.addAction(charging_info)
        
        bat = self.state.get('battery')
        bat_str = f"{bat}%" if bat else "---"
        battery_info = QAction(f"Battery level: {bat_str}", self)
        battery_info.setEnabled(False)
        self.menu.addAction(battery_info)
        
        mic_info = QAction(f"Mic connected: {'Yes' if self.state['connected'] else 'No'}", self)
        mic_info.setEnabled(False)
        self.menu.addAction(mic_info)
        
        self.menu.addSeparator()
        
        mute_text = f"Muted: {'Yes' if self.state['muted'] else 'No'}"
        mute_act = QAction(mute_text, self)
        mute_act.setCheckable(True)
        mute_act.setChecked(self.state['muted'])
        mute_act.triggered.connect(lambda: self.worker.change_mute(not self.state['muted']))
        self.menu.addAction(mute_act)
        
        self.menu.addSeparator()
        
        st_text = f"Side tone: {'ON' if self.state['side_tone'] else 'OFF'}"
        st_act = QAction(st_text, self)
        st_act.setCheckable(True)
        st_act.setChecked(self.state['side_tone'])
        st_act.triggered.connect(lambda: self.worker.change_side_tone(not self.state['side_tone']))
        self.menu.addAction(st_act)
        
        vol_menu = self.menu.addMenu("Side tone volume")
        vol_menu.setStyleSheet(DARK_MENU_STYLE)
        for v in [0, 50, 100, 200]:
            act = QAction(str(v), self)
            act.setCheckable(True)
            act.setChecked(self.state['side_tone_vol'] == v)
            act.triggered.connect(lambda chk, vol=v: self.worker.change_side_tone_vol(vol))
            vol_menu.addAction(act)
            
        self.menu.addSeparator()
        
        sd_menu = self.menu.addMenu("Automatic shutdown")
        sd_menu.setStyleSheet(DARK_MENU_STYLE)
        shutdown_options = [
            (0, "Disabled"), 
            (5, "5 min"), 
            (10, "10 min"), 
            (15, "15 min"), 
            (30, "30 min"), 
            (45, "45 min"), 
            (60, "1 hour"), 
            (90, "1.5 hours"), 
            (120, "2 hours")
        ]
        for mins, label in shutdown_options:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.state['auto_shutdown'] == mins)
            act.triggered.connect(lambda chk, m=mins: self.worker.change_shutdown(m))
            sd_menu.addAction(act)
            
        self.menu.addSeparator()
        
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self.on_quit)
        self.menu.addAction(quit_act)

    def on_quit(self):
        # Cleanup the worker in its own thread
        self.worker.deleteLater()
        
        # Stop and wait for the thread
        self.thread.quit()
        self.thread.wait(2000)
            
        self.quit()

if __name__ == "__main__":
    app = HeadsetApp(sys.argv)
    
    # Handle Ctrl+C (KeyboardInterrupt)
    signal.signal(signal.SIGINT, lambda sig, frame: app.on_quit())
    
    sys.exit(app.exec())
