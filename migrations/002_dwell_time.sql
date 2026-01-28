-- Migration 002: Add dwell time buckets to nbiot_readings
-- Run this in Supabase SQL Editor

-- Dwell time buckets track how long devices stay in range:
-- dwell_0_1: Seen in only 1 minute (drive-by traffic)
-- dwell_1_5: Seen across 2-5 minutes (brief engagement)
-- dwell_5_10: Seen across 5-10 minutes (moderate engagement)
-- dwell_10plus: Seen across 10+ minutes (highly engaged)

ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS dwell_0_1 INTEGER DEFAULT 0;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS dwell_1_5 INTEGER DEFAULT 0;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS dwell_5_10 INTEGER DEFAULT 0;
ALTER TABLE nbiot_readings ADD COLUMN IF NOT EXISTS dwell_10plus INTEGER DEFAULT 0;

-- Create index for analytics queries
CREATE INDEX IF NOT EXISTS idx_nbiot_readings_dwell ON nbiot_readings(device_id, timestamp, dwell_0_1, dwell_1_5, dwell_5_10, dwell_10plus);
