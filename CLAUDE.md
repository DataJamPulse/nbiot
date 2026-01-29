# Data Jam NB-IoT Sensor Project

## Project Overview

Building an NB-IoT version of the JamBox probe counter.

**IMPORTANT FOR CLAUDE:** Never run `pio device monitor` or any serial monitor commands in chat sessions - they time out and crash. User will run serial monitor in a separate terminal. This device counts 802.11 probe requests (like existing JamBox units) but transmits data over cellular instead of WiFi.

**Data Flow:** Device → NB-IoT (T-Mobile) → Hologram → Linode (processing) → Supabase (clean counts only) → DataJam Reports
**Privacy-first architecture** - no PII leaves our infrastructure.

---

## Specialized Agents

Use these agents for specific tasks:

| Agent | Use For |
|-------|---------|
| `firmware-nbiot` | PlatformIO config, ESP32/Arduino code, SIM7028 AT commands, WiFi probe capture, power management |
| `nbiot-connectivity-engineer` | SIM activation, network registration, AT command sequences, signal issues, Hologram dashboard, band configuration |
| `backend-nbiot-engineer` | Hologram webhooks, Linode server, probe data processing, deduplication algorithms, Supabase schema, HTTPS setup |

---

## Current Status (2026-01-29)

**STATUS: PRODUCTION READY** - v5.2 firmware with reliability fixes + optimized BLE sampling!

### Active Devices
| Device ID | Firmware | Location | Status |
|-----------|----------|----------|--------|
| JBNB0001 | **v5.2** | Dev Unit 1 | Online |
| JBNB0002 | **v5.2** | Dev Unit 2 | Online |

### Isolated Test Environment Architecture
```
JBNB Device (firmware v5.2)
    ↓ HTTP over NB-IoT cellular (T-Mobile)
Hologram
    ↓
Linode (172.233.144.32:5000) ← Flask backend stores in SQLite
    ↓ sync_to_supabase.py (cron every 5 min)
Supabase (NB-IoT project: xopbjawzrvsoeiapoawm)
    ↑
Netlify Functions (nbiot.netlify.app/.netlify/functions/nbiot-api v1.4.0)
    ↑
Dashboard (nbiot.netlify.app)
```
**Completely isolated from datajamreports.com** - this is the test environment.

### NB-IoT Portal (Two-Page Structure)
- **URL:** https://nbiot.netlify.app
- **GitHub:** github.com/DataJamPulse/nbiot
- **API:** Local Netlify Functions → Supabase (reads) / Linode (device ops)

**Page 1: My Store Insights** (`index.html`)
Shop owner view - simple language, no technical jargon:
- Visitors Today (big number)
- Busiest Hour
- Foot Traffic chart (Today/Yesterday/Week tabs)
- "Who's Visiting?" - device type breakdown (Apple vs Other) via BLE manufacturer IDs
- "Where Are They?" - proximity breakdown (At Counter, In Store, Window Shopping, Walking Past)
- "How Long Do They Stay?" - engagement (Quick Glance, Browsing, Shopping, Loyal Customer)

**Page 2: Out of Home** (`fleet.html`)
Device management view:
- Interactive map showing sensor locations
- Fleet status (Online/Warning/Offline counts)
- Sensor list with signal strength
- Device detail modal with recent activity
- **Device Health section** - firmware version, signal quality bars, status badges

### Remote Command System (v3.0)
Devices receive commands via both heartbeat AND reading responses:
```bash
# Force send data now
curl -X POST "http://172.233.144.32:5000/api/device/JBNB0002/command" \
  -H "Authorization: Bearer djnb-admin-2026-change-me" \
  -H "Content-Type: application/json" -d '{"command":"send_now"}'

# Reboot device
curl -X POST "..." -d '{"command":"reboot"}'

# Trigger remote geolocation
curl -X POST "..." -d '{"command":"geolocate"}'
```
Commands work on every 5-minute reading as well as daily heartbeat (v3.0 fix).

### Firmware Version: 5.2
### Backend Version: 2.7
### API Version: 1.4.0

### Dwell Time Tracking (v3.0)
Firmware tracks how long devices stay in range:
| Bucket | Duration | Shop Owner Term |
|--------|----------|-----------------|
| `dwell_0_1` | Under 1 min | "Quick Glance" |
| `dwell_1_5` | 1-5 min | "Browsing" |
| `dwell_5_10` | 5-10 min | "Shopping" |
| `dwell_10plus` | 10+ min | "Loyal Customer" |

### RSSI Distance Zones (v3.0)
Firmware categorizes probes by signal strength (proves viewability):
| Zone | RSSI | Distance | Shop Owner Term |
|------|------|----------|-----------------|
| `rssi_immediate` | > -50 dBm | ~0-2m | "At Counter" |
| `rssi_near` | -50 to -65 dBm | ~2-5m | "In Store" |
| `rssi_far` | -65 to -80 dBm | ~5-15m | "Window Shopping" |
| `rssi_remote` | < -80 dBm | >15m | "Walking Past" |

**Note:** Distances are approximate. Actual range depends on phone transmit power and obstacles.

### BLE Device Counting (v5.2)
Firmware scans Bluetooth Low Energy advertisements for OS detection via manufacturer IDs.

**Key Strategy: BLE for Composition, WiFi for Volume**
- **WiFi probes** = foot traffic volume (unique visitors)
- **BLE sample** = device composition percentage (Apple vs Other)
- Server calculates: `ble_apple / ble_unique` = Apple percentage
- Apply percentage to WiFi counts for estimated breakdown

**Why this approach:**
- BLE is noisy (constant broadcasts) but gives accurate manufacturer IDs
- WiFi probes are sparse but better represent real foot traffic
- Brief BLE samples give statistically valid composition data
- WiFi gets 97% of scan time for accurate visitor counting

**Classification: Apple vs Other**
Only Apple devices can be reliably detected via manufacturer ID (0x004C). Android manufacturer ID detection is unreliable due to ecosystem fragmentation (many vendors don't broadcast standard IDs). Therefore:
- **Apple:** Manufacturer ID 0x004C (iPhone, iPad, Watch, AirPods)
- **Other:** Everything else (Android, wearables, IoT, unknown)

**Time-Slicing Architecture (v5.2):**
ESP32 shares radio between WiFi and BLE, so firmware alternates:
- 29 seconds WiFi promiscuous mode (probe capture)
- 1 second BLE passive scanning (minimum for NimBLE)
- **97/3 split** - WiFi gets nearly all time, BLE sampled briefly for composition

**BLE Payload Fields:**
| Field | Description |
|-------|-------------|
| `ble_i` | Total BLE advertisements detected |
| `ble_u` | Unique BLE devices (per-minute dedup) |
| `ble_apple` | Apple device count |
| `ble_other` | Other BLE devices (Android, wearables, IoT) |
| `ble_rssi_avg` | Average BLE signal strength (dBm) |

**API Calculated Fields (v1.4.0):**
| Field | Description |
|-------|-------------|
| `ble_apple_pct` | Percentage of BLE devices that are Apple |
| `ble_other_pct` | Percentage of BLE devices that are Other |
| `estimated_apple` | WiFi unique count × Apple percentage |
| `estimated_other` | WiFi unique count × Other percentage |

**Note:** Backend still accepts `ble_android` for backwards compatibility but firmware sends 0.

**Privacy:** Only randomized BLE addresses are counted (same as WiFi probes).

### Device Activation Portal
Zero-touch device setup for customers:
- **URL:** `https://datajamreports.com/activate/JBNB0001`
- QR code on device label links to status page
- PIN-protected location naming (4-digit PIN from label)
- Shows device status, signal strength, last seen

### Watchdog Timer (v3.0)
Device auto-reboots if stuck for 5 minutes (ESP32 task watchdog).

### OTA Rollback Protection (v3.1)
Firmware uses ESP32 dual-partition OTA with automatic rollback:
- New firmware must successfully send data to backend before being marked "valid"
- If new firmware fails to connect/send, device auto-reboots to previous working firmware
- Prevents bricked devices from bad OTA updates
- Confirmation happens on first successful reading or heartbeat

### Local Data Cache (v3.0)
Device caches readings when cellular is unavailable:
- 96-reading circular buffer (8 hours at 5-min intervals, or 48 hours at 30-min)
- Cached readings sent automatically when connectivity resumes
- No data loss during temporary cellular outages

### WiFi Geolocation (v2.3+)
Device auto-locates on every boot and via remote `geolocate` command:
1. Scans nearby WiFi networks (fast, ~3 sec)
2. Retries modem connection (up to 5 attempts with 2s delays)
3. Sends WiFi BSSIDs to backend
4. Backend calls Google Geolocation API
5. Determines timezone from coordinates
6. Updates device record in SQLite and Supabase

**Google API Key:** `REDACTED_GOOGLE_KEY` (iot Geolocate - no restrictions)

**Limitations:** WiFi geolocation accuracy depends on Google's database of WiFi networks. In areas where Google hasn't mapped the local networks, or where visible networks are associated with other locations, the returned coordinates may be incorrect. Manual location entry may be needed in these cases.

### Offline Device Alerts (v2.5)
Scheduled Netlify function (`nbiot-alerts.js`) runs hourly:
- Checks for devices offline more than 24 hours
- Sends consolidated email via Resend API
- Records alerts to `nbiot_alerts` table (prevents spam)
- Email styled with DataJam branding

### Per-Minute Deduplication (v2.4)
Probe counting now deduplicates per MAC per minute (MRC "opportunity to see" standard):
- Same phone, 50 probes in 1 minute = 1 impression
- Same phone, 50 probes over 10 minutes = 10 impressions
- `unique` count represents "device-minutes" not "unique devices"

### Device Classification (v4.0)
Firmware classifies devices via **BLE manufacturer IDs** (not WiFi OUI):
- **Apple:** Manufacturer ID 0x004C (reliable - iPhone, iPad, Watch, AirPods)
- **Other:** All non-Apple devices (Android detection unreliable due to ecosystem fragmentation)

WiFi probe requests no longer used for OS detection (unreliable with randomized MACs).

### LED Status Colors
| Color | Meaning |
|-------|---------|
| PURPLE | Booting / initializing |
| RED (slow blink) | Searching for network |
| RED (fast blink) | Critical error |
| **GREEN (solid)** | Connected, counting probes |
| CYAN (pulse) | Transmitting data |
| GREEN (3 sec) | Send successful |
| BLUE (slow blink) | Send failed |
| YELLOW (pulse) | OTA update mode |
| WHITE (flash) | Button press acknowledged |

### Buttons
| Button | Action | Function |
|--------|--------|----------|
| Main (top) | Short press | Send data immediately |
| Main (top) | Long press (3s) | Enter OTA mode |
| Side | Press | Reboot device |

| Milestone | Status |
|-----------|--------|
| Hardware validation | ✓ Complete |
| NB-IoT connectivity | ✓ T-Mobile Band 4 |
| Linode server setup | ✓ Complete |
| Flask backend v2.7 | ✓ Running with auth + geolocation + extended RSSI + heartbeat + device PIN + BLE + OTA |
| Device authentication | ✓ Token-based |
| NB-IoT → Backend data flow | ✓ **VERIFIED** - JBNB0001 sending |
| Probe capture firmware | ✓ **COMPLETE** - Privacy filter + WiFi probes |
| BLE device counting | ✓ **COMPLETE** - Apple vs Other via manufacturer IDs |
| Supabase sync | ✓ COMPLETE - Cron job every 5 mins |

### Phase Status
- **Phase 1: Hardware Validation** ✓ COMPLETE
- **Phase 2: Data Transmission** ✓ COMPLETE
- **Phase 3: Backend Development** ✓ COMPLETE - Flask API v2.1 with auth
- **Phase 4: HTTPS/Security** ✓ COMPLETE - SSL cert on server (device uses HTTP intentionally)
- **Phase 5: Firmware Development** ✓ COMPLETE - Probe capture + device classification + LED/buttons
- **Phase 6: Supabase Sync** ✓ COMPLETE - Cron job every 5 mins

### Design Decision: HTTP (not HTTPS) from Device
NB-IoT has built-in network-layer encryption. TLS handshakes are unreliable over narrowband cellular. HTTP is industry standard for NB-IoT deployments. This is intentional, not a bug.

### Parked for Later
- **Hologram API integration** - Data usage per device, last cellular connection time. Revisit at 20+ devices or when billing clients.
- **BLE Beacon advertising** - Proximity marketing feature. JamBox broadcasts beacon, client apps detect and trigger notifications. Hardware capable, needs firmware + client SDK.

### TODO
- [x] Polish Fleet Command UI based on real data - DONE (Device Health section added)
- [x] Add remote command buttons to portal UI - DONE (send_now, geolocate, reboot in fleet modal)
- [x] OTA server infrastructure - DONE (Phase 1 complete)
- [x] OTA device firmware (Phase 2) - DONE (v5.0 has full OTA client)
- [x] Firmware reliability fixes - DONE (v5.0 fixed arrays, no heap fragmentation)
- [ ] OTA monitoring UI (Phase 3) - Fleet Command OTA status display
- [ ] Run Supabase migration `006_ota_tables.sql`
- [ ] Persistent interval change (NVS storage) for set_interval command
- [ ] Device history/events table for audit trail
- [ ] Manual location entry when WiFi geolocation fails

### Firmware v4.0 (2026-01-28)
Major update: BLE device counting for OS detection.

| Feature | Description |
|---------|-------------|
| **BLE Device Counting** | NimBLE passive scanning for Apple vs Other detection via manufacturer IDs |
| **Apple vs Other** | Only Apple reliably detectable (0x004C); Android detection unreliable due to fragmentation |
| **Radio Time-Slicing** | 12s WiFi + 3s BLE alternating (80/20 split) |
| **Removed WiFi OS Detection** | WiFi probe MAC-based classification removed (unreliable) |
| **OTA Rollback Protection** | ESP32 dual-partition OTA - new firmware must successfully send data before being marked valid |
| **NTP-like time sync** | Syncs `g_bootTimestamp` from backend `server_time` in heartbeat response |
| **Command parsing in readings** | Commands work in both heartbeat AND reading responses |
| **Remote geolocate command** | `geolocate` command triggers fresh WiFi scan + location update |
| **Watchdog timer** | 5-minute ESP32 watchdog for auto-recovery if device hangs |
| **Dwell time tracking** | 4 buckets: 0-1min, 1-5min, 5-10min, 10+min |
| **RSSI distance zones** | 4 zones: immediate, near, far, remote |
| **96-reading cache** | Circular buffer for offline resilience |

**To flash:** Connect device, run `./scripts/NBJBTOOL.sh`, option 1, enter device ID.

### Firmware v4.1 (2026-01-28)
Minor update: BLE OS counts now deduplicated.

| Feature | Description |
|---------|-------------|
| **BLE OS Deduplication** | `ble_apple` and `ble_other` now deduplicated per-minute (like `ble_unique`) |

**Before v4.1:** 1 iPhone sending 50 BLE ads = `ble_apple: 50` (raw)
**After v4.1:** 1 iPhone sending 50 BLE ads = `ble_apple: 1` (deduplicated)

`ble_impressions` remains raw count (total advertisements received).

### Firmware v4.6 (2026-01-28)
Time sync fix for correct timestamps.

| Feature | Description |
|---------|-------------|
| **Time Sync Fix** | Fixed server_time parsing - increased buffer from 30 to 40 chars for ISO timestamps with microseconds |
| **Manual Epoch Calculation** | Replaced unreliable mktime() with manual UTC epoch calculation |
| **Buffer Order Fix** | Moved AT+CIPCLOSE after parsing to prevent buffer clearing |

**Bug Fixed:** Device timestamps were showing ~6 hours behind. Server sent timestamps like `2026-01-28T23:04:20.306981+00:00` (32 chars) but firmware only accepted <30 chars.

### Firmware v5.0 (2026-01-29)
**Major reliability update for 24/7 year-long deployment.**

| Feature | Description |
|---------|-------------|
| **Fixed Arrays** | Replaced `std::set` and `std::map` with fixed-size arrays - eliminates heap fragmentation |
| **No Dynamic Allocation** | Probe counting and dwell tracking use pre-allocated arrays, no malloc/free during operation |
| **Watchdog During Network Init** | Added `esp_task_wdt_reset()` in network init loop - prevents false reboots on slow networks |
| **Heap Monitoring** | Logs heap stats every 60 seconds: Free, Min, MaxBlock - visibility into memory health |
| **Delta OTA Client** | Full OTA state machine with NVS persistence, 512-byte chunk download, resume after power loss |

**Memory Changes:**
- RAM: 23.0% (was 19.9%) - arrays pre-allocated at startup
- Flash: 53.9% - unchanged
- Heap: Stable over time (no fragmentation)

**Reliability Improvements:**
- Safe for 24/7 operation over 1+ year deployment
- No memory leaks from STL containers
- No critical section issues with dynamic allocation
- Predictable memory usage regardless of traffic

### Firmware v5.2 (2026-01-29)
**BLE sparse sampling for composition percentages.**

| Feature | Description |
|---------|-------------|
| **97/3 Time Split** | 29s WiFi / 1s BLE (was 80/20 in v4.0) |
| **BLE for Composition Only** | Brief BLE samples give Apple vs Other percentage |
| **WiFi for Volume** | Nearly all time dedicated to accurate probe counting |
| **NimBLE 1s Minimum** | Fixed "forever" scan warning (NimBLE needs ≥1 second) |

**Key Insight:** BLE is noisy (4,916 devices/day) but gives accurate manufacturer IDs. WiFi probes are sparse (343/day) but represent real foot traffic. Use BLE ratio to estimate device breakdown of WiFi counts.

**API v1.4.0 calculates:**
- `ble_apple_pct` / `ble_other_pct` from BLE sample
- `estimated_apple` / `estimated_other` applied to WiFi unique counts

---

## OTA Update System (v2.7)

Production-ready delta OTA system for updating devices over NB-IoT cellular.

### Architecture
```
Server (Linode)                          Device (ESP32-S3)
┌─────────────────────┐                  ┌─────────────────────┐
│ Firmware Registry   │                  │ OTA State Machine   │
│ - v4.6.bin (1MB)    │                  │ - Check for updates │
│ - v5.0.bin (1MB)    │                  │ - Download chunks   │
│                     │                  │ - Apply delta patch │
│ Patch Generator     │   512-byte       │ - Verify & reboot   │
│ - bsdiff algorithm  │◄──chunks────────►│                     │
│ - heatshrink comp.  │                  │ NVS Progress        │
│                     │                  │ - Resume on reboot  │
│ Chunk Server        │                  │                     │
│ - /api/ota/chunk    │                  │ esp_delta_ota       │
└─────────────────────┘                  └─────────────────────┘
```

### Size Comparison
| Update Type | Full Binary | Delta Patch | Compressed Delta |
|-------------|-------------|-------------|------------------|
| Bug fix | 1,010 KB | ~15 KB | ~8 KB |
| Minor feature | 1,010 KB | ~40 KB | ~20 KB |
| Major feature | 1,010 KB | ~100 KB | ~50 KB |

### OTA Workflow

**1. Register new firmware:**
```bash
# Build firmware
pio run

# Upload to server
scp .pio/build/m5stack-atoms3/firmware.bin \
    root@172.233.144.32:/opt/datajam-nbiot/ota/firmware/v4.7.bin

# SSH to server
ssh root@172.233.144.32
cd /opt/datajam-nbiot && source venv/bin/activate

# Generate delta patch (bsdiff + heatshrink)
python3 ota/generate_patch.py 4.6 4.7

# Register with backend
python3 ota/register_firmware.py firmware 4.7 --current
python3 ota/register_firmware.py patch 4.6 4.7

# Check status
python3 ota/register_firmware.py status
```

**2. Device update flow:**
- Device calls `/api/ota/check` on heartbeat
- If update available, downloads 512-byte chunks
- Progress saved to NVS (survives power loss)
- Applies delta patch using esp_delta_ota
- Reboots and confirms success

### OTA Phase Status
| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Server Infrastructure | ✅ Complete |
| 2 | Device Firmware (OTA client) | ✅ Complete (v5.0) |
| 3 | Monitoring & Rollout UI | Pending |
| 4 | Testing | Pending |

### Registered Firmware & Patches
| Version | Size | Status | Notes |
|---------|------|--------|-------|
| v4.6 | 1,011 KB | Available | Time sync fix |
| v5.0 | 1,059 KB | Available | Reliability fixes |
| v5.2 | 1,059 KB | **Current** | BLE sparse sampling (97/3 split) |

| Patch | Size | Chunks | Compression |
|-------|------|--------|-------------|
| v4.6 → v5.0 | 188 KB | 369 | heatshrink (82% reduction) |

**Note:** v5.2 deployed via direct flash. Generate OTA patch when needed: `python3 ota/generate_patch.py 5.0 5.2`

### Supabase OTA Tables
Run migration `migrations/006_ota_tables.sql` to add:
- `firmware_versions` - Registry of firmware builds
- `ota_patches` - Delta patches between versions
- `device_ota_progress` - Track chunked download progress

---

## Hardware

### M5Stack AtomS3 DTU-NB-IoT
- **Board:** AtomS3 Lite (ESP32-S3)
- **Modem:** SIM7028 R2110 (firmware 2110B07SIM7028)
- **Serial Port:** `/dev/cu.usbmodem2101` or `/dev/cu.usbmodem101` (changes on reconnect)
- **Baud Rate:** 115200

### Pin Configuration (AtomS3)
```
Modem TX: GPIO5 (AtomS3 → Modem RX)
Modem RX: GPIO6 (AtomS3 ← Modem TX)
```

### SIM Card
- **Type:** Hologram Hyper eUICC (micro SIM)
- **Installation:** Gold contacts up, cutaway edge out
- **APN:** `hologram` (no auth required)

### LED Status
See LED Status Colors table above for full reference.
- **GREEN solid** = All good, connected and counting

---

## Hologram Dashboard

- **Device ID:** 4376999
- **SIM ID:** 4765146
- **ICCID:** 89464278206109528521
- **Profile:** Global-3
- **Status:** Ready
- **Dashboard:** dashboard.hologram.io

### US NB-IoT Networks
- **T-Mobile:** Band 2, 4, 12 (currently using Band 4)
- **AT&T:** Bands 2, 4, 12, 13

---

## Linode Backend Server

- **Label:** datajam-nbiot-backend
- **IP:** 172.233.144.32
- **Region:** Los Angeles, CA
- **Plan:** Nanode 1GB
- **OS:** Ubuntu 24.04.3 LTS
- **SSH:** `ssh root@172.233.144.32`

### Backend API (v2.0)

**Base URL:** `http://172.233.144.32:5000`
**DNS:** `nbiot.datajamreports.com` (configured, HTTPS pending)

### Device Naming Convention
- **Format:** `JBNB` + 4 digits (e.g., `JBNB0001`)
- **JB** = JamBox
- **NB** = NB-IoT variant

### Credentials (SAVE THESE SECURELY)
```
Admin Key: djnb-admin-2026-change-me
Device JBNB0001 Token: B10fYoCjm0HWc8LltAXFsBpxw3pSCFALkDK5WVlIoIE
```

### API Endpoints

**Public (no auth):**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check, returns version |

**Device Endpoints (require `Authorization: Bearer <device-token>`):**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/reading` | POST | Submit probe counts |
| `/api/heartbeat` | POST | Send heartbeat signal |
| `/api/geolocation` | POST | Send WiFi scan for location |

**Admin Endpoints (require `Authorization: Bearer <admin-key>`):**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/device/register` | POST | Register new device, returns token |
| `/api/device/<id>/regenerate-token` | POST | Generate new token |
| `/api/device/<id>/status` | PUT | Change device status |
| `/api/devices` | GET | List all devices |
| `/api/readings` | GET | View readings (optional ?device_id=X&limit=N) |
| `/api/stats` | GET | System stats |
| `/api/heartbeats` | GET | View heartbeat logs |
| `/api/ota/register-firmware` | POST | Register new firmware version |
| `/api/ota/register-patch` | POST | Register a delta patch |
| `/api/ota/status` | GET | Get OTA status for all devices |

**OTA Endpoints (require device auth):**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/ota/check` | POST | Device checks for available updates |
| `/api/ota/chunk` | GET | Get a single 512-byte chunk of patch |
| `/api/ota/complete` | POST | Device reports update success/failure |

### Device Payload Format (v4.0 firmware / v2.6 backend)
```json
{
  "d": "JBNB0001",
  "t": "2026-01-25T12:15:00Z",
  "i": 450,
  "u": 120,
  "probe_rssi_avg": -62,
  "probe_rssi_min": -45,
  "probe_rssi_max": -88,
  "cell_rssi": -85,
  "dwell_0_1": 25,
  "dwell_1_5": 30,
  "dwell_5_10": 10,
  "dwell_10plus": 5,
  "rssi_immediate": 8,
  "rssi_near": 22,
  "rssi_far": 45,
  "rssi_remote": 45,
  "ble_i": 200,
  "ble_u": 85,
  "ble_apple": 156,
  "ble_other": 44,
  "ble_rssi_avg": -68
}
```

**WiFi Probe Fields:**
| Field | Description | Required |
|-------|-------------|----------|
| `d` | Device ID | Yes |
| `t` | ISO 8601 timestamp | Yes |
| `i` | WiFi impressions (randomized MACs only) | Yes |
| `u` | WiFi unique count (deduplicated per minute) | Yes |
| `probe_rssi_avg` | Average WiFi probe RSSI (dBm) | No |
| `probe_rssi_min` | Minimum WiFi probe RSSI (dBm, strongest) | No |
| `probe_rssi_max` | Maximum WiFi probe RSSI (dBm, weakest) | No |
| `cell_rssi` | Cellular signal strength (dBm) | No |
| `dwell_*` | Dwell time bucket counts | No |
| `rssi_*` | RSSI distance zone counts | No |

**BLE Fields (v4.0+):**
| Field | Description |
|-------|-------------|
| `ble_i` | Total BLE advertisements |
| `ble_u` | Unique BLE devices (per-minute dedup) |
| `ble_apple` | Apple devices (manufacturer ID 0x004C) |
| `ble_other` | Other BLE devices (Android, wearables, IoT) |
| `ble_rssi_avg` | Average BLE signal strength (dBm) |

**Note:** `ble_android` field exists in backend for backwards compatibility but v4.0 firmware sends 0.

**Privacy Note:** Only randomized MACs are counted for both WiFi and BLE. Static addresses are filtered at the device level.

### Service Management
```bash
systemctl status datajam-nbiot    # Check status
systemctl restart datajam-nbiot   # Restart
systemctl stop datajam-nbiot      # Stop
journalctl -u datajam-nbiot -f    # View logs
```

### Database (Local)
- **Type:** SQLite
- **Path:** `/opt/datajam-nbiot/data.db`
- **Tables:** devices, readings, heartbeats

---

## Supabase (Cloud Database)

- **Project:** IoTNB Data
- **URL:** `https://xopbjawzrvsoeiapoawm.supabase.co`
- **Tables:** `nbiot_readings`, `nbiot_devices`

### Sync Script
- **Location:** `/opt/datajam-nbiot/sync_to_supabase.py`
- **Schedule:** Every 5 minutes (cron)
- **Log:** `/var/log/supabase-sync.log`

### Table Schema (v2.3)
```sql
CREATE TABLE nbiot_readings (
    id BIGSERIAL PRIMARY KEY,
    device_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    impressions INTEGER NOT NULL,
    unique_count INTEGER NOT NULL,
    signal_dbm INTEGER,
    apple_count INTEGER DEFAULT 0,
    android_count INTEGER DEFAULT 0,
    other_count INTEGER DEFAULT 0,
    probe_rssi_avg INTEGER,
    probe_rssi_min INTEGER,
    probe_rssi_max INTEGER,
    cell_rssi INTEGER,
    received_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Migration SQL (run in Supabase SQL Editor):**
```sql
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS other_count INTEGER DEFAULT 0;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS probe_rssi_avg INTEGER;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS probe_rssi_min INTEGER;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS probe_rssi_max INTEGER;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS cell_rssi INTEGER;
```

### Files on Server
```
/opt/datajam-nbiot/
├── venv/                 # Python virtual environment
├── receiver.py           # Flask application (v2.7)
├── sync_to_supabase.py   # Supabase sync script (v2.7)
├── data.db               # SQLite database
├── data.db.v1.backup     # Backup of v1 database
└── ota/                  # OTA update system
    ├── firmware/         # Firmware binaries (v4.6.bin, etc.)
    ├── patches/          # Delta patches (patch_4.6_to_4.7.bin, .json)
    ├── generate_patch.py # Patch generator (bsdiff + heatshrink)
    └── register_firmware.py # CLI tool to register firmware/patches
```

---

## Network Configuration (Verified Working)

### Current Connection
| Parameter | Value |
|-----------|-------|
| Network | T-Mobile (310-260) |
| Mode | NB-IoT |
| Band | 4 |
| Signal | -85 dBm |
| Registration | +CEREG: 0,5 (roaming) |
| IP Address | 10.238.177.255 |

### Canonical Bring-Up Sequence

**Critical Insight:** Registration ≠ Data. You MUST call `AT+NETOPEN` to open the IP stack.

**Step 1: Lock to US Bands (speeds up registration)**
```
AT+QCBAND=0,2,4,12,13,66
AT+CFUN=1,1
```
*Tip: If stuck searching after 2 minutes, run `AT+CFUN=1,1` again.*

**Step 2: Wait for Registration**
```
AT+CPSI?          # Should show: NB,Online,310-260,...
AT+CEREG?         # Should show: +CEREG: 0,5 (roaming)
```

**Step 3: Use CID 0 (auto-created by modem)**
```
AT+CGDCONT?       # Verify CID 0 has "hologram"
AT+CGACT?         # Confirm CID 0 is active (0,1)
```

**Step 4: Attach and Open Network**
```
AT+CGATT=1        # Attach to packet domain
AT+NETOPEN        # CRITICAL: Opens IP stack
```

**Step 5: Verify IP**
```
AT+IPADDR         # Should return 10.x.x.x
```

---

## Sending Data from Device

### HTTP POST via AT Commands

**Step 1: Open TCP connection**
```
AT+CIPOPEN=0,"TCP","172.233.144.32",5000
```
Wait for `+CIPOPEN: 0,0`

**Step 2: Send HTTP request**
```
AT+CIPSEND=0,232
```
When you see `>`, send the raw HTTP request:
```
POST /api/reading HTTP/1.1
Host: 172.233.144.32:5000
Authorization: Bearer B10fYoCjm0HWc8LltAXFsBpxw3pSCFALkDK5WVlIoIE
Content-Type: application/json
Content-Length: 56

{"d":"JBNB0001","t":1706230000,"i":100,"u":50,"sig":-85}
```

**Step 3: Close connection**
```
AT+CIPCLOSE=0
```

### Python Test Script
```bash
cd "/Users/jav/Desktop/DATAJAM/SynologyDrive/Development/Claude_Projects/IoTnAtom Data Jam Project/scripts"
python3 test_http_post.py
```

---

## Key Lessons Learned

1. **CID 0 is the only PDP context you should use on SIM7028 NB-IoT**
2. **`AT+NETOPEN` is mandatory** — registration ≠ data connectivity
3. **Band locking helps speed**, not correctness
4. **Do NOT use `AT+CGACT=1,1`** — causes "duplicate APN" errors
5. If `AT+IPADDR` fails, the network is not open
6. **HTTP POST over raw TCP works** - build the request manually, send via `AT+CIPSEND`

> *SIM7028 NB-IoT does not give you IP just because you are registered. You must explicitly open the data plane.*

---

## AT Command Reference

### Basic Commands
| Command | Purpose | Expected Response |
|---------|---------|-------------------|
| `AT` | Test modem | `OK` |
| `ATE0` | Disable echo | `OK` |
| `AT+CPIN?` | Check SIM status | `+CPIN: READY` |
| `AT+CSQ` | Signal quality | `+CSQ: <rssi>,<ber>` |
| `AT+CEREG?` | EPS registration | `+CEREG: <n>,<stat>` |
| `AT+CPSI?` | System info | Network, band, signal |
| `AT+COPS?` | Current operator | Operator name/code |
| `AT+IPADDR` | Get IP address | `+IPADDR: 10.x.x.x` |

### Registration Status (+CEREG)
| Code | Meaning |
|------|---------|
| 0 | Not registered, not searching |
| 1 | Registered, home network |
| 2 | Not registered, searching |
| 3 | Registration denied |
| 5 | Registered, roaming ← **This is normal for Hologram** |

### TCP Commands
| Command | Purpose |
|---------|---------|
| `AT+NETOPEN` | Open IP stack |
| `AT+NETCLOSE` | Close IP stack |
| `AT+CIPOPEN=0,"TCP","host",port` | Open TCP connection |
| `AT+CIPSEND=0,<len>` | Send data |
| `AT+CIPCLOSE=0` | Close TCP connection |

### US Carrier Codes
- **T-Mobile:** 310260
- **AT&T:** 310410, 310280

---

## Project Files

### Local (Mac)
```
/Users/jav/Desktop/DATAJAM/SynologyDrive/Development/Claude_Projects/IoTnAtom Data Jam Project/
├── CLAUDE.md                    # This file
├── platformio.ini               # PlatformIO config
├── .gitignore                   # Excludes tokens, configs, credentials
├── src/
│   ├── main.cpp                 # Main firmware source (v5.2)
│   └── device_config.h          # Device-specific config (auto-generated, gitignored)
├── scripts/
│   ├── NBJBTOOL.sh              # Device provisioning tool
│   └── test_http_post.py        # Python script to test HTTP POST
├── docs/
│   └── PROVISIONING_GUIDE.md    # Full provisioning documentation
├── backend/
│   ├── receiver.py              # Local copy of Flask backend (v2.7)
│   ├── sync_to_supabase.py      # Supabase sync script (v2.7)
│   └── ota/                     # OTA tools
│       ├── generate_patch.py    # Delta patch generator
│       ├── register_firmware.py # Firmware/patch registration CLI
│       └── requirements.txt     # OTA dependencies (detools, heatshrink2)
├── migrations/
│   └── 006_ota_tables.sql       # Supabase OTA tables migration
├── provisioning.log             # Log of provisioned devices (no tokens)
└── *.py                         # Various diagnostic scripts
```

### Server (Linode)
```
/opt/datajam-nbiot/
├── venv/                        # Python 3.12 virtual environment
├── receiver.py                  # Flask backend v2.7
├── sync_to_supabase.py          # Supabase sync script (v2.7)
├── data.db                      # SQLite database
└── ota/                         # OTA update system
    ├── firmware/                # v4.6.bin, v4.7.bin, etc.
    ├── patches/                 # Delta patches
    ├── generate_patch.py        # Patch generator
    └── register_firmware.py     # Registration CLI
```

---

## Existing JamBox Reference (WiFi Version)

The current WiFi JamBox uses this config structure (for reference when building NB-IoT firmware):

```json
{
  "datajam_number": "JB000001",
  "datajam_token": "eyJ...",
  "datajam_url": "https://datajamportal.com",
  "wifi_ssid": "...",
  "wifi_password": "..."
}
```

For NB-IoT version, configuration is stored in `src/device_config.h` (auto-generated by NBJBTOOL.sh).

---

## Device Provisioning

### NBJBTOOL.sh - Provisioning Tool

Production tool for flashing and configuring NB-IoT JamBox devices.

**Location:** `scripts/NBJBTOOL.sh`
**Documentation:** `docs/PROVISIONING_GUIDE.md`

**Prerequisites:**
- PlatformIO CLI (`~/.platformio/penv/bin/pio`)
- curl (for API calls)
- jq (recommended, for JSON parsing)

### Quick Start

```bash
# Navigate to project directory
cd "/Users/jav/Desktop/DATAJAM/SynologyDrive/Development/Claude_Projects/IoTnAtom Data Jam Project"

# Run provisioning tool
./scripts/NBJBTOOL.sh
```

### Menu Options

| Option | Description |
|--------|-------------|
| 1 | **Flash Pre-Registered Device** - Portal workflow: enter device ID, tool fetches token |
| 2 | Full Provisioning - Register new device + flash (admin use) |
| 3 | Register Device Only - Just get token, don't flash |
| 4 | Flash with Current Config - Re-flash using existing device_config.h |
| 5 | Test Device Connectivity - Verify backend is reachable |
| 6 | View Registered Devices - List all devices from backend |
| 7 | View Current Config - Show current device_config.h |
| 8 | Monitor Serial Output - Watch device logs |

### Production Workflow (Portal-First)

**This is the recommended workflow for production:**

1. **Admin registers device in portal** → Device ID created in backend (e.g., JBNB0003)

2. **Floor worker receives work order** with just the device ID

3. **Worker runs provisioning tool:**
   ```bash
   ./scripts/NBJBTOOL.sh
   # Select option 1
   # Enter device ID: JBNB0003
   ```

4. **Tool automatically:**
   - Verifies device exists in backend
   - Calls `regenerate-token` to get a fresh token
   - Generates `src/device_config.h`
   - Builds firmware
   - Flashes to connected device
   - Logs to `provisioning.log` (token NOT saved)

5. **Verify device boots:**
   - LED turns GREEN = connected and counting
   - Use option 8 to watch serial output

### Security Model

| Location | What's Stored | Security |
|----------|--------------|----------|
| Backend DB | token_hash (SHA256) | Can't be reversed |
| Device flash | Plain token | Only copy that exists |
| Local files | **Nothing** | Tokens NOT saved locally |
| .gitignore | Blocks credentials | Can't accidentally commit |

**Key points:**
- Tokens are NEVER saved to local files
- Each flash generates a fresh token (old token invalidated)
- If a device needs re-provisioning, just run the tool again
- `provisioning.log` only records device ID + timestamp

### Manual Provisioning (Alternative)

If you prefer manual steps:

1. **Register device:**
   ```bash
   curl -X POST "http://172.233.144.32:5000/api/device/register" \
     -H "Authorization: Bearer djnb-admin-2026-change-me" \
     -H "Content-Type: application/json" \
     -d '{"device_id": "JBNB0003"}'
   ```
   Note the returned token (shown once only)!

2. **Edit `src/device_config.h`:**
   ```c
   #define DEVICE_ID "JBNB0003"
   #define AUTH_TOKEN "your-token-here"
   ```

3. **Build and flash:**
   ```bash
   ~/.platformio/penv/bin/pio run --target upload
   ```

### Configuration Files

| File | Purpose |
|------|---------|
| `src/device_config.h` | Device-specific config (auto-generated, gitignored) |
| `src/main.cpp` | Main firmware (includes device_config.h) |
| `provisioning.log` | Log of provisioned devices (no tokens) |

### Device ID Format

- **Pattern:** `JBNB` + 4 digits
- **Examples:** `JBNB0001`, `JBNB0002`, `JBNB0123`
- **JB** = JamBox
- **NB** = NB-IoT variant

### Setting Up a New Provisioning Laptop

See `docs/PROVISIONING_GUIDE.md` for full instructions. Quick summary:

**Mac:**
```bash
brew install jq
curl -fsSL -o get-platformio.py https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py
python3 get-platformio.py
```

**Windows:**
1. Install Python 3.8+ from python.org
2. Install Git from git-scm.com
3. Install PlatformIO (same script in PowerShell)
4. May need USB driver from Silicon Labs

---

## Next Steps

### In Progress: Portal Integration (Plan Approved)

Integrating NB-IoT device management into DataJam Reports Portal.

**Phase 1: Netlify Backend Functions** (2-3 days)
- Create `netlify/functions/nbiot-api.js`
- Endpoints: /devices, /readings, /heartbeats, /device/register, /device/:id/regenerate
- Pattern: Basic Auth + Supabase reads + Linode proxy for writes

**Phase 2: Admin Panel UI** (3-4 days)
- Add "📡 NB-IoT" tab to existing admin panel
- Device fleet grid with status indicators (green/yellow/red)
- Register device modal (shows token once)
- Device detail modal (signal chart, readings, regenerate token)

**Phase 3: Alerting & Monitoring** (1-2 days)
- Scheduled function `nbiot-alerts.js` (hourly)
- Email via Resend when device offline 48hr+
- New Supabase table: `nbiot_alerts`

**Phase 4: Supabase Schema** (0.5 days)
- Add `project_id`, `client_id` columns to `nbiot_devices`
- Create `nbiot_alerts` table

**Phase 5 (Future): Client Data Integration**
- Show NB-IoT data alongside WiFi JamBox data
- Unified charts with device type badges

**Portal Project Location:**
```
/Users/jav/Desktop/DATAJAM/SynologyDrive/Development/Claude_Projects/Data_Jam_Pulse/datajamreports-production/
```

**Key Files:**
- `js/admin-panel.js` - Add NB-IoT tab here
- `netlify/functions/report-subscriptions-api.js` - Pattern for new API

---

### Other Items

1. **Extended Testing**
   - Run devices for extended periods to verify stability
   - Monitor Supabase sync is working

2. **Power Management** (future)
   - Implement deep sleep between reports
   - Battery life optimization

3. **Production Hardening**
   - ✓ Device provisioning workflow (NBJBTOOL.sh) - COMPLETE
   - Change admin key to something secure
   - Enclosure/weatherproofing

---

## Troubleshooting

### No Signal (CSQ=99)
1. Check antenna is firmly connected
2. Try near window or outside
3. Lock to specific bands: `AT+QCBAND=0,2,4,12,13,66`
4. Reset modem: `AT+CFUN=1,1`

### Stuck Searching (+CEREG: 0,2)
1. Wait 2-3 minutes (NB-IoT is slow)
2. Try `AT+CFUN=1,1` again
3. Force T-Mobile: `AT+COPS=1,2,"310260",9`

### No IP Address
1. Run `AT+NETOPEN` (most common fix)
2. Wait for `+NETOPEN: 0`
3. Then `AT+IPADDR` should work

### TCP Connection Fails
1. Verify IP with `AT+IPADDR`
2. Check firewall on Linode (ports 80, 443, 5000)
3. Test backend: `curl http://172.233.144.32:5000/health`

### Backend Auth Errors
1. Check device is registered: `GET /api/devices` with admin key
2. Verify token matches what was issued at registration
3. Check device status is "active"

---

## Contact Information

**Hologram Support**
- Felix Morales - Connectivity Specialist
- felix.morales@hologram.io
- (951) 783-4479

**M5Stack Support**
- community@m5stack.com

---

*Last Updated: 2026-01-29 (Firmware v5.2 with BLE sparse sampling, API v1.4.0 with composition percentages)*
