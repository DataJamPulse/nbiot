# Data Jam NB-IoT Sensor Project

## Critical Warnings

**NEVER** run `pio device monitor` in chat sessions - they time out and crash. User runs serial monitor separately.

**NEVER** touch production folder: `/Users/jav/Desktop/DATAJAM/SynologyDrive/Development/Claude_Projects/Data_Jam_Pulse/datajamreports-production/`

## Project Overview

NB-IoT version of JamBox probe counter. Counts 802.11 probe requests, transmits over cellular.

**Data Flow:** Device → NB-IoT (T-Mobile) → Hologram → Linode → Supabase → Dashboard

**Privacy-first:** Only aggregated counts leave infrastructure. No PII.

## Current Status

| Component | Version |
|-----------|---------|
| Firmware | **v5.5** |
| Backend | v2.11 |
| API | v1.7.0 |

### Active Devices
| Device ID | Firmware | Status |
|-----------|----------|--------|
| JBNB0001 | v5.5 | Online |
| JBNB0002 | v5.5 | Online |
| JBNB0003 | v5.5 | Online |
| JBNB0004 | v5.5 | Online |
| JBNB4400 | v5.5 | Online |

## Backend Quick Reference

| Item | Value |
|------|-------|
| IP | `172.233.144.32` |
| Port | `5000` |
| Admin Key | `djnb-admin-2026-change-me` |
| SSH | `ssh root@172.233.144.32` |

**Common API calls:**
```bash
# List devices
curl -H "Authorization: Bearer djnb-admin-2026-change-me" http://172.233.144.32:5000/api/devices

# Get readings
curl -H "Authorization: Bearer djnb-admin-2026-change-me" "http://172.233.144.32:5000/api/readings?limit=10"

# Send command (send_now, reboot, geolocate, ota_check)
curl -X POST "http://172.233.144.32:5000/api/device/JBNB0001/command" \
  -H "Authorization: Bearer djnb-admin-2026-change-me" \
  -H "Content-Type: application/json" -d '{"command":"send_now"}'
```

## Device Provisioning

**Device ID Format:** `JBNB` + 4 digits (e.g., `JBNB0001`)

**Factory-fresh devices require two-phase provisioning:**
1. Option 9 → Provisioning firmware → Wait for GREEN LED
2. Option 1 → Enter device ID → Production firmware

See `docs/PROVISIONING_GUIDE.md` for full workflow.

## Specialized Agents

| Agent | Use For |
|-------|---------|
| `firmware-nbiot` | ESP32/Arduino code, SIM7028 AT commands, probe capture |
| `nbiot-connectivity-engineer` | Network registration, signal issues, Hologram dashboard |
| `backend-nbiot-engineer` | Linode server, data processing, Supabase schema |

## Anomaly Detection (v2.11)

Backend detects unusual request patterns and flags devices. **Never blocks real data.**

- **Threshold:** 50+ requests in 60 seconds triggers anomaly flag
- **Email alerts:** Sent via Resend API to team@data-jam.com
- **UI:** Anomaly badge on device cards, Clear button in modal
- **Clear:** POST `/api/device/{id}/clear-anomaly`

**Supabase columns:** `anomalous`, `anomaly_reason`, `anomaly_detected_at`

Run migration: `migrations/009_anomaly_detection.sql`

## Reference Documentation

| Document | Contents |
|----------|----------|
| `docs/PROVISIONING_GUIDE.md` | Two-phase workflow, NBJBTOOL.sh, laptop setup |
| `docs/FIRMWARE.md` | Version history, payload format, LED status, features |
| `docs/BACKEND_API.md` | All endpoints, service management, database |
| `docs/OTA_SYSTEM.md` | Delta OTA architecture, workflow, patches |
| `docs/HARDWARE_NETWORK.md` | Hardware specs, AT commands, troubleshooting |

## Project Files

```
src/main.cpp              # Production firmware (v5.5)
src/provisioning_main.cpp # Cellular provisioning firmware
src/device_config.h       # Device credentials (gitignored)
scripts/NBJBTOOL.sh       # Provisioning tool
```

---

*Last Updated: 2026-01-30 - Backend v2.11, API v1.7.0, anomaly detection + email alerts*
