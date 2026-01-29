#!/usr/bin/env python3
"""
Sync readings, devices, OTA data, and device configs from local SQLite to Supabase.
Runs as a cron job every 5 minutes.
Updated for v2.9 - includes remote device configuration sync.
"""

import sqlite3
import requests
import os
from datetime import datetime, timezone

# Configuration
DB_PATH = "/opt/datajam-nbiot/data.db"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://xopbjawzrvsoeiapoawm.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_KEY:
    raise ValueError("SUPABASE_SERVICE_KEY environment variable is required")

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
               dwell_0_1, dwell_1_5, dwell_5_10, dwell_10plus,
               rssi_immediate, rssi_near, rssi_far, rssi_remote,
               ble_impressions, ble_unique, ble_apple, ble_android, ble_other, ble_rssi_avg,
               period_start_ts, overflow_count, cache_depth, send_failures, age_seconds,
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
            "dwell_0_1": r.get("dwell_0_1", 0) or 0,
            "dwell_1_5": r.get("dwell_1_5", 0) or 0,
            "dwell_5_10": r.get("dwell_5_10", 0) or 0,
            "dwell_10plus": r.get("dwell_10plus", 0) or 0,
            "rssi_immediate": r.get("rssi_immediate", 0) or 0,
            "rssi_near": r.get("rssi_near", 0) or 0,
            "rssi_far": r.get("rssi_far", 0) or 0,
            "rssi_remote": r.get("rssi_remote", 0) or 0,
            "ble_impressions": r.get("ble_impressions", 0) or 0,
            "ble_unique": r.get("ble_unique", 0) or 0,
            "ble_apple": r.get("ble_apple", 0) or 0,
            "ble_android": r.get("ble_android", 0) or 0,
            "ble_other": r.get("ble_other", 0) or 0,
            "ble_rssi_avg": r.get("ble_rssi_avg"),
            # Data quality/auditability fields (v2.8)
            "period_start_ts": r.get("period_start_ts"),
            "overflow_count": r.get("overflow_count", 0) or 0,
            "cache_depth": r.get("cache_depth", 0) or 0,
            "send_failures": r.get("send_failures", 0) or 0,
            "age_seconds": r.get("age_seconds", 0) or 0,
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
               last_signal_dbm, latitude, longitude, device_pin
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
            "longitude": d["longitude"],
            "device_pin": d.get("device_pin")
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

def get_firmware_versions():
    """Get all firmware versions from local database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("""
            SELECT version, release_date, binary_size, sha256,
                   release_notes, is_current, created_at
            FROM firmware_versions
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        conn.close()
        return []  # Table doesn't exist yet

def sync_firmware_versions_to_supabase(firmware_versions):
    """Upsert firmware versions to Supabase."""
    if not firmware_versions:
        return True

    supabase_rows = []
    for f in firmware_versions:
        supabase_rows.append({
            "version": f["version"],
            "release_date": f["release_date"],
            "binary_size": f["binary_size"],
            "sha256": f["sha256"],
            "release_notes": f["release_notes"],
            "is_current": bool(f["is_current"]),
            "created_at": f["created_at"]
        })

    url = f"{SUPABASE_URL}/rest/v1/firmware_versions"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }

    try:
        response = requests.post(url, headers=headers, json=supabase_rows)
        if response.status_code in (200, 201):
            print(f"Synced {len(firmware_versions)} firmware versions to Supabase")
            return True
        else:
            print(f"Supabase firmware_versions error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"Firmware versions sync error: {e}")
        return False

def get_ota_patches():
    """Get all OTA patches from local database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("""
            SELECT from_version, to_version, patch_size, chunk_count,
                   sha256, compression, created_at
            FROM ota_patches
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        conn.close()
        return []  # Table doesn't exist yet

def sync_ota_patches_to_supabase(patches):
    """Upsert OTA patches to Supabase."""
    if not patches:
        return True

    supabase_rows = []
    for p in patches:
        supabase_rows.append({
            "from_version": p["from_version"],
            "to_version": p["to_version"],
            "patch_size": p["patch_size"],
            "chunk_count": p["chunk_count"],
            "sha256": p["sha256"],
            "compression": p["compression"],
            "created_at": p["created_at"]
        })

    url = f"{SUPABASE_URL}/rest/v1/ota_patches"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }

    try:
        response = requests.post(url, headers=headers, json=supabase_rows)
        if response.status_code in (200, 201):
            print(f"Synced {len(patches)} OTA patches to Supabase")
            return True
        else:
            print(f"Supabase ota_patches error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"OTA patches sync error: {e}")
        return False

def get_device_ota_progress():
    """Get device OTA progress from local database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("""
            SELECT device_id, target_version, chunks_received, total_chunks,
                   started_at, last_chunk_at, status, error_message
            FROM device_ota_progress
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        conn.close()
        return []  # Table doesn't exist yet


def get_device_configs():
    """Get all device configs from local database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("""
            SELECT device_id, report_interval_ms, heartbeat_interval_ms,
                   geolocation_on_boot, wifi_channels,
                   rssi_immediate_threshold, rssi_near_threshold, rssi_far_threshold,
                   dwell_short_threshold, dwell_medium_threshold, dwell_long_threshold,
                   config_version, updated_at
            FROM device_configs
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        conn.close()
        return []  # Table doesn't exist yet


def sync_device_configs_to_supabase(configs):
    """Upsert device configs to Supabase."""
    if not configs:
        return True

    supabase_rows = []
    for c in configs:
        supabase_rows.append({
            "device_id": c["device_id"],
            "report_interval_ms": c.get("report_interval_ms", 300000),
            "heartbeat_interval_ms": c.get("heartbeat_interval_ms", 86400000),
            "geolocation_on_boot": bool(c.get("geolocation_on_boot", 1)),
            "wifi_channels": c.get("wifi_channels", "1,6,11"),
            "rssi_immediate_threshold": c.get("rssi_immediate_threshold", -50),
            "rssi_near_threshold": c.get("rssi_near_threshold", -65),
            "rssi_far_threshold": c.get("rssi_far_threshold", -80),
            "dwell_short_threshold": c.get("dwell_short_threshold", 1),
            "dwell_medium_threshold": c.get("dwell_medium_threshold", 5),
            "dwell_long_threshold": c.get("dwell_long_threshold", 10),
            "config_version": c.get("config_version", 1),
            "updated_at": c.get("updated_at")
        })

    url = f"{SUPABASE_URL}/rest/v1/nbiot_device_configs"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }

    try:
        response = requests.post(url, headers=headers, json=supabase_rows)
        if response.status_code in (200, 201):
            print(f"Synced {len(configs)} device configs to Supabase")
            return True
        else:
            print(f"Supabase device_configs error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"Device configs sync error: {e}")
        return False

def sync_device_ota_progress_to_supabase(progress):
    """Upsert device OTA progress to Supabase."""
    if not progress:
        return True

    supabase_rows = []
    for p in progress:
        supabase_rows.append({
            "device_id": p["device_id"],
            "target_version": p["target_version"],
            "chunks_received": p["chunks_received"],
            "total_chunks": p["total_chunks"],
            "started_at": p["started_at"],
            "last_chunk_at": p["last_chunk_at"],
            "status": p["status"],
            "error_message": p["error_message"]
        })

    url = f"{SUPABASE_URL}/rest/v1/device_ota_progress"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }

    try:
        response = requests.post(url, headers=headers, json=supabase_rows)
        if response.status_code in (200, 201):
            print(f"Synced {len(progress)} OTA progress records to Supabase")
            return True
        else:
            print(f"Supabase device_ota_progress error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"OTA progress sync error: {e}")
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

    # Sync OTA tables (v2.7)
    firmware_versions = get_firmware_versions()
    if firmware_versions:
        print(f"Found {len(firmware_versions)} firmware versions to sync")
        sync_firmware_versions_to_supabase(firmware_versions)

    patches = get_ota_patches()
    if patches:
        print(f"Found {len(patches)} OTA patches to sync")
        sync_ota_patches_to_supabase(patches)

    progress = get_device_ota_progress()
    if progress:
        print(f"Found {len(progress)} OTA progress records to sync")
        sync_device_ota_progress_to_supabase(progress)

    # Sync device configs (v2.9)
    configs = get_device_configs()
    if configs:
        print(f"Found {len(configs)} device configs to sync")
        sync_device_configs_to_supabase(configs)

    print("Sync complete")

if __name__ == "__main__":
    main()
