# HyperHeadset Python Tray

A battery and status monitoring tool for the **HyperX Cloud III Wireless** (and compatible) headsets, written in Python with a native system tray interface.

[![Latest Release](https://img.shields.io/github/v/release/rafal-p4wlowski/HyperHeadset_PY?label=Download%20.exe)](https://github.com/rafal-p4wlowski/HyperHeadset_PY/releases/latest)

## Features

- **Battery Monitoring:** Battery level displayed directly in the system tray icon (polled every 10 seconds).
- **Live Events:** Mute button, charger and headset power on/off are picked up immediately.
- **Auto-Reconnect:** Recovers within seconds after the dongle is replugged or Windows resumes from sleep.
- **Charging Status:** View whether the headset is currently charging.
- **Microphone Control:** Toggle microphone mute status and view current state.
- **Side Tone:** Enable/Disable side tone and adjust its volume (0, 50, 100, 200).
- **Auto-Shutdown:** Configure automatic shutdown timer (Disabled, 5, 10, 15, 30, 45, 60, 90, or 120 minutes).
- **Premium UI:** Sleek, dark-themed context menu powered by PyQt6.
- **Lightweight:** Runs silently in the background with minimal resource usage.

## Screenshots

| Tray Hover (Battery Level) | Context Menu (Settings) |
| :---: | :---: |
| ![Tray Hover](1.png) | ![Context Menu](2.png) |

## Installation

### Prerequisites

- **Python 3.9+**
- **hidapi:** `pip install hidapi` installs a prebuilt binary only for Python versions it has wheels for; on a newer Python it has to be compiled, which needs Microsoft C++ Build Tools. Alternatively install the `hid` package and put `hidapi.dll` (from [libusb/hidapi releases](https://github.com/libusb/hidapi/releases)) next to `main.py`.

### Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/rafal-p4wlowski/HyperHeadset_PY.git
   cd HyperHeadset_PY
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run the application:
```bash
python main.py
```
The application will appear as an icon in your system tray. Right-click the icon to access the menu and settings.

A log is written to `%APPDATA%\HyperHeadset\hyperheadset.log`. Set the environment variable `HYPERHEADSET_DEBUG=1` to also log every HID report.

## Creating an Executable (.exe)

To create a standalone `.exe` file for Windows:

1. Install PyInstaller:
   ```bash
   pip install pyinstaller
   ```
2. Build the application:
   ```bash
   pyinstaller --noconsole --onefile --windowed --name "HyperHeadset" main.py
   ```
   *(Note: The first run will generate a `dist` folder containing `HyperHeadset.exe`.)*

## Dependencies

- `hidapi`: For communication with the headset over HID.
- `PyQt6`: For the system tray icon, the context menu and rendering the battery level icon.

## Attribution

The HID communication logic and protocol identifiers were implemented based on the original project by **Lennard Kittner**:
- **Original Repository:** [HyperHeadset](https://github.com/LennardKittner/HyperHeadset)
- **License:** MIT

## License

This project is licensed under the MIT License.
