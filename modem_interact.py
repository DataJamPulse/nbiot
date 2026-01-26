#!/usr/bin/env python3
"""
Interactive AT Command Script for M5Stack AtomS3 DTU NB-IoT
Sends commands and shows raw output for debugging
"""

import serial
import time
import sys

SERIAL_PORT = "/dev/cu.usbmodem101"
BAUD_RATE = 115200

def send_and_read(ser, cmd, wait_secs=3):
    """Send command and read all output"""
    print(f"\n{'='*60}")
    print(f"COMMAND: {cmd}")
    print('='*60)

    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())

    time.sleep(wait_secs)

    output = ""
    while ser.in_waiting:
        output += ser.read(ser.in_waiting).decode('utf-8', errors='replace')
        time.sleep(0.1)

    print(output if output else "(no output)")
    print()
    return output

def main():
    print("M5Stack AtomS3 DTU NB-IoT - AT Command Interface")
    print("-" * 60)

    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=5)
        print(f"Opened {SERIAL_PORT} at {BAUD_RATE} baud")
        time.sleep(1)

        # === DIAGNOSTIC COMMANDS ===

        # Basic test
        send_and_read(ser, "AT", wait_secs=2)

        # Modem info
        send_and_read(ser, "ATI", wait_secs=2)

        # SIM status
        send_and_read(ser, "AT+CPIN?", wait_secs=2)

        # Network registration
        send_and_read(ser, "AT+CEREG?", wait_secs=2)

        # Signal quality
        send_and_read(ser, "AT+CSQ", wait_secs=2)

        # APN
        send_and_read(ser, "AT+CGDCONT?", wait_secs=2)

        # Current operator
        send_and_read(ser, "AT+COPS?", wait_secs=2)

        # === BAND CONFIGURATION ===
        print("\n" + "#"*60)
        print("# BAND CONFIGURATION SECTION")
        print("#"*60)

        # Query current bands - try multiple commands
        send_and_read(ser, "AT+CBAND?", wait_secs=2)
        send_and_read(ser, "AT+CNBP?", wait_secs=2)

        # List all available AT commands (if supported)
        # send_and_read(ser, "AT+CLAC", wait_secs=5)

        # === CONFIGURE FOR US ===
        print("\n" + "#"*60)
        print("# CONFIGURING FOR US NB-IoT")
        print("#"*60)

        # Set to minimum functionality for configuration
        send_and_read(ser, "AT+CFUN=0", wait_secs=3)

        # Try to set NB-IoT bands (different syntaxes for SIM7028)
        # Band 12 = 700MHz (T-Mobile primary)
        # Band 71 = 600MHz (T-Mobile secondary)
        # Band 2 = 1900MHz (AT&T)
        # Band 4 = 1700MHz (Verizon)

        # Try SIMCOM SIM7028 band config syntax
        send_and_read(ser, 'AT+CBAND="NB-IOT",2,4,12,71', wait_secs=2)

        # Alternative: set all bands
        send_and_read(ser, 'AT+CBAND="ALL_MODE"', wait_secs=2)

        # Restore full functionality
        send_and_read(ser, "AT+CFUN=1", wait_secs=5)

        # === FORCE REGISTRATION ===
        print("\n" + "#"*60)
        print("# FORCING NETWORK REGISTRATION")
        print("#"*60)

        # Enable extended registration info
        send_and_read(ser, "AT+CEREG=2", wait_secs=2)

        # Deregister
        send_and_read(ser, "AT+COPS=2", wait_secs=3)

        # Re-enable automatic registration
        send_and_read(ser, "AT+COPS=0", wait_secs=3)

        # === NETWORK SCAN ===
        print("\n" + "#"*60)
        print("# NETWORK SCAN (60+ seconds)")
        print("#"*60)

        send_and_read(ser, "AT+COPS=?", wait_secs=90)

        # === FINAL STATUS ===
        print("\n" + "#"*60)
        print("# FINAL STATUS CHECK")
        print("#"*60)

        send_and_read(ser, "AT+CEREG?", wait_secs=2)
        send_and_read(ser, "AT+CSQ", wait_secs=2)
        send_and_read(ser, "AT+COPS?", wait_secs=2)

        ser.close()
        print("\nDone.")

    except serial.SerialException as e:
        print(f"Serial error: {e}")
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
