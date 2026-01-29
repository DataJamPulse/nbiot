-- Migration 008: Device Configuration Table for Remote Settings
-- Run this in Supabase SQL Editor
-- Created: 2026-01-29

-- Create device configs table for remote configuration management
CREATE TABLE IF NOT EXISTS nbiot_device_configs (
    device_id TEXT PRIMARY KEY,
    report_interval_ms INTEGER DEFAULT 300000,
    heartbeat_interval_ms INTEGER DEFAULT 86400000,
    geolocation_on_boot BOOLEAN DEFAULT true,
    wifi_channels TEXT DEFAULT '1,6,11',
    -- RSSI distance zone thresholds (dBm)
    rssi_immediate_threshold INTEGER DEFAULT -50,
    rssi_near_threshold INTEGER DEFAULT -65,
    rssi_far_threshold INTEGER DEFAULT -80,
    -- Dwell time bucket thresholds (minutes)
    dwell_short_threshold INTEGER DEFAULT 1,
    dwell_medium_threshold INTEGER DEFAULT 5,
    dwell_long_threshold INTEGER DEFAULT 10,
    -- Version tracking for device sync
    config_version INTEGER DEFAULT 1,
    updated_at TIMESTAMPTZ
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_device_configs_version ON nbiot_device_configs(config_version);

-- Enable RLS
ALTER TABLE nbiot_device_configs ENABLE ROW LEVEL SECURITY;

-- Policy for service role (full access for sync script)
CREATE POLICY "Service role has full access to device configs"
    ON nbiot_device_configs
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Policy for authenticated users (read only)
CREATE POLICY "Authenticated users can read device configs"
    ON nbiot_device_configs
    FOR SELECT
    TO authenticated
    USING (true);

-- Comment on table
COMMENT ON TABLE nbiot_device_configs IS 'Remote device configuration for NB-IoT JamBox sensors. Synced from Linode backend.';
COMMENT ON COLUMN nbiot_device_configs.rssi_immediate_threshold IS 'RSSI threshold for "At Counter" zone (default -50 dBm)';
COMMENT ON COLUMN nbiot_device_configs.rssi_near_threshold IS 'RSSI threshold for "In Store" zone (default -65 dBm)';
COMMENT ON COLUMN nbiot_device_configs.rssi_far_threshold IS 'RSSI threshold for "Window Shopping" zone (default -80 dBm)';
COMMENT ON COLUMN nbiot_device_configs.dwell_short_threshold IS 'Minutes for "Quick Glance" boundary (default 1)';
COMMENT ON COLUMN nbiot_device_configs.dwell_medium_threshold IS 'Minutes for "Browsing" boundary (default 5)';
COMMENT ON COLUMN nbiot_device_configs.dwell_long_threshold IS 'Minutes for "Shopping" boundary (default 10)';
COMMENT ON COLUMN nbiot_device_configs.config_version IS 'Incremented on each update, used by devices to detect changes';
