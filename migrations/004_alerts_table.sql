-- Migration 004: Create nbiot_alerts table for offline alerts
-- Run this in Supabase SQL Editor

-- Alert records to track sent alerts and prevent duplicates
CREATE TABLE IF NOT EXISTS nbiot_alerts (
    id BIGSERIAL PRIMARY KEY,
    device_id TEXT NOT NULL,
    alert_type TEXT NOT NULL,  -- 'offline', 'low_signal', 'anomaly', etc.
    severity TEXT DEFAULT 'warning',  -- 'info', 'warning', 'critical'
    message TEXT,
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for checking recent alerts (prevents duplicate notifications)
CREATE INDEX IF NOT EXISTS idx_nbiot_alerts_device_type ON nbiot_alerts(device_id, alert_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_nbiot_alerts_unacked ON nbiot_alerts(acknowledged, created_at DESC);
