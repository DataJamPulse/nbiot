#!/usr/bin/env python3
"""
SIM7028 Band Configuration - Check supported commands
The SIM7028 uses different AT commands than SIM7000/SIM7600 series
"""

import serial
import time
import sys

DEVICE = "/dev/cu.usbmodem101"
BAUD = 115200
TIMEOUT = 3

def send_at_command(ser, cmd, wait_time=2):
    """Send AT command and capture response"""
    print(f"\n>>> {cmd}")
    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())
    time.sleep(wait_time)

    response_lines = []
    while ser.in_waiting:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            response_lines.append(line)

    # Extract the actual response from debug output
    for line in response_lines:
        if "RX <<" in line:
            # Parse the actual response
            parts = line.split("RX <<")
            if len(parts) > 1:
                actual = parts[1].replace("[CRLF]", "").strip()
                print(f"<<< {actual}")
                return actual

    return " | ".join(response_lines)

def main():
    print("=" * 60)
    print("SIM7028 Band Configuration Diagnostics")
    print("=" * 60)

    try:
        ser = serial.Serial(DEVICE, BAUD, timeout=TIMEOUT)
        time.sleep(0.5)
        print(f"Connected to {DEVICE}")
    except Exception as e:
        print(f"ERROR: Could not open {DEVICE}: {e}")
        sys.exit(1)

    try:
        # Get module identification
        print("\n--- Module Identification ---")
        send_at_command(ser, "ATI")
        send_at_command(ser, "AT+CGMM")
        send_at_command(ser, "AT+CGMR")  # Firmware version

        # Check SIM status
        print("\n--- SIM Status ---")
        send_at_command(ser, "AT+CPIN?")
        send_at_command(ser, "AT+CCID")  # SIM ICCID

        # SIM7028-specific band commands to try
        print("\n--- Trying SIM7028 Band Commands ---")

        # Try CBAND (alternative syntax)
        send_at_command(ser, "AT+CBAND?")
        send_at_command(ser, "AT+CBAND=?")  # Test command to see supported values

        # Try NBIOT specific commands
        send_at_command(ser, "AT+CNBIOTBAND?")
        send_at_command(ser, "AT+CNBIOTBAND=?")

        # Check CNMP (network mode preference)
        send_at_command(ser, "AT+CNMP?")
        send_at_command(ser, "AT+CNMP=?")

        # Check CMNB (NB-IoT/Cat-M mode)
        send_at_command(ser, "AT+CMNB?")
        send_at_command(ser, "AT+CMNB=?")

        # Network operator scan (takes time but shows available networks)
        print("\n--- Network Status ---")
        send_at_command(ser, "AT+COPS?")
        send_at_command(ser, "AT+CEREG?")
        send_at_command(ser, "AT+CGATT?")  # GPRS attach status

        # APN configuration
        print("\n--- APN Configuration ---")
        send_at_command(ser, "AT+CGDCONT?")

        # Extended signal info
        print("\n--- Extended Signal Info ---")
        send_at_command(ser, "AT+CESQ")  # Extended signal quality
        send_at_command(ser, "AT+CENG?")  # Engineering mode

        # Try network scan (this takes 30-60 seconds)
        print("\n--- Would you like to run network scan? (AT+COPS=?) ---")
        print("Skipping - takes 30-60 seconds. Run manually if needed.")

    finally:
        ser.close()
        print("\n\nSerial port closed")

if __name__ == "__main__":
    main()
