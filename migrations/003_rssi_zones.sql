-- Migration 003: Add RSSI distance zones to nbiot_readings
-- Run this in Supabase SQL Editor

-- RSSI zones prove viewability by categorizing probes by signal strength:
-- rssi_immediate: > -50 dBm (within ~2m, very close)
-- rssi_near: -50 to -65 dBm (~2-5m, clearly visible)
-- rssi_far: -65 to -80 dBm (~5-15m, in vicinity)
-- rssi_remote: < -80 dBm (>15m, passing by)

ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS rssi_immediate INTEGER DEFAULT 0;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS rssi_near INTEGER DEFAULT 0;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS rssi_far INTEGER DEFAULT 0;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS rssi_remote INTEGER DEFAULT 0;

-- Create index for analytics queries
CREATE INDEX IF NOT EXISTS idx_nbiot_readings_rssi_zones ON nbiot_readings(device_id, timestamp, rssi_immediate, rssi_near, rssi_far, rssi_remote);
