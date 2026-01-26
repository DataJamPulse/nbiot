#!/usr/bin/env python3
"""
SIM7028 Band Configuration - Using correct SIM7028 AT commands
Based on SIM7028 AT Command Manual
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

    raw_response = ""
    while ser.in_waiting:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            raw_response += line + " | "

    # Extract the actual response
    result = "OK" if "OK" in raw_response else ("ERROR" if "ERROR" in raw_response else raw_response)

    # Try to extract meaningful data
    if "RX <<" in raw_response:
        parts = raw_response.split("RX <<")
        if len(parts) > 1:
            actual = parts[1].replace("[CRLF]", " ").strip()
            if actual:
                result = actual

    print(f"<<< {result}")
    return raw_response

def main():
    print("=" * 60)
    print("SIM7028 Band Configuration (SIM7028-specific commands)")
    print("=" * 60)

    try:
        ser = serial.Serial(DEVICE, BAUD, timeout=TIMEOUT)
        time.sleep(0.5)
        print(f"Connected to {DEVICE}")
    except Exception as e:
        print(f"ERROR: Could not open {DEVICE}: {e}")
        sys.exit(1)

    try:
        # SIM7028 specific band commands
        print("\n--- SIM7028 Specific Band Commands ---")

        # CNSMOD - Network system mode
        send_at_command(ser, "AT+CNSMOD?")
        send_at_command(ser, "AT+CNSMOD=?")

        # CBANDMODE - Band mode configuration (SIM7028 specific)
        send_at_command(ser, "AT+CBANDMODE?")
        send_at_command(ser, "AT+CBANDMODE=?")

        # CBAND - Might work with different syntax
        send_at_command(ser, "AT+CBAND?")

        # NBSC - NB-IoT system config
        send_at_command(ser, "AT+NBSC?")
        send_at_command(ser, "AT+NBSC=?")

        # NCONFIG - NB-IoT configuration
        send_at_command(ser, "AT+NCONFIG?")

        # NBAND - NB-IoT band (common on NB-IoT modules)
        send_at_command(ser, "AT+NBAND?")
        send_at_command(ser, "AT+NBAND=?")

        # Query supported frequency bands via engineering command
        send_at_command(ser, "AT+CFREQSCAN?")
        send_at_command(ser, "AT*CNBPREFBAND?")

        # Try listing all AT commands
        print("\n--- Checking Available Commands ---")
        send_at_command(ser, "AT+CLAC", wait_time=5)  # List all AT commands

        # Current network attachment status
        print("\n--- Current Network Status ---")
        send_at_command(ser, "AT+CEREG=2")  # Enable location info in CEREG
        send_at_command(ser, "AT+CEREG?")
        send_at_command(ser, "AT+CSQ")

        # Check if module is in airplane mode or wrong mode
        send_at_command(ser, "AT+CFUN?")

        # Try forcing manual network selection
        print("\n--- Network Operator Info ---")
        send_at_command(ser, "AT+COPS?")

        # Check PSM (Power Saving Mode) - might be blocking connection
        send_at_command(ser, "AT+CPSMS?")

        # Check eDRX settings
        send_at_command(ser, "AT+CEDRXS?")

        print("\n--- Running Full Network Scan (30-60 seconds) ---")
        print("This will scan for all available networks...")
        resp = send_at_command(ser, "AT+COPS=?", wait_time=45)
        print(f"Full response: {resp[:500] if len(resp) > 500 else resp}")

    finally:
        ser.close()
        print("\n\nSerial port closed")

if __name__ == "__main__":
    main()
