#!/usr/bin/env python3
"""
DataJam NB-IoT Backend Receiver v2.9
Production-ready with device authentication, management, device type classification,
WiFi-based geolocation with automatic timezone detection, extended RSSI metrics,
enhanced heartbeat tracking with uptime, BLE device counting, OTA update system,
data quality/auditability features, and remote device configuration.
v2.9: Remote configuration of RSSI thresholds, dwell time buckets, and report intervals.
"""

import sqlite3
import secrets
import hashlib
import base64
import json
import os
import requests
from datetime import datetime, timezone, timedelta
from functools import wraps
from pathlib import Path
from flask import Flask, request, jsonify, g
from timezonefinder import TimezoneFinder

app = Flask(__name__)
DB_PATH = "/opt/datajam-nbiot/data.db"

# Admin key for management endpoints - loaded from environment
ADMIN_KEY = os.environ.get("NBIOT_ADMIN_KEY", "djnb-admin-2026-change-me")

# Google Maps Geolocation API key
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

# OTA Configuration
OTA_BASE_DIR = Path("/opt/datajam-nbiot/ota")
OTA_FIRMWARE_DIR = OTA_BASE_DIR / "firmware"
OTA_PATCHES_DIR = OTA_BASE_DIR / "patches"
OTA_CHUNK_SIZE = 512  # bytes per chunk

# TimezoneFinder instance
tf = TimezoneFinder()

# ============== Database Setup ==============

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)

    # Device registry
    conn.execute("""CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT UNIQUE NOT NULL,
        token_hash TEXT NOT NULL,
        project_name TEXT,
        location_name TEXT,
        timezone TEXT DEFAULT 'UTC',
        firmware_version TEXT,
        status TEXT DEFAULT 'active',
        registered_at TEXT NOT NULL,
        last_seen_at TEXT,
        last_signal_dbm INTEGER,
        last_battery_pct INTEGER
    )""")

    # Readings v2.3 - with ISO timestamp, device type breakdown, and extended RSSI metrics
    conn.execute("""CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        impressions INTEGER NOT NULL,
        unique_count INTEGER NOT NULL,
        signal_dbm INTEGER,
        battery_pct INTEGER,
        firmware_version TEXT,
        apple_count INTEGER DEFAULT 0,
        android_count INTEGER DEFAULT 0,
        other_count INTEGER DEFAULT 0,
        probe_rssi_avg INTEGER,
        probe_rssi_min INTEGER,
        probe_rssi_max INTEGER,
        cell_rssi INTEGER,
        dwell_0_1 INTEGER DEFAULT 0,
        dwell_1_5 INTEGER DEFAULT 0,
        dwell_5_10 INTEGER DEFAULT 0,
        dwell_10plus INTEGER DEFAULT 0,
        rssi_immediate INTEGER DEFAULT 0,
        rssi_near INTEGER DEFAULT 0,
        rssi_far INTEGER DEFAULT 0,
        rssi_remote INTEGER DEFAULT 0,
        received_at TEXT NOT NULL,
        synced_to_supabase INTEGER DEFAULT 0,
        FOREIGN KEY (device_id) REFERENCES devices(device_id)
    )""")

    # Heartbeats log
    conn.execute("""CREATE TABLE IF NOT EXISTS heartbeats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        signal_dbm INTEGER,
        battery_pct INTEGER,
        firmware_version TEXT,
        uptime_seconds INTEGER,
        ip_address TEXT
    )""")

    # Device configs for remote configuration (v2.9 - added RSSI/dwell thresholds)
    conn.execute("""CREATE TABLE IF NOT EXISTS device_configs (
        device_id TEXT PRIMARY KEY,
        report_interval_ms INTEGER DEFAULT 300000,
        heartbeat_interval_ms INTEGER DEFAULT 86400000,
        geolocation_on_boot INTEGER DEFAULT 1,
        wifi_channels TEXT DEFAULT '1,6,11',
        rssi_immediate_threshold INTEGER DEFAULT -50,
        rssi_near_threshold INTEGER DEFAULT -65,
        rssi_far_threshold INTEGER DEFAULT -80,
        dwell_short_threshold INTEGER DEFAULT 1,
        dwell_medium_threshold INTEGER DEFAULT 5,
        dwell_long_threshold INTEGER DEFAULT 10,
        config_version INTEGER DEFAULT 1,
        updated_at TEXT
    )""")

    # OTA: Firmware versions registry (local SQLite mirror)
    conn.execute("""CREATE TABLE IF NOT EXISTS firmware_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version TEXT UNIQUE NOT NULL,
        release_date TEXT NOT NULL,
        binary_size INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        release_notes TEXT,
        is_current INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )""")

    # OTA: Delta patches between versions
    conn.execute("""CREATE TABLE IF NOT EXISTS ota_patches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_version TEXT NOT NULL,
        to_version TEXT NOT NULL,
        patch_size INTEGER NOT NULL,
        chunk_count INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        compression TEXT DEFAULT 'heatshrink',
        created_at TEXT NOT NULL,
        UNIQUE(from_version, to_version)
    )""")

    # OTA: Device update progress
    conn.execute("""CREATE TABLE IF NOT EXISTS device_ota_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT NOT NULL,
        target_version TEXT NOT NULL,
        chunks_received INTEGER DEFAULT 0,
        total_chunks INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        last_chunk_at TEXT,
        status TEXT DEFAULT 'pending',
        error_message TEXT,
        UNIQUE(device_id, target_version)
    )""")

    # Indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_device_time ON readings(device_id, timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_unsynced ON readings(synced_to_supabase)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ota_progress_device ON device_ota_progress(device_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_firmware_current ON firmware_versions(is_current)")

    # Migration: Add columns if they don't exist (for existing databases)
    migrations = [
        ("readings", "apple_count", "INTEGER DEFAULT 0"),
        ("readings", "android_count", "INTEGER DEFAULT 0"),
        ("readings", "other_count", "INTEGER DEFAULT 0"),
        ("readings", "probe_rssi_avg", "INTEGER"),
        ("readings", "probe_rssi_min", "INTEGER"),
        ("readings", "probe_rssi_max", "INTEGER"),
        ("readings", "cell_rssi", "INTEGER"),
        ("devices", "latitude", "REAL"),
        ("devices", "longitude", "REAL"),
        ("heartbeats", "uptime_seconds", "INTEGER"),
        ("devices", "device_pin", "VARCHAR(4)"),
        ("readings", "dwell_0_1", "INTEGER DEFAULT 0"),
        ("readings", "dwell_1_5", "INTEGER DEFAULT 0"),
        ("readings", "dwell_5_10", "INTEGER DEFAULT 0"),
        ("readings", "dwell_10plus", "INTEGER DEFAULT 0"),
        ("readings", "rssi_immediate", "INTEGER DEFAULT 0"),
        ("readings", "rssi_near", "INTEGER DEFAULT 0"),
        ("readings", "rssi_far", "INTEGER DEFAULT 0"),
        ("readings", "rssi_remote", "INTEGER DEFAULT 0"),
        # BLE device counting (v2.6 / firmware v4.0)
        ("readings", "ble_impressions", "INTEGER DEFAULT 0"),
        ("readings", "ble_unique", "INTEGER DEFAULT 0"),
        ("readings", "ble_apple", "INTEGER DEFAULT 0"),
        ("readings", "ble_android", "INTEGER DEFAULT 0"),
        ("readings", "ble_other", "INTEGER DEFAULT 0"),
        ("readings", "ble_rssi_avg", "INTEGER"),
        # OTA (v2.7)
        ("devices", "pending_command", "TEXT"),
        # Data quality & auditability (v2.8)
        ("readings", "period_start_ts", "TEXT"),
        ("readings", "overflow_count", "INTEGER DEFAULT 0"),
        ("readings", "cache_depth", "INTEGER DEFAULT 0"),
        ("readings", "send_failures", "INTEGER DEFAULT 0"),
        ("readings", "age_seconds", "INTEGER DEFAULT 0"),
        # Remote device configuration thresholds (v2.9)
        ("device_configs", "rssi_immediate_threshold", "INTEGER DEFAULT -50"),
        ("device_configs", "rssi_near_threshold", "INTEGER DEFAULT -65"),
        ("device_configs", "rssi_far_threshold", "INTEGER DEFAULT -80"),
        ("device_configs", "dwell_short_threshold", "INTEGER DEFAULT 1"),
        ("device_configs", "dwell_medium_threshold", "INTEGER DEFAULT 5"),
        ("device_configs", "dwell_long_threshold", "INTEGER DEFAULT 10"),
        ("device_configs", "config_version", "INTEGER DEFAULT 1"),
    ]

    for table, column, col_type in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            print(f"[MIGRATION] Added column {table}.{column}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Create unique index for idempotent inserts (v2.8)
    # This prevents duplicate readings from being inserted
    try:
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_period
            ON readings(device_id, period_start_ts)
            WHERE period_start_ts IS NOT NULL
        """)
        print("[MIGRATION] Created unique index idx_readings_period")
    except sqlite3.OperationalError as e:
        if "already exists" not in str(e):
            print(f"[MIGRATION] Index creation note: {e}")

    conn.commit()
    conn.close()

# ============== Authentication ==============

def hash_token(token):
    """Hash a token for secure storage."""
    return hashlib.sha256(token.encode()).hexdigest()

def verify_device_token(device_id, token):
    """Verify a device token is valid."""
    conn = get_db()
    device = conn.execute(
        "SELECT token_hash, status FROM devices WHERE device_id = ?",
        (device_id,)
    ).fetchone()

    if not device:
        return False, "Device not registered"
    if device['status'] != 'active':
        return False, f"Device status: {device['status']}"
    if device['token_hash'] != hash_token(token):
        return False, "Invalid token"

    return True, "OK"

def require_device_auth(f):
    """Decorator to require device authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({"error": "Missing Authorization header"}), 401

        token = auth[7:]  # Remove 'Bearer '

        # Try to get device_id from JSON body first, then query params
        data = request.get_json(silent=True) or {}
        device_id = data.get('d') or data.get('device_id')

        # For GET requests, also check query parameters
        if not device_id:
            device_id = request.args.get('d') or request.args.get('device_id')

        if not device_id:
            return jsonify({"error": "Missing device_id"}), 400

        valid, msg = verify_device_token(device_id, token)
        if not valid:
            return jsonify({"error": msg}), 401

        g.device_id = device_id
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    """Decorator to require admin authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({"error": "Missing Authorization header"}), 401

        token = auth[7:]
        if token != ADMIN_KEY:
            return jsonify({"error": "Invalid admin key"}), 401

        return f(*args, **kwargs)
    return decorated

# ============== Utility Functions ==============

def calculate_crc16(data: bytes) -> int:
    """Calculate CRC16-CCITT for chunk verification."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc

# ============== Public Endpoints ==============

@app.route("/health")
def health():
    """Health check - no auth required."""
    return jsonify({
        "status": "ok",
        "service": "datajam-nbiot-receiver",
        "version": "2.9"
    })

# ============== Device Endpoints (require device token) ==============

@app.route("/api/reading", methods=["POST"])
@require_device_auth
def receive_reading():
    """Receive a reading from an authenticated device."""
    try:
        data = request.get_json()
        device_id = g.device_id

        # Timestamp can be ISO string or integer
        timestamp = data.get('t') if data.get('t') is not None else data.get('timestamp')
        impressions = data.get('i') if data.get('i') is not None else data.get('impressions')
        unique_count = data.get('u') if data.get('u') is not None else data.get('unique_count')
        battery_pct = data.get('bat') if data.get('bat') is not None else data.get('battery_pct')
        firmware = data.get('fw') if data.get('fw') is not None else data.get('firmware_version')

        # Device type fields
        apple_count = data.get('apple', 0)
        android_count = data.get('android', 0)
        other_count = data.get('other', 0) or data.get('other_count', 0)

        # RSSI fields - cell_rssi replaces signal_dbm but accept both for backwards compat
        cell_rssi = data.get('cell_rssi') or data.get('sig') or data.get('signal_dbm')
        probe_rssi_avg = data.get('probe_rssi_avg')
        probe_rssi_min = data.get('probe_rssi_min')
        probe_rssi_max = data.get('probe_rssi_max')

        # Dwell time buckets (v3.0+)
        dwell_0_1 = data.get('dwell_0_1', 0) or 0
        dwell_1_5 = data.get('dwell_1_5', 0) or 0
        dwell_5_10 = data.get('dwell_5_10', 0) or 0
        dwell_10plus = data.get('dwell_10plus', 0) or 0

        # RSSI distance zones (v3.0+)
        rssi_immediate = data.get('rssi_immediate', 0) or 0
        rssi_near = data.get('rssi_near', 0) or 0
        rssi_far = data.get('rssi_far', 0) or 0
        rssi_remote = data.get('rssi_remote', 0) or 0

        # BLE device counting fields (v4.0+)
        ble_impressions = data.get('ble_i', 0) or data.get('ble_impressions', 0) or 0
        ble_unique = data.get('ble_u', 0) or data.get('ble_unique', 0) or 0
        ble_apple = data.get('ble_apple', 0) or 0
        ble_android = data.get('ble_android', 0) or 0
        ble_other = data.get('ble_other', 0) or 0
        ble_rssi_avg = data.get('ble_rssi_avg')

        # Data quality/auditability fields (v5.3 firmware / v2.8 backend)
        overflow_count = data.get('of', 0) or 0    # Uniques dropped due to cap
        cache_depth = data.get('cd', 0) or 0       # Cache depth when sent
        send_failures = data.get('sf', 0) or 0     # Consecutive failures before this
        age_seconds = data.get('age', 0) or 0      # 0 = live, >0 = cached reading

        # Keep signal_dbm for backwards compatibility in database
        signal_dbm = cell_rssi

        if not all([timestamp is not None, impressions is not None, unique_count is not None]):
            return jsonify({"error": "Missing required fields: t, i, u"}), 400

        now = datetime.now(timezone.utc)
        received_at = now.isoformat()

        # Calculate period_start_ts: when this reading's period actually occurred
        # For cached readings (age > 0), we subtract age from receive time
        period_time = now - timedelta(seconds=age_seconds)
        # Normalize to 5-minute boundary (bucket)
        period_start = period_time.replace(
            minute=(period_time.minute // 5) * 5,
            second=0,
            microsecond=0
        )
        period_start_ts = period_start.isoformat()

        conn = get_db()

        # Idempotent insert: INSERT OR IGNORE to prevent duplicates
        # Unique constraint on (device_id, period_start_ts) prevents re-ingestion
        cursor = conn.execute("""
            INSERT OR IGNORE INTO readings (device_id, timestamp, impressions, unique_count,
                                  signal_dbm, battery_pct, firmware_version,
                                  apple_count, android_count, other_count,
                                  probe_rssi_avg, probe_rssi_min, probe_rssi_max,
                                  cell_rssi, dwell_0_1, dwell_1_5, dwell_5_10, dwell_10plus,
                                  rssi_immediate, rssi_near, rssi_far, rssi_remote,
                                  ble_impressions, ble_unique, ble_apple, ble_android, ble_other, ble_rssi_avg,
                                  period_start_ts, overflow_count, cache_depth, send_failures, age_seconds,
                                  received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (device_id, timestamp, impressions, unique_count, signal_dbm,
              battery_pct, firmware, apple_count, android_count, other_count,
              probe_rssi_avg, probe_rssi_min, probe_rssi_max, cell_rssi,
              dwell_0_1, dwell_1_5, dwell_5_10, dwell_10plus,
              rssi_immediate, rssi_near, rssi_far, rssi_remote,
              ble_impressions, ble_unique, ble_apple, ble_android, ble_other, ble_rssi_avg,
              period_start_ts, overflow_count, cache_depth, send_failures, age_seconds, received_at))

        # Check if insert actually happened (or was ignored as duplicate)
        was_duplicate = cursor.rowcount == 0

        # Update device last_seen
        conn.execute("""
            UPDATE devices SET last_seen_at = ?, last_signal_dbm = ?, last_battery_pct = ?,
                               firmware_version = COALESCE(?, firmware_version)
            WHERE device_id = ?
        """, (received_at, signal_dbm, battery_pct, firmware, device_id))

        conn.commit()

        # Log for debugging
        rssi_info = ""
        if probe_rssi_avg is not None:
            rssi_info = f" probe_rssi(avg:{probe_rssi_avg} min:{probe_rssi_min} max:{probe_rssi_max})"
        dwell_info = ""
        if any([dwell_0_1, dwell_1_5, dwell_5_10, dwell_10plus]):
            dwell_info = f" dwell(0-1:{dwell_0_1} 1-5:{dwell_1_5} 5-10:{dwell_5_10} 10+:{dwell_10plus})"
        zone_info = ""
        if any([rssi_immediate, rssi_near, rssi_far, rssi_remote]):
            zone_info = f" zones(imm:{rssi_immediate} near:{rssi_near} far:{rssi_far} remote:{rssi_remote})"
        ble_info = ""
        if any([ble_impressions, ble_unique]):
            ble_info = f" BLE(i:{ble_impressions} u:{ble_unique} Apple:{ble_apple} Android:{ble_android} Other:{ble_other})"
        quality_info = ""
        if any([overflow_count, cache_depth, send_failures, age_seconds]):
            quality_info = f" quality(of:{overflow_count} cd:{cache_depth} sf:{send_failures} age:{age_seconds}s)"
        dup_info = " [DUPLICATE]" if was_duplicate else ""
        print(f"[READING] {device_id}: {impressions} probes, {unique_count} unique "
              f"(Apple:{apple_count} Android:{android_count} Other:{other_count}) "
              f"cell_rssi:{cell_rssi}{rssi_info}{dwell_info}{zone_info}{ble_info}{quality_info}{dup_info} @ {period_start_ts}")

        # Check for pending command
        response = {"status": "ok"}
        if was_duplicate:
            response["note"] = "duplicate_ignored"

        device_row = conn.execute("SELECT pending_command FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        if device_row and device_row['pending_command']:
            command = device_row['pending_command']
            response['command'] = command
            # Clear the pending command
            conn.execute("UPDATE devices SET pending_command = NULL WHERE device_id = ?", (device_id,))
            conn.commit()
            print(f"[COMMAND] Sending to {device_id}: {command}", flush=True)

        return jsonify(response), 201

    except Exception as e:
        print(f"[ERROR] receive_reading: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/heartbeat", methods=["POST"])
@require_device_auth
def heartbeat():
    """Device heartbeat - 'I'm alive' signal with firmware version and uptime tracking."""
    try:
        data = request.get_json()
        device_id = g.device_id

        # Parse heartbeat payload - support both old and new field names
        # New format: {"d":"JBNB0001","v":"2.8","uptime":86400,"cell_rssi":-85}
        # Old format: {"d":"JBNB0001","sig":-85,"bat":100,"fw":"2.0"}
        signal_dbm = data.get('cell_rssi') or data.get('sig') or data.get('signal_dbm')
        battery_pct = data.get('bat') or data.get('battery_pct')
        firmware = data.get('v') or data.get('fw') or data.get('firmware_version')
        uptime_seconds = data.get('uptime') or data.get('uptime_seconds')

        now = datetime.now(timezone.utc).isoformat()
        ip_address = request.remote_addr
        conn = get_db()

        # Log heartbeat with uptime
        conn.execute("""
            INSERT INTO heartbeats (device_id, timestamp, signal_dbm, battery_pct, firmware_version, uptime_seconds, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (device_id, now, signal_dbm, battery_pct, firmware, uptime_seconds, ip_address))

        # Update device last_seen and firmware_version
        conn.execute("""
            UPDATE devices SET last_seen_at = ?, last_signal_dbm = ?, last_battery_pct = ?,
                               firmware_version = COALESCE(?, firmware_version)
            WHERE device_id = ?
        """, (now, signal_dbm, battery_pct, firmware, device_id))

        conn.commit()

        # Log for debugging
        uptime_str = f"{uptime_seconds}s" if uptime_seconds is not None else "N/A"
        print(f"[HEARTBEAT] {device_id} v{firmware} uptime:{uptime_str} cell:{signal_dbm}dBm", flush=True)

        # Check for pending command
        response = {"status": "ok", "server_time": now}

        # Include config_version so device knows if it needs to fetch new config
        config_row = conn.execute("SELECT config_version FROM device_configs WHERE device_id = ?", (device_id,)).fetchone()
        response['config_version'] = config_row['config_version'] if config_row else 1

        device_row = conn.execute("SELECT pending_command FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        if device_row and device_row['pending_command']:
            command = device_row['pending_command']
            response['command'] = command
            # Clear the pending command
            conn.execute("UPDATE devices SET pending_command = NULL WHERE device_id = ?", (device_id,))
            conn.commit()
            print(f"[COMMAND] Sending to {device_id}: {command}", flush=True)

        return jsonify(response), 200

    except Exception as e:
        print(f"[ERROR] heartbeat: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

# ============== Remote Configuration ==============

@app.route("/api/config/<device_id>", methods=["GET"])
@require_device_auth
def get_device_config(device_id):
    """Return device configuration for remote config pull."""
    try:
        conn = get_db()

        # Check device exists
        device = conn.execute(
            "SELECT device_id FROM devices WHERE device_id = ?",
            (device_id,)
        ).fetchone()

        if not device:
            return jsonify({"error": "Device not found"}), 404

        # Get device-specific config or return defaults
        config = conn.execute(
            "SELECT * FROM device_configs WHERE device_id = ?",
            (device_id,)
        ).fetchone()

        if config:
            response = {
                "config_version": config.get('config_version', 1) if hasattr(config, 'get') else (config['config_version'] if 'config_version' in config.keys() else 1),
                "report_interval_ms": config['report_interval_ms'],
                "heartbeat_interval_ms": config['heartbeat_interval_ms'],
                "geolocation_on_boot": bool(config['geolocation_on_boot']),
                "wifi_channels": [int(c) for c in config['wifi_channels'].split(',')],
                # RSSI thresholds (v2.9)
                "rssi_immediate_threshold": config['rssi_immediate_threshold'] if 'rssi_immediate_threshold' in config.keys() else -50,
                "rssi_near_threshold": config['rssi_near_threshold'] if 'rssi_near_threshold' in config.keys() else -65,
                "rssi_far_threshold": config['rssi_far_threshold'] if 'rssi_far_threshold' in config.keys() else -80,
                # Dwell time thresholds (v2.9)
                "dwell_short_threshold": config['dwell_short_threshold'] if 'dwell_short_threshold' in config.keys() else 1,
                "dwell_medium_threshold": config['dwell_medium_threshold'] if 'dwell_medium_threshold' in config.keys() else 5,
                "dwell_long_threshold": config['dwell_long_threshold'] if 'dwell_long_threshold' in config.keys() else 10,
                "updated_at": config['updated_at']
            }
        else:
            # Return defaults
            response = {
                "config_version": 1,
                "report_interval_ms": 300000,      # 5 minutes
                "heartbeat_interval_ms": 86400000, # 24 hours
                "geolocation_on_boot": True,
                "wifi_channels": [1, 6, 11],
                # RSSI thresholds (v2.9)
                "rssi_immediate_threshold": -50,
                "rssi_near_threshold": -65,
                "rssi_far_threshold": -80,
                # Dwell time thresholds (v2.9)
                "dwell_short_threshold": 1,
                "dwell_medium_threshold": 5,
                "dwell_long_threshold": 10,
                "updated_at": None
            }

        print(f"[CONFIG] {device_id}: interval={response['report_interval_ms']}ms v{response['config_version']}")
        return jsonify(response), 200

    except Exception as e:
        print(f"[ERROR] get_device_config: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

@app.route("/api/config/<device_id>", methods=["PUT"])
@require_admin
def update_device_config(device_id):
    """Update device configuration (admin only)."""
    try:
        data = request.get_json()
        conn = get_db()

        # Validate RSSI thresholds (must be in order: immediate > near > far)
        rssi_immediate = data.get('rssi_immediate_threshold', -50)
        rssi_near = data.get('rssi_near_threshold', -65)
        rssi_far = data.get('rssi_far_threshold', -80)

        if not (-30 >= rssi_immediate >= -60):
            return jsonify({"error": "rssi_immediate_threshold must be between -30 and -60"}), 400
        if not (-50 >= rssi_near >= -75):
            return jsonify({"error": "rssi_near_threshold must be between -50 and -75"}), 400
        if not (-65 >= rssi_far >= -90):
            return jsonify({"error": "rssi_far_threshold must be between -65 and -90"}), 400
        if not (rssi_immediate > rssi_near > rssi_far):
            return jsonify({"error": "RSSI thresholds must be in order: immediate > near > far"}), 400

        # Validate dwell thresholds
        dwell_short = data.get('dwell_short_threshold', 1)
        dwell_medium = data.get('dwell_medium_threshold', 5)
        dwell_long = data.get('dwell_long_threshold', 10)

        if not (1 <= dwell_short <= 5):
            return jsonify({"error": "dwell_short_threshold must be between 1 and 5"}), 400
        if not (2 <= dwell_medium <= 15):
            return jsonify({"error": "dwell_medium_threshold must be between 2 and 15"}), 400
        if not (5 <= dwell_long <= 30):
            return jsonify({"error": "dwell_long_threshold must be between 5 and 30"}), 400
        if not (dwell_short < dwell_medium < dwell_long):
            return jsonify({"error": "Dwell thresholds must be in order: short < medium < long"}), 400

        # Validate report interval (1-60 minutes)
        report_interval = data.get('report_interval_ms', 300000)
        if not (60000 <= report_interval <= 3600000):
            return jsonify({"error": "report_interval_ms must be between 60000 (1 min) and 3600000 (60 min)"}), 400

        # Get current config_version and increment
        existing = conn.execute(
            "SELECT config_version FROM device_configs WHERE device_id = ?",
            (device_id,)
        ).fetchone()
        new_version = (existing['config_version'] + 1) if existing and existing['config_version'] else 1

        now = datetime.now(timezone.utc).isoformat()
        wifi_channels = ','.join(str(c) for c in data.get('wifi_channels', [1, 6, 11]))

        conn.execute("""
            INSERT OR REPLACE INTO device_configs
            (device_id, report_interval_ms, heartbeat_interval_ms, geolocation_on_boot, wifi_channels,
             rssi_immediate_threshold, rssi_near_threshold, rssi_far_threshold,
             dwell_short_threshold, dwell_medium_threshold, dwell_long_threshold,
             config_version, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            device_id,
            report_interval,
            data.get('heartbeat_interval_ms', 86400000),
            1 if data.get('geolocation_on_boot', True) else 0,
            wifi_channels,
            rssi_immediate,
            rssi_near,
            rssi_far,
            dwell_short,
            dwell_medium,
            dwell_long,
            new_version,
            now
        ))
        conn.commit()

        print(f"[CONFIG] Updated config for {device_id} -> v{new_version}")
        return jsonify({"status": "ok", "config_version": new_version, "updated_at": now}), 200

    except Exception as e:
        print(f"[ERROR] update_device_config: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

# ============== Geolocation Endpoints ==============

def google_geolocate(wifi_networks):
    """
    Call Google Maps Geolocation API with WiFi access points.
    Returns (latitude, longitude) tuple or (None, None) on failure.
    """
    if not wifi_networks:
        return None, None

    # Build request payload for Google Geolocation API
    wifi_access_points = []
    for network in wifi_networks:
        ap = {
            "macAddress": network.get("bssid", ""),
            "signalStrength": network.get("rssi", -100),
            "channel": network.get("ch", 0)
        }
        wifi_access_points.append(ap)

    payload = {
        "wifiAccessPoints": wifi_access_points
    }

    url = f"https://www.googleapis.com/geolocation/v1/geolocate?key={GOOGLE_MAPS_API_KEY}"

    try:
        print(f"[GEO] Calling Google API with {len(wifi_access_points)} APs", flush=True)
        response = requests.post(url, json=payload, timeout=10)
        print(f"[GEO] Google API response: {response.status_code}", flush=True)
        if response.status_code == 200:
            data = response.json()
            location = data.get("location", {})
            lat = location.get("lat")
            lng = location.get("lng")
            accuracy = data.get("accuracy")
            print(f"[GEO] Google API: lat={lat}, lng={lng}, accuracy={accuracy}m", flush=True)
            return lat, lng
        else:
            print(f"[GEO] Google API error: {response.status_code} - {response.text}", flush=True)
            return None, None
    except Exception as e:
        print(f"[GEO] Google API exception: {e}", flush=True)
        return None, None


@app.route("/api/geolocation", methods=["POST"])
@require_device_auth
def receive_geolocation():
    """Receive WiFi scan data from device and determine location/timezone."""
    try:
        data = request.get_json()
        device_id = g.device_id
        wifi_networks = data.get('wifi', [])

        if not wifi_networks:
            return jsonify({"error": "No WiFi networks provided"}), 400

        print(f"[GEO] Received {len(wifi_networks)} WiFi networks from {device_id}", flush=True)
        for i, n in enumerate(wifi_networks[:3]):  # Log first 3
            print(f"[GEO]   {i+1}: {n.get('bssid')} rssi={n.get('rssi')} ch={n.get('ch')}", flush=True)

        # Call Google Geolocation API
        lat, lng = google_geolocate(wifi_networks)

        if lat is None or lng is None:
            return jsonify({
                "status": "error",
                "message": "Could not determine location from WiFi networks"
            }), 200

        # Determine timezone from coordinates
        timezone_str = tf.timezone_at(lat=lat, lng=lng)
        if not timezone_str:
            timezone_str = "UTC"
            print(f"[GEO] Could not determine timezone, defaulting to UTC", flush=True)
        else:
            print(f"[GEO] Timezone: {timezone_str}", flush=True)

        # Update device record with location and timezone
        conn = get_db()
        conn.execute("""
            UPDATE devices
            SET latitude = ?, longitude = ?, timezone = ?, last_seen_at = ?
            WHERE device_id = ?
        """, (lat, lng, timezone_str, datetime.now(timezone.utc).isoformat(), device_id))
        conn.commit()

        print(f"[GEO] Updated {device_id}: lat={lat}, lng={lng}, tz={timezone_str}", flush=True)

        return jsonify({
            "status": "ok",
            "lat": lat,
            "lng": lng,
            "timezone": timezone_str
        }), 200

    except Exception as e:
        print(f"[ERROR] receive_geolocation: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

# ============== OTA Update Endpoints ==============

@app.route("/api/ota/check", methods=["POST"])
@require_device_auth
def ota_check():
    """
    Device checks for available firmware updates.
    Request: {"d": "JBNB0001", "v": "4.6"}
    Response: {"update_available": true, "target_version": "4.7", "patch_size": 12345, "chunk_count": 25}
    """
    try:
        data = request.get_json()
        device_id = g.device_id
        current_version = data.get('v') or data.get('version')

        if not current_version:
            return jsonify({"error": "Missing current version (v)"}), 400

        conn = get_db()

        # Get current firmware version
        current_fw = conn.execute(
            "SELECT version FROM firmware_versions WHERE is_current = 1"
        ).fetchone()

        if not current_fw:
            print(f"[OTA] {device_id}: No current firmware registered")
            return jsonify({"update_available": False, "reason": "no_current_firmware"}), 200

        target_version = current_fw['version']

        # Check if device already has latest
        if current_version == target_version:
            print(f"[OTA] {device_id}: Already on latest v{target_version}")
            return jsonify({"update_available": False, "reason": "up_to_date"}), 200

        # Check if patch exists
        patch = conn.execute("""
            SELECT patch_size, chunk_count, sha256
            FROM ota_patches
            WHERE from_version = ? AND to_version = ?
        """, (current_version, target_version)).fetchone()

        if not patch:
            print(f"[OTA] {device_id}: No patch from v{current_version} to v{target_version}")
            return jsonify({
                "update_available": False,
                "reason": "no_patch",
                "current": current_version,
                "target": target_version
            }), 200

        # Check if device already has an in-progress update
        progress = conn.execute("""
            SELECT status, chunks_received, total_chunks
            FROM device_ota_progress
            WHERE device_id = ? AND target_version = ?
        """, (device_id, target_version)).fetchone()

        response = {
            "update_available": True,
            "target_version": target_version,
            "patch_size": patch['patch_size'],
            "chunk_count": patch['chunk_count'],
            "chunk_size": OTA_CHUNK_SIZE,
            "patch_sha256": patch['sha256']
        }

        if progress:
            response["resume_from"] = progress['chunks_received']
            response["status"] = progress['status']
            print(f"[OTA] {device_id}: Resume update to v{target_version} from chunk {progress['chunks_received']}")
        else:
            # Create new progress record
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                INSERT INTO device_ota_progress (device_id, target_version, total_chunks, started_at, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (device_id, target_version, patch['chunk_count'], now))
            conn.commit()
            response["resume_from"] = 0
            response["status"] = "pending"
            print(f"[OTA] {device_id}: New update available v{current_version} -> v{target_version}")

        return jsonify(response), 200

    except Exception as e:
        print(f"[ERROR] ota_check: {e}", flush=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/ota/chunk", methods=["GET"])
@require_device_auth
def ota_get_chunk():
    """
    Get a single chunk of the OTA patch.
    Query params: ?d=JBNB0001&from=4.6&to=4.7&chunk=0
    Response: {"chunk": 0, "data": "base64...", "crc16": 12345, "total": 25}
    """
    try:
        device_id = request.args.get('d') or g.device_id
        from_version = request.args.get('from')
        to_version = request.args.get('to')
        chunk_index = request.args.get('chunk', type=int)

        if not all([from_version, to_version, chunk_index is not None]):
            return jsonify({"error": "Missing required params: from, to, chunk"}), 400

        # Load patch file
        patch_path = OTA_PATCHES_DIR / f"patch_{from_version}_to_{to_version}.bin"
        if not patch_path.exists():
            return jsonify({"error": "Patch not found"}), 404

        # Load metadata for CRC verification
        meta_path = OTA_PATCHES_DIR / f"patch_{from_version}_to_{to_version}.json"
        if not meta_path.exists():
            return jsonify({"error": "Patch metadata not found"}), 404

        with open(meta_path) as f:
            metadata = json.load(f)

        total_chunks = metadata['chunk_count']

        if chunk_index < 0 or chunk_index >= total_chunks:
            return jsonify({"error": f"Invalid chunk index. Valid: 0-{total_chunks-1}"}), 400

        # Read the specific chunk
        with open(patch_path, 'rb') as f:
            f.seek(chunk_index * OTA_CHUNK_SIZE)
            chunk_data = f.read(OTA_CHUNK_SIZE)

        # Calculate CRC16 for this chunk
        crc16 = calculate_crc16(chunk_data)

        # Base64 encode for JSON transport
        chunk_b64 = base64.b64encode(chunk_data).decode('ascii')

        # Update progress
        conn = get_db()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE device_ota_progress
            SET chunks_received = ?, last_chunk_at = ?, status = 'downloading'
            WHERE device_id = ? AND target_version = ? AND chunks_received < ?
        """, (chunk_index + 1, now, device_id, to_version, chunk_index + 1))
        conn.commit()

        print(f"[OTA] {device_id}: Chunk {chunk_index + 1}/{total_chunks} ({len(chunk_data)} bytes)")

        return jsonify({
            "chunk": chunk_index,
            "data": chunk_b64,
            "size": len(chunk_data),
            "crc16": crc16,
            "total": total_chunks
        }), 200

    except Exception as e:
        print(f"[ERROR] ota_get_chunk: {e}", flush=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/ota/complete", methods=["POST"])
@require_device_auth
def ota_complete():
    """
    Device reports successful OTA update.
    Request: {"d": "JBNB0001", "v": "4.7", "success": true}
    """
    try:
        data = request.get_json()
        device_id = g.device_id
        new_version = data.get('v') or data.get('version')
        success = data.get('success', False)
        error_message = data.get('error')

        if not new_version:
            return jsonify({"error": "Missing version (v)"}), 400

        conn = get_db()
        now = datetime.now(timezone.utc).isoformat()

        if success:
            # Update progress to complete
            conn.execute("""
                UPDATE device_ota_progress
                SET status = 'complete', last_chunk_at = ?
                WHERE device_id = ? AND target_version = ?
            """, (now, device_id, new_version))

            # Update device firmware version
            conn.execute("""
                UPDATE devices
                SET firmware_version = ?, last_seen_at = ?
                WHERE device_id = ?
            """, (new_version, now, device_id))

            conn.commit()
            print(f"[OTA] {device_id}: Update to v{new_version} COMPLETE")

            return jsonify({"status": "ok", "message": "OTA update confirmed"}), 200

        else:
            # Update progress to failed
            conn.execute("""
                UPDATE device_ota_progress
                SET status = 'failed', error_message = ?, last_chunk_at = ?
                WHERE device_id = ? AND target_version = ?
            """, (error_message, now, device_id, new_version))
            conn.commit()

            print(f"[OTA] {device_id}: Update to v{new_version} FAILED - {error_message}")

            return jsonify({"status": "failed", "message": error_message}), 200

    except Exception as e:
        print(f"[ERROR] ota_complete: {e}", flush=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/ota/register-firmware", methods=["POST"])
@require_admin
def ota_register_firmware():
    """
    Register a new firmware version (admin only).
    Request: {"version": "4.7", "binary_size": 456789, "sha256": "abc123...", "release_notes": "...", "is_current": true}
    """
    try:
        data = request.get_json()
        version = data.get('version')
        binary_size = data.get('binary_size')
        sha256 = data.get('sha256')
        release_notes = data.get('release_notes', '')
        is_current = data.get('is_current', False)

        if not all([version, binary_size, sha256]):
            return jsonify({"error": "Missing required fields: version, binary_size, sha256"}), 400

        conn = get_db()
        now = datetime.now(timezone.utc).isoformat()

        # If marking as current, unset previous current
        if is_current:
            conn.execute("UPDATE firmware_versions SET is_current = 0 WHERE is_current = 1")

        # Insert or update firmware version
        try:
            conn.execute("""
                INSERT INTO firmware_versions (version, release_date, binary_size, sha256, release_notes, is_current, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (version, now, binary_size, sha256, release_notes, 1 if is_current else 0, now))
        except sqlite3.IntegrityError:
            # Version exists, update it
            conn.execute("""
                UPDATE firmware_versions
                SET binary_size = ?, sha256 = ?, release_notes = ?, is_current = ?
                WHERE version = ?
            """, (binary_size, sha256, release_notes, 1 if is_current else 0, version))

        conn.commit()

        print(f"[OTA] Registered firmware v{version} (current={is_current})")

        return jsonify({
            "status": "ok",
            "version": version,
            "is_current": is_current
        }), 201

    except Exception as e:
        print(f"[ERROR] ota_register_firmware: {e}", flush=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/ota/register-patch", methods=["POST"])
@require_admin
def ota_register_patch():
    """
    Register a patch after generation (admin only).
    Request: {"from_version": "4.6", "to_version": "4.7", "patch_size": 12345, "chunk_count": 25, "sha256": "abc..."}
    """
    try:
        data = request.get_json()
        from_version = data.get('from_version')
        to_version = data.get('to_version')
        patch_size = data.get('patch_size')
        chunk_count = data.get('chunk_count')
        sha256 = data.get('sha256')
        compression = data.get('compression', 'heatshrink')

        if not all([from_version, to_version, patch_size, chunk_count, sha256]):
            return jsonify({"error": "Missing required fields"}), 400

        conn = get_db()
        now = datetime.now(timezone.utc).isoformat()

        try:
            conn.execute("""
                INSERT INTO ota_patches (from_version, to_version, patch_size, chunk_count, sha256, compression, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (from_version, to_version, patch_size, chunk_count, sha256, compression, now))
        except sqlite3.IntegrityError:
            conn.execute("""
                UPDATE ota_patches
                SET patch_size = ?, chunk_count = ?, sha256 = ?, compression = ?
                WHERE from_version = ? AND to_version = ?
            """, (patch_size, chunk_count, sha256, compression, from_version, to_version))

        conn.commit()

        print(f"[OTA] Registered patch v{from_version} -> v{to_version} ({patch_size} bytes, {chunk_count} chunks)")

        return jsonify({
            "status": "ok",
            "from_version": from_version,
            "to_version": to_version,
            "chunk_count": chunk_count
        }), 201

    except Exception as e:
        print(f"[ERROR] ota_register_patch: {e}", flush=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/ota/status", methods=["GET"])
@require_admin
def ota_status():
    """
    Get OTA status for all devices (admin only).
    Returns firmware versions, patches, and device update progress.
    """
    try:
        conn = get_db()

        # Get all firmware versions
        firmware = conn.execute("""
            SELECT version, release_date, binary_size, sha256, release_notes, is_current
            FROM firmware_versions
            ORDER BY created_at DESC
        """).fetchall()

        # Get all patches
        patches = conn.execute("""
            SELECT from_version, to_version, patch_size, chunk_count, sha256, compression, created_at
            FROM ota_patches
            ORDER BY created_at DESC
        """).fetchall()

        # Get device update progress
        progress = conn.execute("""
            SELECT p.device_id, p.target_version, p.chunks_received, p.total_chunks,
                   p.started_at, p.last_chunk_at, p.status, p.error_message,
                   d.firmware_version as current_version
            FROM device_ota_progress p
            JOIN devices d ON p.device_id = d.device_id
            ORDER BY p.started_at DESC
            LIMIT 50
        """).fetchall()

        # Get devices needing updates
        current_fw = conn.execute(
            "SELECT version FROM firmware_versions WHERE is_current = 1"
        ).fetchone()

        devices_needing_update = []
        if current_fw:
            devices = conn.execute("""
                SELECT device_id, firmware_version, last_seen_at
                FROM devices
                WHERE status = 'active'
                  AND firmware_version IS NOT NULL
                  AND firmware_version != ?
            """, (current_fw['version'],)).fetchall()
            devices_needing_update = [dict(d) for d in devices]

        return jsonify({
            "current_version": current_fw['version'] if current_fw else None,
            "firmware_versions": [dict(f) for f in firmware],
            "patches": [dict(p) for p in patches],
            "update_progress": [dict(p) for p in progress],
            "devices_needing_update": devices_needing_update
        }), 200

    except Exception as e:
        print(f"[ERROR] ota_status: {e}", flush=True)
        return jsonify({"error": str(e)}), 500


# ============== Admin Endpoints ==============

@app.route("/api/device/register", methods=["POST"])
@require_admin
def register_device():
    """Register a new device (admin only). Returns the device token."""
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        project_name = data.get('project_name')
        location_name = data.get('location_name')
        tz = data.get('timezone', 'UTC')

        if not device_id:
            return jsonify({"error": "Missing device_id"}), 400

        # Generate secure token
        token = secrets.token_urlsafe(32)
        token_hash = hash_token(token)
        now = datetime.now(timezone.utc).isoformat()

        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO devices (device_id, token_hash, project_name, location_name, timezone, registered_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (device_id, token_hash, project_name, location_name, tz, now))
            conn.commit()
        except sqlite3.IntegrityError:
            return jsonify({"error": "Device already registered"}), 409

        return jsonify({
            "status": "ok",
            "device_id": device_id,
            "token": token,
            "message": "Save this token securely - it cannot be retrieved later"
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/device/<device_id>/regenerate-token", methods=["POST"])
@require_admin
def regenerate_token(device_id):
    """Regenerate a device's token (admin only)."""
    try:
        conn = get_db()
        device = conn.execute("SELECT id FROM devices WHERE device_id = ?", (device_id,)).fetchone()

        if not device:
            return jsonify({"error": "Device not found"}), 404

        token = secrets.token_urlsafe(32)
        token_hash = hash_token(token)

        conn.execute("UPDATE devices SET token_hash = ? WHERE device_id = ?", (token_hash, device_id))
        conn.commit()

        return jsonify({
            "status": "ok",
            "device_id": device_id,
            "token": token,
            "message": "Old token is now invalid"
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/device/<device_id>/status", methods=["PUT"])
@require_admin
def update_device_status(device_id):
    """Update device status (active/inactive/maintenance)."""
    try:
        data = request.get_json()
        status = data.get('status')

        if status not in ['active', 'inactive', 'maintenance']:
            return jsonify({"error": "Invalid status. Use: active, inactive, maintenance"}), 400

        conn = get_db()
        result = conn.execute("UPDATE devices SET status = ? WHERE device_id = ?", (status, device_id))
        conn.commit()

        if result.rowcount == 0:
            return jsonify({"error": "Device not found"}), 404

        return jsonify({"status": "ok", "device_id": device_id, "new_status": status}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/device/<device_id>/command", methods=["POST"])
@require_admin
def queue_command(device_id):
    """Queue a command for a device (executed on next heartbeat)."""
    try:
        data = request.get_json()
        command = data.get('command')

        valid_commands = ['reboot', 'send_now', 'geolocate', 'ota_check']
        if command not in valid_commands:
            return jsonify({"error": f"Invalid command. Use: {', '.join(valid_commands)}"}), 400

        conn = get_db()

        # Check device exists
        device = conn.execute("SELECT device_id FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        if not device:
            return jsonify({"error": "Device not found"}), 404

        # Queue the command
        conn.execute("UPDATE devices SET pending_command = ? WHERE device_id = ?", (command, device_id))
        conn.commit()

        print(f"[COMMAND] Queued for {device_id}: {command}", flush=True)

        return jsonify({"status": "queued", "device_id": device_id, "command": command}), 200

    except Exception as e:
        print(f"[ERROR] queue_command: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

@app.route("/api/device/<device_id>/location", methods=["PUT"])
@require_admin
def update_device_location(device_id):
    """Manually set device location (lat/lng)."""
    try:
        data = request.get_json()
        lat = data.get('latitude')
        lng = data.get('longitude')
        location_name = data.get('location_name')

        if lat is None or lng is None:
            return jsonify({"error": "latitude and longitude are required"}), 400

        # Validate coordinates
        try:
            lat = float(lat)
            lng = float(lng)
            if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
                raise ValueError("Out of range")
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid coordinates"}), 400

        conn = get_db()

        # Check device exists
        device = conn.execute("SELECT device_id FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        if not device:
            return jsonify({"error": "Device not found"}), 404

        # Determine timezone from coordinates
        try:
            timezone_str = tf.timezone_at(lat=lat, lng=lng)
        except:
            timezone_str = "UTC"

        # Update location
        if location_name:
            conn.execute("""
                UPDATE devices SET latitude = ?, longitude = ?, timezone = ?, location_name = ?
                WHERE device_id = ?
            """, (lat, lng, timezone_str, location_name, device_id))
        else:
            conn.execute("""
                UPDATE devices SET latitude = ?, longitude = ?, timezone = ?
                WHERE device_id = ?
            """, (lat, lng, timezone_str, device_id))
        conn.commit()

        print(f"[LOCATION] Manual update {device_id}: lat={lat}, lng={lng}, tz={timezone_str}", flush=True)

        return jsonify({
            "status": "ok",
            "device_id": device_id,
            "latitude": lat,
            "longitude": lng,
            "timezone": timezone_str
        }), 200

    except Exception as e:
        print(f"[ERROR] update_device_location: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

@app.route("/api/device/<device_id>/pin", methods=["PUT"])
@require_admin
def update_device_pin(device_id):
    """Set device PIN for customer activation portal."""
    try:
        data = request.get_json()
        pin = data.get('pin')

        if not pin or len(pin) != 4 or not pin.isdigit():
            return jsonify({"error": "PIN must be exactly 4 digits"}), 400

        conn = get_db()

        # Check device exists
        device = conn.execute("SELECT device_id FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        if not device:
            return jsonify({"error": "Device not found"}), 404

        # Update PIN
        conn.execute("UPDATE devices SET device_pin = ? WHERE device_id = ?", (pin, device_id))
        conn.commit()

        print(f"[PIN] Set PIN for {device_id}", flush=True)

        return jsonify({
            "success": True,
            "device_id": device_id,
            "message": "PIN updated successfully"
        }), 200

    except Exception as e:
        print(f"[ERROR] update_device_pin: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

@app.route("/api/devices")
@require_admin
def list_devices():
    """List all devices with their status."""
    conn = get_db()
    rows = conn.execute("""
        SELECT device_id, project_name, location_name, timezone, firmware_version,
               status, registered_at, last_seen_at, last_signal_dbm, last_battery_pct,
               latitude, longitude, device_pin
        FROM devices ORDER BY device_id
    """).fetchall()

    return jsonify([dict(row) for row in rows])

@app.route("/api/readings")
@require_admin
def get_readings():
    """Get recent readings (admin only)."""
    device_id = request.args.get('device_id')
    limit = request.args.get('limit', 100, type=int)

    conn = get_db()
    if device_id:
        rows = conn.execute("""
            SELECT * FROM readings WHERE device_id = ?
            ORDER BY id DESC LIMIT ?
        """, (device_id, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM readings ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()

    return jsonify([dict(row) for row in rows])

@app.route("/api/stats")
@require_admin
def get_stats():
    """Get system stats (admin only)."""
    conn = get_db()
    stats = conn.execute("""
        SELECT
            (SELECT COUNT(*) FROM readings) as total_readings,
            (SELECT COUNT(*) FROM devices) as total_devices,
            (SELECT COUNT(*) FROM devices WHERE status = 'active') as active_devices,
            (SELECT COUNT(*) FROM readings WHERE synced_to_supabase = 0) as unsynced_readings,
            (SELECT SUM(impressions) FROM readings) as total_impressions,
            (SELECT SUM(unique_count) FROM readings) as total_unique,
            (SELECT SUM(apple_count) FROM readings) as total_apple,
            (SELECT SUM(android_count) FROM readings) as total_android,
            (SELECT SUM(other_count) FROM readings) as total_other
    """).fetchone()

    return jsonify(dict(stats))

@app.route("/api/heartbeats")
@require_admin
def get_heartbeats():
    """Get recent heartbeats (admin only)."""
    device_id = request.args.get('device_id')
    limit = request.args.get('limit', 50, type=int)

    conn = get_db()
    if device_id:
        rows = conn.execute("""
            SELECT * FROM heartbeats WHERE device_id = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (device_id, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM heartbeats ORDER BY timestamp DESC LIMIT ?
        """, (limit,)).fetchall()

    return jsonify([dict(row) for row in rows])

# ============== Startup ==============

if __name__ == "__main__":
    init_db()
    # Ensure OTA directories exist
    OTA_FIRMWARE_DIR.mkdir(parents=True, exist_ok=True)
    OTA_PATCHES_DIR.mkdir(parents=True, exist_ok=True)
    print("DataJam NB-IoT Receiver v2.9 starting on port 5000...")
    print("Features: Device auth, ISO timestamps, Apple/Android/Other classification, extended RSSI metrics,")
    print("          WiFi geolocation, heartbeat with uptime, device PIN, BLE counting, OTA updates,")
    print("          Remote device configuration (RSSI/dwell thresholds, report intervals)")
    print(f"OTA Directory: {OTA_BASE_DIR}")
    print(f"Admin key: {ADMIN_KEY}")
    app.run(host="0.0.0.0", port=5000)
