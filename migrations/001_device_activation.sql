-- Migration 001: Device Activation Schema
-- Run in Supabase SQL Editor
-- Adds support for zero-touch device activation via QR code

-- Add columns to nbiot_devices for activation support
ALTER TABLE nbiot_devices ADD COLUMN IF NOT EXISTS device_pin VARCHAR(4);
ALTER TABLE nbiot_devices ADD COLUMN IF NOT EXISTS location_name TEXT;

-- Create index for faster PIN lookups
CREATE INDEX IF NOT EXISTS idx_nbiot_devices_pin ON nbiot_devices(device_id, device_pin);

-- Add comment for documentation
COMMENT ON COLUMN nbiot_devices.device_pin IS 'PIN for customer-facing device activation (4 digits)';
COMMENT ON COLUMN nbiot_devices.location_name IS 'Customer-set location name for the device';
