#!/usr/bin/env python3
"""
Sync readings and devices from local SQLite to Supabase.
Runs as a cron job every 5 minutes.
Updated for v2.3 - includes extended RSSI metrics.
"""

import sqlite3
import requests
from datetime import datetime, timezone

# Configuration
DB_PATH = "/opt/datajam-nbiot/data.db"
SUPABASE_URL = "https://xopbjawzrvsoeiapoawm.supabase.co"
SUPABASE_KEY = "REDACTED_SUPABASE_KEY"

def parse_timestamp(ts):
    """Convert timestamp to ISO format for Supabase."""
    if ts is None:
        return None
    if isinstance(ts, str) and "T" in ts:
        return ts
    try:
        unix_ts = int(ts)
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return str(ts)

def get_unsynced_readings():
    """Get readings that have not been synced to Supabase yet."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("""
        SELECT id, device_id, timestamp, impressions, unique_count,
               signal_dbm, apple_count, android_count, other_count,
               probe_rssi_avg, probe_rssi_min, probe_rssi_max, cell_rssi,
               received_at
        FROM readings
        WHERE synced_to_supabase = 0
        ORDER BY id
        LIMIT 100
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def mark_as_synced(reading_ids):
    """Mark readings as synced in local database."""
    if not reading_ids:
        return
    conn = sqlite3.connect(DB_PATH)
    placeholders = ",".join("?" * len(reading_ids))
    conn.execute(f"UPDATE readings SET synced_to_supabase = 1 WHERE id IN ({placeholders})", reading_ids)
    conn.commit()
    conn.close()

def sync_readings_to_supabase(readings):
    """Push readings to Supabase."""
    if not readings:
        print("No readings to sync")
        return True

    supabase_rows = []
    for r in readings:
        supabase_rows.append({
            "device_id": r["device_id"],
            "timestamp": parse_timestamp(r["timestamp"]),
            "impressions": r["impressions"],
            "unique_count": r["unique_count"],
            "signal_dbm": r["signal_dbm"],
            "apple_count": r.get("apple_count", 0) or 0,
            "android_count": r.get("android_count", 0) or 0,
            "other_count": r.get("other_count", 0) or 0,
            "probe_rssi_avg": r.get("probe_rssi_avg"),
            "probe_rssi_min": r.get("probe_rssi_min"),
            "probe_rssi_max": r.get("probe_rssi_max"),
            "cell_rssi": r.get("cell_rssi"),
            "received_at": r["received_at"]
        })

    url = f"{SUPABASE_URL}/rest/v1/nbiot_readings"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

    try:
        response = requests.post(url, headers=headers, json=supabase_rows)
        if response.status_code in (200, 201):
            print(f"Synced {len(readings)} readings to Supabase")
            return True
        else:
            print(f"Supabase readings error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"Readings sync error: {e}")
        return False

def get_devices():
    """Get all devices from local database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("""
        SELECT device_id, project_name, location_name, timezone,
               firmware_version, status, registered_at, last_seen_at,
               last_signal_dbm, latitude, longitude
        FROM devices
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def sync_devices_to_supabase(devices):
    """Upsert devices to Supabase."""
    if not devices:
        print("No devices to sync")
        return True

    supabase_rows = []
    for d in devices:
        supabase_rows.append({
            "device_id": d["device_id"],
            "project_name": d["project_name"],
            "location_name": d["location_name"],
            "timezone": d["timezone"],
            "firmware_version": d["firmware_version"],
            "status": d["status"],
            "registered_at": d["registered_at"],
            "last_seen_at": d["last_seen_at"],
            "last_signal_dbm": d["last_signal_dbm"],
            "latitude": d["latitude"],
            "longitude": d["longitude"]
        })

    url = f"{SUPABASE_URL}/rest/v1/nbiot_devices"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }

    try:
        response = requests.post(url, headers=headers, json=supabase_rows)
        if response.status_code in (200, 201):
            print(f"Synced {len(devices)} devices to Supabase")
            return True
        else:
            print(f"Supabase devices error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"Devices sync error: {e}")
        return False

def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting Supabase sync...")

    # Sync readings
    readings = get_unsynced_readings()
    print(f"Found {len(readings)} unsynced readings")

    if readings:
        if sync_readings_to_supabase(readings):
            reading_ids = [r["id"] for r in readings]
            mark_as_synced(reading_ids)
            print(f"Marked {len(reading_ids)} readings as synced")
        else:
            print("Readings sync failed, will retry next run")

    # Sync devices (always upsert to keep Supabase current)
    devices = get_devices()
    print(f"Found {len(devices)} devices to sync")
    sync_devices_to_supabase(devices)

    print("Sync complete")

if __name__ == "__main__":
    main()
