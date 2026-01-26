#!/usr/bin/env python3
"""
SIM7028 Direct Passthrough Test
The AtomS3 firmware is forwarding commands - need to work with that
"""

import serial
import time
import sys

DEVICE = "/dev/cu.usbmodem101"
BAUD = 115200
TIMEOUT = 5

def send_command(ser, cmd, wait_time=3):
    """Send command and wait for full response"""
    print(f"\n{'='*50}")
    print(f"COMMAND: {cmd}")
    print(f"{'='*50}")

    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())
    time.sleep(wait_time)

    lines = []
    while ser.in_waiting:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            lines.append(line)
            print(f"  {line}")

    return lines

def main():
    print("=" * 60)
    print("SIM7028 via AtomS3 Passthrough")
    print("=" * 60)

    try:
        ser = serial.Serial(DEVICE, BAUD, timeout=TIMEOUT)
        time.sleep(1)
        print(f"Connected to {DEVICE}")

        # Drain any startup messages
        time.sleep(2)
        while ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                print(f"[startup] {line}")

    except Exception as e:
        print(f"ERROR: Could not open {DEVICE}: {e}")
        sys.exit(1)

    try:
        # The AtomS3 firmware is a passthrough - send AT commands
        print("\n--- Sending AT commands through AtomS3 passthrough ---")

        # Basic AT test - multiple attempts
        for i in range(5):
            resp = send_command(ser, "AT", wait_time=2)
            if any("OK" in r for r in resp):
                print("\n*** Modem responding! ***")
                break
            time.sleep(1)

        # Check SIM status
        send_command(ser, "AT+CPIN?", wait_time=2)

        # Check modem info
        send_command(ser, "ATI", wait_time=2)

        # Check CEREG
        send_command(ser, "AT+CEREG?", wait_time=2)

        # Check signal
        send_command(ser, "AT+CSQ", wait_time=2)

        # Check APN
        send_command(ser, "AT+CGDCONT?", wait_time=2)

        # Check operator
        send_command(ser, "AT+COPS?", wait_time=2)

        # Try the band configuration that the firmware may support
        print("\n--- Attempting band configuration ---")
        send_command(ser, "AT+CBANDCFG?", wait_time=2)

        # Check PSM status
        send_command(ser, "AT+CPSMS?", wait_time=2)

        # Keep monitoring for 30 seconds
        print("\n" + "=" * 60)
        print("MONITORING FOR 30 SECONDS...")
        print("=" * 60)

        start_time = time.time()
        while time.time() - start_time < 30:
            while ser.in_waiting:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(f"[{int(time.time()-start_time):2d}s] {line}")
            time.sleep(0.5)

    finally:
        ser.close()
        print("\nSerial port closed")

if __name__ == "__main__":
    main()
