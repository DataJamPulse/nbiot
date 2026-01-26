#!/usr/bin/env python3
"""
SIM7028 Wake-up Script
The modem may have entered PSM deep sleep - need to wake it
"""

import serial
import time
import sys

DEVICE = "/dev/cu.usbmodem101"
BAUD = 115200
TIMEOUT = 2

def main():
    print("=" * 60)
    print("SIM7028 Wake-up Procedure")
    print("=" * 60)

    try:
        ser = serial.Serial(
            DEVICE,
            BAUD,
            timeout=TIMEOUT,
            rtscts=False,
            dsrdtr=False
        )
        time.sleep(0.5)
        print(f"Connected to {DEVICE}")
    except Exception as e:
        print(f"ERROR: Could not open {DEVICE}: {e}")
        sys.exit(1)

    try:
        print("\n--- Attempting to wake modem ---")

        # Toggle DTR to wake from sleep
        print("1. Toggling DTR line...")
        ser.dtr = False
        time.sleep(0.5)
        ser.dtr = True
        time.sleep(0.5)

        # Toggle RTS
        print("2. Toggling RTS line...")
        ser.rts = False
        time.sleep(0.5)
        ser.rts = True
        time.sleep(0.5)

        # Send multiple AT commands with delays
        print("3. Sending wake-up AT commands...")

        for i in range(10):
            ser.reset_input_buffer()
            ser.write(b"AT\r\n")
            time.sleep(0.5)

            response = b""
            while ser.in_waiting:
                response += ser.read(ser.in_waiting)

            if response:
                decoded = response.decode('utf-8', errors='ignore')
                print(f"   Attempt {i+1}: {decoded.strip()}")
                if "OK" in decoded:
                    print("\n*** MODEM AWAKE! ***")
                    break
            else:
                print(f"   Attempt {i+1}: No response")

            # Try sending just carriage return to wake
            ser.write(b"\r\n")
            time.sleep(0.3)

        # Final verification
        print("\n--- Verification ---")
        ser.reset_input_buffer()
        ser.write(b"AT\r\n")
        time.sleep(1)

        response = b""
        while ser.in_waiting:
            response += ser.read(ser.in_waiting)

        if response:
            print(f"Response: {response.decode('utf-8', errors='ignore').strip()}")
        else:
            print("No response - modem may need power cycle")
            print("\nTROUBLESHOOTING:")
            print("1. Check USB connection")
            print("2. Power cycle the device")
            print("3. Check if PSM put modem in deep sleep")
            print("4. Verify UART pins on the M5Stack Atom")

    finally:
        ser.close()
        print("\nSerial port closed")

if __name__ == "__main__":
    main()
