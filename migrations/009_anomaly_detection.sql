-- Migration: Add anomaly detection columns to nbiot_devices
-- Run this in Supabase SQL Editor

ALTER TABLE nbiot_devices ADD COLUMN IF NOT EXISTS anomalous BOOLEAN DEFAULT FALSE;
ALTER TABLE nbiot_devices ADD COLUMN IF NOT EXISTS anomaly_reason TEXT;
ALTER TABLE nbiot_devices ADD COLUMN IF NOT EXISTS anomaly_detected_at TIMESTAMPTZ;

-- Index for quickly finding anomalous devices
CREATE INDEX IF NOT EXISTS idx_nbiot_devices_anomalous ON nbiot_devices(anomalous) WHERE anomalous = TRUE;

COMMENT ON COLUMN nbiot_devices.anomalous IS 'True if device showing unusual request patterns';
COMMENT ON COLUMN nbiot_devices.anomaly_reason IS 'Description of the anomaly (e.g., "Burst: 73 requests in 60s")';
COMMENT ON COLUMN nbiot_devices.anomaly_detected_at IS 'When the anomaly was first detected';
