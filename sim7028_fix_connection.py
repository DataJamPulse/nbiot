#!/usr/bin/env python3
"""
SIM7028 Connection Fix Script
Based on diagnostic findings - PSM may be blocking initial connection
"""

import serial
import time
import sys

DEVICE = "/dev/cu.usbmodem101"
BAUD = 115200
TIMEOUT = 3

def send_at_command(ser, cmd, wait_time=2, show_raw=False):
    """Send AT command and capture response"""
    print(f"\n>>> {cmd}")
    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())
    time.sleep(wait_time)

    raw_lines = []
    while ser.in_waiting:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            raw_lines.append(line)

    # Parse response
    result = "NO RESPONSE"
    for line in raw_lines:
        if "RX <<" in line:
            actual = line.split("RX <<")[1].replace("[CRLF]", " ").strip()
            if actual:
                result = actual
                break

    print(f"<<< {result}")
    if show_raw and raw_lines:
        print(f"    (raw: {raw_lines})")

    return result

def main():
    print("=" * 60)
    print("SIM7028 Connection Fix Procedure")
    print("=" * 60)

    try:
        ser = serial.Serial(DEVICE, BAUD, timeout=TIMEOUT)
        time.sleep(0.5)
        print(f"Connected to {DEVICE}")
    except Exception as e:
        print(f"ERROR: Could not open {DEVICE}: {e}")
        sys.exit(1)

    try:
        # Step 1: Check current state
        print("\n" + "=" * 40)
        print("STEP 1: Current State")
        print("=" * 40)

        send_at_command(ser, "AT")
        send_at_command(ser, "AT+CPIN?")
        send_at_command(ser, "AT+CFUN?")
        send_at_command(ser, "AT+CEREG?")
        send_at_command(ser, "AT+CSQ")

        # Step 2: Disable PSM (Power Saving Mode)
        # PSM can prevent network attachment during initial setup
        print("\n" + "=" * 40)
        print("STEP 2: Disable Power Saving Mode (PSM)")
        print("=" * 40)
        print("PSM was enabled with T3324/T3412 timers - disabling for initial attach")

        send_at_command(ser, "AT+CPSMS=0")  # Disable PSM

        # Step 3: Disable eDRX (extended Discontinuous Reception)
        print("\n" + "=" * 40)
        print("STEP 3: Disable eDRX")
        print("=" * 40)

        send_at_command(ser, "AT+CEDRXS=0,5")  # Disable eDRX for NB-IoT

        # Step 4: Verify APN is set correctly
        print("\n" + "=" * 40)
        print("STEP 4: Verify APN Configuration")
        print("=" * 40)

        send_at_command(ser, "AT+CGDCONT?")
        # Re-set APN to ensure it's correct
        send_at_command(ser, 'AT+CGDCONT=1,"IP","hologram"')

        # Step 5: Set automatic operator selection
        print("\n" + "=" * 40)
        print("STEP 5: Set Automatic Operator Selection")
        print("=" * 40)

        send_at_command(ser, "AT+COPS=0")  # Automatic

        # Step 6: Restart radio to apply changes
        print("\n" + "=" * 40)
        print("STEP 6: Radio Restart")
        print("=" * 40)

        send_at_command(ser, "AT+CFUN=0", wait_time=2)
        print("    Waiting 3 seconds...")
        time.sleep(3)
        send_at_command(ser, "AT+CFUN=1", wait_time=3)

        # Step 7: Monitor registration progress
        print("\n" + "=" * 40)
        print("STEP 7: Monitor Registration (30 seconds)")
        print("=" * 40)
        print("NB-IoT registration can take 30-60 seconds...")

        for i in range(6):
            time.sleep(5)
            print(f"\n--- Check {i+1}/6 (at {(i+1)*5}s) ---")
            cereg = send_at_command(ser, "AT+CEREG?")
            csq = send_at_command(ser, "AT+CSQ")

            # Parse CEREG status
            if "+CEREG:" in cereg:
                parts = cereg.split(",")
                if len(parts) >= 2:
                    stat = parts[1].strip().split()[0] if parts[1].strip() else "?"
                    status_map = {
                        "0": "NOT REGISTERED, not searching",
                        "1": "REGISTERED (home) - SUCCESS!",
                        "2": "Searching...",
                        "3": "REGISTRATION DENIED",
                        "4": "Unknown",
                        "5": "REGISTERED (roaming) - SUCCESS!"
                    }
                    status = status_map.get(stat, f"Unknown ({stat})")
                    print(f"    Status: {status}")

                    if stat in ["1", "5"]:
                        print("\n*** NETWORK REGISTRATION SUCCESSFUL! ***")
                        break

            # Parse CSQ
            if "+CSQ:" in csq:
                vals = csq.split(":")[1].strip().split(",")
                if len(vals) >= 1:
                    rssi = vals[0].strip().split()[0]
                    if rssi == "99":
                        print("    Signal: No signal detected")
                    else:
                        try:
                            rssi_dbm = -113 + (int(rssi) * 2)
                            print(f"    Signal: RSSI {rssi} ({rssi_dbm} dBm)")
                        except:
                            pass

        # Final status
        print("\n" + "=" * 60)
        print("FINAL STATUS")
        print("=" * 60)
        send_at_command(ser, "AT+CEREG?")
        send_at_command(ser, "AT+CSQ")
        send_at_command(ser, "AT+CGATT?")  # GPRS attach status
        send_at_command(ser, "AT+CPSMS?")  # Verify PSM is off
        send_at_command(ser, "AT+COPS?")

    finally:
        ser.close()
        print("\n\nSerial port closed")

if __name__ == "__main__":
    main()
