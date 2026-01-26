#!/usr/bin/env python3
"""
NB-IoT Band Configuration Script for SIM7028
Query and set NB-IoT bands for US T-Mobile via Hologram
"""

import serial
import time
import sys

SERIAL_PORT = "/dev/cu.usbmodem101"
BAUD_RATE = 115200
TIMEOUT = 2

def send_at_command(ser, cmd, wait_time=2):
    """Send AT command and capture response"""
    ser.reset_input_buffer()
    full_cmd = cmd + "\r\n"
    ser.write(full_cmd.encode())
    print(f"\n>>> {cmd}")

    time.sleep(wait_time)

    response = ""
    while ser.in_waiting:
        response += ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        time.sleep(0.1)

    # Parse out the RX << response
    for line in response.split('\n'):
        line = line.strip()
        if line and ('RX <<' in line or '+' in line or 'OK' in line or 'ERROR' in line):
            print(f"    {line}")

    return response

def main():
    print("=" * 60)
    print("SIM7028 NB-IoT Band Configuration")
    print("=" * 60)
    print("\nUS NB-IoT Bands via Hologram/T-Mobile:")
    print("  - Band 12 (700 MHz) - Primary")
    print("  - Band 71 (600 MHz) - Secondary")
    print("  - Band 2 (1900 MHz) - AT&T fallback")
    print("  - Band 4 (1700 MHz) - Verizon regions")
    print("=" * 60)

    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=TIMEOUT)
        print(f"Connected to {SERIAL_PORT}")
        time.sleep(0.5)
        ser.reset_input_buffer()

        # Basic check
        send_at_command(ser, "AT", wait_time=1)

        print("\n--- Querying Current Band Settings ---")

        # SIM7028 specific band commands (try multiple variants)
        band_queries = [
            "AT+CBANDCFG?",      # Standard SIMCOM
            "AT+CNBP?",          # NB-IoT band preference
            "AT+NBAND?",         # Alternative band query
            "AT+QBAND?",         # Quectel style
            "AT+NBSC?",          # NB-IoT scan config
            "AT*MCGDEFCONT?",    # Default context
        ]

        for cmd in band_queries:
            send_at_command(ser, cmd, wait_time=1)

        print("\n--- Checking Supported Commands ---")
        # Check what commands are available
        send_at_command(ser, 'AT+CLAC', wait_time=3)

        print("\n--- Querying RF Configuration ---")
        # Try to get RF/band info via engineering commands
        rf_queries = [
            "AT+CENG?",          # Engineering mode
            "AT+NUESTATS",       # UE stats
            "AT+NUESTATS=CELL",  # Cell info
            "AT+NCONFIG?",       # NB-IoT config
        ]

        for cmd in rf_queries:
            send_at_command(ser, cmd, wait_time=1)

        print("\n--- Checking Operator Lock ---")
        send_at_command(ser, "AT+COPS?", wait_time=1)
        send_at_command(ser, "AT+COPN", wait_time=2)  # Operator names

        print("\n--- Checking Frequency Lock ---")
        freq_cmds = [
            "AT+NCSEARFCN",      # Search ARFCN
            "AT+CFREQSCAN?",     # Freq scan setting
        ]
        for cmd in freq_cmds:
            send_at_command(ser, cmd, wait_time=1)

        ser.close()

    except serial.SerialException as e:
        print(f"Serial error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
