# Backend API Reference

## Server Info

| Item | Value |
|------|-------|
| Label | datajam-nbiot-backend |
| IP | 172.233.144.32 |
| Port | 5000 |
| Region | Los Angeles, CA |
| Plan | Nanode 1GB |
| OS | Ubuntu 24.04.3 LTS |
| SSH | `ssh root@172.233.144.32` |

---

## API Endpoints

### Public (no auth)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check, returns version |

### Device Endpoints

Require `Authorization: Bearer <device-token>`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/reading` | POST | Submit probe counts |
| `/api/heartbeat` | POST | Send heartbeat signal |
| `/api/geolocation` | POST | Send WiFi scan for location |

### Admin Endpoints

Require `Authorization: Bearer djnb-admin-2026-change-me`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/device/register` | POST | Register new device, returns token |
| `/api/device/<id>/regenerate-token` | POST | Generate new token |
| `/api/device/<id>/status` | PUT | Change device status |
| `/api/device/<id>/command` | POST | Queue command for device |
| `/api/device/<id>/clear-anomaly` | POST | Clear anomaly flag |
| `/api/devices` | GET | List all devices |
| `/api/readings` | GET | View readings (?device_id=X&limit=N) |
| `/api/stats` | GET | System stats |
| `/api/heartbeats` | GET | View heartbeat logs |
| `/api/ota/register-firmware` | POST | Register new firmware version |
| `/api/ota/register-patch` | POST | Register a delta patch |
| `/api/ota/status` | GET | Get OTA status for all devices |

### OTA Endpoints (device auth)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/ota/check` | POST | Device checks for available updates |
| `/api/ota/chunk` | GET | Get a single 512-byte chunk of patch |
| `/api/ota/complete` | POST | Device reports update success/failure |

---

## Common API Examples

```bash
# List all devices
curl -H "Authorization: Bearer djnb-admin-2026-change-me" \
  http://172.233.144.32:5000/api/devices

# Get recent readings
curl -H "Authorization: Bearer djnb-admin-2026-change-me" \
  "http://172.233.144.32:5000/api/readings?limit=20"

# Get readings for specific device
curl -H "Authorization: Bearer djnb-admin-2026-change-me" \
  "http://172.233.144.32:5000/api/readings?device_id=JBNB0001&limit=10"

# Register new device
curl -X POST "http://172.233.144.32:5000/api/device/register" \
  -H "Authorization: Bearer djnb-admin-2026-change-me" \
  -H "Content-Type: application/json" \
  -d '{"device_id": "JBNB0005"}'

# Regenerate token
curl -X POST "http://172.233.144.32:5000/api/device/JBNB0001/regenerate-token" \
  -H "Authorization: Bearer djnb-admin-2026-change-me"

# Send command to device
curl -X POST "http://172.233.144.32:5000/api/device/JBNB0001/command" \
  -H "Authorization: Bearer djnb-admin-2026-change-me" \
  -H "Content-Type: application/json" \
  -d '{"command":"send_now"}'

# Available commands: send_now, reboot, geolocate, ota_check, fetch_config
```

---

## Service Management

```bash
systemctl status datajam-nbiot    # Check status
systemctl restart datajam-nbiot   # Restart
systemctl stop datajam-nbiot      # Stop
journalctl -u datajam-nbiot -f    # View logs
```

---

## Database

### Local SQLite

- **Path:** `/opt/datajam-nbiot/data.db`
- **Tables:** devices, readings, heartbeats

### Supabase (Cloud)

- **Project:** IoTNB Data
- **URL:** `https://xopbjawzrvsoeiapoawm.supabase.co`
- **Tables:** `nbiot_readings`, `nbiot_devices`

### Sync Script

- **Location:** `/opt/datajam-nbiot/sync_to_supabase.py`
- **Schedule:** Every 5 minutes (cron)
- **Log:** `/var/log/supabase-sync.log`

---

## Server File Structure

```
/opt/datajam-nbiot/
├── venv/                 # Python virtual environment
├── receiver.py           # Flask application (v2.11)
├── sync_to_supabase.py   # Supabase sync script
├── data.db               # SQLite database
└── ota/                  # OTA update system
    ├── firmware/         # Firmware binaries
    ├── patches/          # Delta patches
    ├── generate_patch.py # Patch generator
    └── register_firmware.py # Registration CLI
```

---

## Heartbeat System

**Frequency:** Every 24 hours + on boot

**Payload (Device → Backend):**
```json
{
  "d": "JBNB0002",
  "v": "5.5",
  "uptime": 86400,
  "cell_rssi": -85
}
```

**Response (Backend → Device):**
```json
{
  "status": "ok",
  "server_time": "2026-01-29T10:00:00.123456+00:00",
  "command": "send_now",
  "config_version": 1
}
```

**What happens on heartbeat:**
1. Time sync - Device calculates boot timestamp
2. Command processing - Executes any pending command
3. OTA rollback - First successful heartbeat marks firmware valid
4. Config check - Fetches new config if version changed

---

## Anomaly Detection (v2.11)

Non-blocking detection of unusual request patterns. Flags but never drops data.

### How It Works

- **Threshold:** 50+ requests from same device in 60 seconds
- **Action:** Sets `anomalous=true` in device record, sends email alert
- **Email:** Sent via Resend API to team@data-jam.com (one per anomaly)

### Database Columns

| Column | Type | Description |
|--------|------|-------------|
| `anomalous` | BOOLEAN | True if unusual activity detected |
| `anomaly_reason` | TEXT | e.g., "Burst: 73 requests in 60s" |
| `anomaly_detected_at` | TIMESTAMPTZ | When first detected |

### Clear Anomaly

```bash
curl -X POST "http://172.233.144.32:5000/api/device/JBNB0001/clear-anomaly" \
  -H "Authorization: Bearer djnb-admin-2026-change-me"
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `RESEND_API_KEY` | Resend API key for email alerts |
| `ALERT_EMAIL_TO` | Recipient email (team@data-jam.com) |
| `ALERT_EMAIL_FROM` | Sender (NB-IoT Alerts <alerts@datajamreports.com>) |

Set in `/opt/datajam-nbiot/.env` and loaded via systemd EnvironmentFile.
