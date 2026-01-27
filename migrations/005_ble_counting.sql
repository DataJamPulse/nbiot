-- Migration 005: BLE Device Counting
-- Adds columns to track BLE advertisement data for accurate OS detection
--
-- BLE scanning provides reliable Apple/Android/Other classification via
-- manufacturer IDs in advertisements, unlike WiFi probe requests which
-- only show randomized MACs.
--
-- Run this in Supabase SQL Editor:

-- Add BLE counting columns to nbiot_readings
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS ble_impressions INTEGER DEFAULT 0;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS ble_unique INTEGER DEFAULT 0;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS ble_apple INTEGER DEFAULT 0;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS ble_android INTEGER DEFAULT 0;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS ble_other INTEGER DEFAULT 0;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS ble_rssi_avg INTEGER;

-- Comment on purpose
COMMENT ON COLUMN nbiot_readings.ble_impressions IS 'Total BLE advertisements detected (all randomized MACs)';
COMMENT ON COLUMN nbiot_readings.ble_unique IS 'Unique BLE devices per minute (deduplicated)';
COMMENT ON COLUMN nbiot_readings.ble_apple IS 'Apple devices (manufacturer ID 0x004C)';
COMMENT ON COLUMN nbiot_readings.ble_android IS 'Android devices (Google Fast Pair, Samsung, Xiaomi, etc.)';
COMMENT ON COLUMN nbiot_readings.ble_other IS 'Other BLE devices (wearables, IoT, etc.)';
COMMENT ON COLUMN nbiot_readings.ble_rssi_avg IS 'Average BLE signal strength (dBm)';
