# NB-IoT JamBox Provisioning Guide

This guide covers everything needed to provision NB-IoT JamBox devices (JBNB series) for production deployment.

---

## Overview

**What is provisioning?**
Provisioning flashes unique firmware onto each JamBox device with its own secure authentication token. Each device gets a unique identity (e.g., JBNB0002) that's registered in our backend.

**Workflow:**
1. Device is registered in the portal/backend (creates device ID + token)
2. Technician runs NBJBTOOL.sh on their laptop
3. Enters the device ID (e.g., JBNB0002)
4. Tool fetches a fresh token, builds firmware, and flashes the device
5. Device boots up and starts counting

---

## Prerequisites

### Hardware Required
- NB-IoT JamBox device (M5Stack AtomS3 DTU-NB-IoT)
- USB-C cable (data cable, not charge-only)
- Hologram SIM card (pre-installed in device)

### Software Required

| Software | Mac | Windows | Purpose |
|----------|-----|---------|---------|
| Python 3.8+ | Pre-installed | Download from python.org | Required by PlatformIO |
| PlatformIO CLI | Install via script | Install via script | Builds and flashes firmware |
| Git | Pre-installed | Download from git-scm.com | Clone the project |
| curl | Pre-installed | Pre-installed (Win10+) | API calls |
| jq | `brew install jq` | `choco install jq` | JSON parsing (optional but recommended) |

---

## Setup Instructions

### Mac Setup

1. **Install Homebrew** (if not already installed):
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

2. **Install jq**:
   ```bash
   brew install jq
   ```

3. **Install PlatformIO CLI**:
   ```bash
   curl -fsSL -o get-platformio.py https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py
   python3 get-platformio.py
   ```

   After installation, PlatformIO will be at: `~/.platformio/penv/bin/pio`

4. **Clone the project**:
   ```bash
   cd ~/Documents
   git clone <repository-url> "NB-IoT JamBox"
   cd "NB-IoT JamBox"
   ```

5. **Verify setup**:
   ```bash
   ~/.platformio/penv/bin/pio --version
   ```

### Windows Setup

1. **Install Python 3.8+**:
   - Download from https://www.python.org/downloads/
   - During install, CHECK "Add Python to PATH"

2. **Install Git**:
   - Download from https://git-scm.com/download/win
   - Use default options

3. **Install Chocolatey** (package manager, optional):
   ```powershell
   # Run PowerShell as Administrator
   Set-ExecutionPolicy Bypass -Scope Process -Force
   [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
   iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
   ```

4. **Install jq** (optional but recommended):
   ```powershell
   choco install jq
   ```

5. **Install PlatformIO CLI**:
   ```powershell
   # In PowerShell
   Invoke-WebRequest -Uri "https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py" -OutFile "get-platformio.py"
   python get-platformio.py
   ```

   After installation, PlatformIO will be at: `%USERPROFILE%\.platformio\penv\Scripts\pio.exe`

6. **Clone the project**:
   ```powershell
   cd Documents
   git clone <repository-url> "NB-IoT JamBox"
   cd "NB-IoT JamBox"
   ```

7. **Install USB driver** (if device not recognized):
   - Download CP210x driver from Silicon Labs: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers

### Linux Setup

1. **Install dependencies**:
   ```bash
   sudo apt update
   sudo apt install python3 python3-pip git curl jq
   ```

2. **Install PlatformIO CLI**:
   ```bash
   curl -fsSL -o get-platformio.py https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py
   python3 get-platformio.py
   ```

3. **Add user to dialout group** (for serial port access):
   ```bash
   sudo usermod -a -G dialout $USER
   # Log out and back in for this to take effect
   ```

4. **Clone the project**:
   ```bash
   cd ~/Documents
   git clone <repository-url> "NB-IoT JamBox"
   cd "NB-IoT JamBox"
   ```

---

## Provisioning a Device

### Step 1: Connect the Device

1. Connect the JamBox to your laptop via USB-C
2. The device LED should light up (purple = booting)
3. Wait a few seconds for the USB port to be recognized

**Verify connection:**
- Mac: `ls /dev/cu.usbmodem*` should show a device
- Windows: Check Device Manager > Ports for "USB Serial Device"
- Linux: `ls /dev/ttyUSB*` or `ls /dev/ttyACM*`

### Step 2: Run the Provisioning Tool

**Mac/Linux:**
```bash
cd "/path/to/NB-IoT JamBox"
./scripts/NBJBTOOL.sh
```

**Windows (Git Bash):**
```bash
cd "/c/Users/YourName/Documents/NB-IoT JamBox"
./scripts/NBJBTOOL.sh
```

### Step 3: Flash the Device

1. Select option **1** (Flash Pre-Registered Device)
2. Enter the device ID (e.g., `JBNB0002`)
   - The device must already be registered in the portal/backend
3. Confirm the flash when prompted
4. Wait for the build and flash to complete (~15-20 seconds)

**Expected output:**
```
[OK] Device JBNB0002 found in backend
[OK] Got fresh token: xxxxxxxx...
[OK] Configuration written
[OK] Firmware built successfully
[OK] Firmware flashed successfully
[OK] Device JBNB0002 flashed successfully!
```

### Step 4: Verify the Device

1. The device will automatically reboot after flashing
2. Watch the LED:
   - PURPLE = Booting
   - RED (slow blink) = Searching for network
   - GREEN (solid) = Connected and counting
3. Use option **8** (Monitor Serial Output) to watch the boot process

**Successful boot shows:**
```
[NET] Registered to network
[GEO] Geolocation sent successfully
[HEARTBEAT] Success
[INIT] Monitoring for probe requests...
```

---

## Menu Options Reference

| Option | Name | Description |
|--------|------|-------------|
| 1 | Flash Pre-Registered Device | **Primary workflow** - Enter device ID, tool fetches token and flashes |
| 2 | Full Provisioning | Register new device + flash (admin use) |
| 3 | Register Device Only | Just register, don't flash (admin use) |
| 4 | Flash with Current Config | Re-flash using existing config |
| 5 | Test Device Connectivity | Verify backend is reachable |
| 6 | View Registered Devices | List all devices in backend |
| 7 | View Current Config | Show current device_config.h |
| 8 | Monitor Serial Output | Watch device serial output |

---

## Troubleshooting

### "No serial devices found"

**Cause:** Device not connected or driver issue

**Fix:**
- Try a different USB-C cable (some are charge-only)
- Try a different USB port
- Windows: Install CP210x driver from Silicon Labs
- Mac: May need to allow the driver in System Preferences > Security

### "Device not found in backend"

**Cause:** Device ID not registered yet

**Fix:**
- Ask an admin to register the device in the portal first
- Or use option 2 (Full Provisioning) if you have admin access

### "Build failed"

**Cause:** PlatformIO not installed correctly

**Fix:**
```bash
# Verify PlatformIO
~/.platformio/penv/bin/pio --version

# If not found, reinstall
curl -fsSL -o get-platformio.py https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py
python3 get-platformio.py
```

### "Flash failed" or "Serial port busy"

**Cause:** Another program is using the serial port

**Fix:**
- Close any serial monitor windows
- Close Arduino IDE if open
- Mac: `lsof /dev/cu.usbmodem*` to find what's using it
- Try unplugging and replugging the device

### Device LED stays RED

**Cause:** Network registration taking too long or failed

**Fix:**
- Move device closer to a window (better cellular signal)
- Wait 2-3 minutes (NB-IoT registration can be slow)
- Press the side button to reboot and retry
- Check SIM card is properly inserted

### "Modem not responding"

**Cause:** Modem needs time to initialize after power-on

**Fix:**
- The firmware retries 5 times automatically
- If it fails all 5, press the button to trigger a retry
- Power cycle the device if persistent

---

## Security Notes

- **Tokens are NOT saved locally** - they only exist on the device
- Each flash generates a fresh token (old token is invalidated)
- If a device needs re-provisioning, just run the tool again
- The provisioning log (`provisioning.log`) only records device ID and timestamp, never tokens

---

## Quick Reference Card

```
PROVISIONING CHECKLIST
======================
[ ] Device connected via USB-C
[ ] Device registered in portal (have the JBNB#### number)
[ ] Run: ./scripts/NBJBTOOL.sh
[ ] Select option 1
[ ] Enter device ID
[ ] Confirm flash
[ ] Wait for "flashed successfully"
[ ] Verify LED turns GREEN

TROUBLESHOOTING
===============
No serial port? -> Try different cable/port
Device not found? -> Check portal registration
Build failed? -> Reinstall PlatformIO
Flash failed? -> Close other serial apps
LED stays red? -> Wait or move near window
```

---

## Support

If you encounter issues not covered here:
1. Check the serial output (option 8) for error messages
2. Note the exact error message
3. Contact the development team with:
   - Device ID
   - Error message
   - Operating system
   - Steps to reproduce

---

*Last updated: 2026-01-26*
