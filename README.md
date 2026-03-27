# HyperHeadset Python Tray

A battery and status monitoring tool for the **HyperX Cloud III Wireless** (and compatible) headsets, written in Python with a native system tray interface.

[![Latest Release](https://img.shields.io/github/v/release/rafal-p4wlowski/HyperHeadset_PY?label=Download%20.exe)](https://github.com/rafal-p4wlowski/HyperHeadset_PY/releases/latest)

## Features

- **Battery Monitoring:** Real-time battery level displayed directly in the system tray icon (updates every 5 minutes).
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

- **Python 3.8+**
- **hidapi libraries:** Ensure you have the necessary HIDAPI drivers installed on your system.

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
   *(Note: The first run will generate a `dist` folder containing `HyperHeadset.exe`. Since Windows has built-in fonts, we don't need to bundle separate `.ttf` files.)*

## Dependencies

- `hidapi`: For communication with the headset over HID.
- `PyQt6`: For the system tray icon and native context menu.
- `Pillow`: For dynamic generation of battery level icons.

## Attribution

The HID communication logic and protocol identifiers were implemented based on the original project by **Lennard Kittner**:
- **Original Repository:** [HyperHeadset](https://github.com/LennardKittner/HyperHeadset)
- **License:** MIT

## License

This project is licensed under the MIT License.
