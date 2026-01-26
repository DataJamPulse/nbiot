#!/usr/bin/env python3
"""
NB-IoT Modem Diagnostic Script for SIM7028
Checks band configuration, signal, and network status
"""

import serial
import time
import sys

SERIAL_PORT = "/dev/cu.usbmodem101"
BAUD_RATE = 115200
TIMEOUT = 2

def send_at_command(ser, cmd, wait_time=1, expect_lines=5):
    """Send AT command and capture response from firmware echo"""
    # Clear any pending data
    ser.reset_input_buffer()

    # Send command
    full_cmd = cmd + "\r\n"
    ser.write(full_cmd.encode())
    print(f"\n>>> Sending: {cmd}")

    # Wait for response
    time.sleep(wait_time)

    # Read all available data
    response_lines = []
    start_time = time.time()
    while time.time() - start_time < wait_time + 1:
        if ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                response_lines.append(line)
                print(f"    {line}")
        else:
            time.sleep(0.1)

    return response_lines

def main():
    print("=" * 60)
    print("SIM7028 NB-IoT Modem Diagnostic")
    print("=" * 60)

    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=TIMEOUT)
        print(f"Connected to {SERIAL_PORT} at {BAUD_RATE} baud")
        time.sleep(0.5)

        # Clear buffer
        ser.reset_input_buffer()

        print("\n" + "=" * 60)
        print("STEP 1: Basic Modem Check")
        print("=" * 60)

        # Basic AT test
        send_at_command(ser, "AT", wait_time=1)

        # Modem identification
        send_at_command(ser, "ATI", wait_time=1)

        # Firmware version
        send_at_command(ser, "AT+CGMR", wait_time=1)

        print("\n" + "=" * 60)
        print("STEP 2: SIM and Network Status")
        print("=" * 60)

        # SIM status
        send_at_command(ser, "AT+CPIN?", wait_time=1)

        # IMSI (subscriber ID)
        send_at_command(ser, "AT+CIMI", wait_time=1)

        # Network registration status
        send_at_command(ser, "AT+CEREG?", wait_time=1)

        # Current operator
        send_at_command(ser, "AT+COPS?", wait_time=1)

        print("\n" + "=" * 60)
        print("STEP 3: Signal Quality")
        print("=" * 60)

        # Signal quality
        send_at_command(ser, "AT+CSQ", wait_time=1)

        # Extended signal quality (if supported)
        send_at_command(ser, "AT+CESQ", wait_time=1)

        print("\n" + "=" * 60)
        print("STEP 4: Current Band Configuration")
        print("=" * 60)

        # Check current band config (SIM7028 specific)
        send_at_command(ser, "AT+CBANDCFG?", wait_time=1)

        # Alternative band query
        send_at_command(ser, "AT+CBAND?", wait_time=1)

        # NB-IoT band scan setting
        send_at_command(ser, "AT+CNBS?", wait_time=1)

        print("\n" + "=" * 60)
        print("STEP 5: APN Configuration")
        print("=" * 60)

        # Check PDP context (APN)
        send_at_command(ser, "AT+CGDCONT?", wait_time=1)

        # Check network mode
        send_at_command(ser, "AT+CMNB?", wait_time=1)

        print("\n" + "=" * 60)
        print("STEP 6: Network Scan (may take 30-60 seconds)")
        print("=" * 60)

        # Force network scan - this can take a while
        print("Starting network scan... please wait...")
        send_at_command(ser, "AT+COPS=?", wait_time=45)

        ser.close()
        print("\n" + "=" * 60)
        print("Diagnostic Complete")
        print("=" * 60)

    except serial.SerialException as e:
        print(f"Serial error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        if 'ser' in locals():
            ser.close()
        sys.exit(0)

if __name__ == "__main__":
    main()
