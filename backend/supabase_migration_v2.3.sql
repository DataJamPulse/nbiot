-- Supabase Migration for v2.3
-- Run this in the Supabase SQL Editor (Dashboard > SQL Editor > New Query)
-- Project: IoTNB Data
-- URL: https://xopbjawzrvsoeiapoawm.supabase.co

-- Add new columns to nbiot_readings table
-- These are nullable to support backwards compatibility with older readings

ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS other_count INTEGER DEFAULT 0;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS probe_rssi_avg INTEGER;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS probe_rssi_min INTEGER;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS probe_rssi_max INTEGER;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS cell_rssi INTEGER;

-- Verify the schema after migration
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'nbiot_readings'
-- ORDER BY ordinal_position;
