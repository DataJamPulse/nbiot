#!/usr/bin/env python3
"""
NB-IoT Band Configuration Script for SIM7028
Configures US NB-IoT bands for T-Mobile/AT&T coverage
"""

import serial
import time
import sys

DEVICE = "/dev/cu.usbmodem101"
BAUD = 115200
TIMEOUT = 3

def send_at_command(ser, cmd, wait_time=2):
    """Send AT command and capture response"""
    print(f"\n>>> Sending: {cmd}")
    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())
    time.sleep(wait_time)

    response_lines = []
    while ser.in_waiting:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            response_lines.append(line)

    # Filter for actual modem responses (skip echo)
    meaningful_responses = []
    for line in response_lines:
        if line == cmd:
            continue  # Skip echo
        if any(x in line for x in ['+', 'OK', 'ERROR', 'READY']):
            meaningful_responses.append(line)

    print(f"<<< Response: {meaningful_responses}")
    return meaningful_responses

def main():
    print("=" * 60)
    print("SIM7028 NB-IoT Band Configuration")
    print(f"Device: {DEVICE} @ {BAUD} baud")
    print("=" * 60)

    try:
        ser = serial.Serial(DEVICE, BAUD, timeout=TIMEOUT)
        time.sleep(0.5)
        print(f"\nConnected to {DEVICE}")
    except Exception as e:
        print(f"ERROR: Could not open {DEVICE}: {e}")
        sys.exit(1)

    try:
        # Step 1: Basic AT test
        print("\n--- Step 1: Basic AT Test ---")
        resp = send_at_command(ser, "AT")
        if "OK" not in resp:
            print("WARNING: Modem not responding to AT command")

        # Step 2: Check current band configuration
        print("\n--- Step 2: Check Current Band Config ---")
        resp = send_at_command(ser, "AT+CBANDCFG?")
        current_bands = [r for r in resp if "+CBANDCFG" in r]
        if current_bands:
            print(f"Current bands: {current_bands}")

        # Step 3: Check available/supported bands
        print("\n--- Step 3: Check Available Bands ---")
        resp = send_at_command(ser, "AT+CNBS?")
        available_bands = [r for r in resp if "+CNBS" in r]
        if available_bands:
            print(f"Available bands: {available_bands}")

        # Step 4: Check current registration before changes
        print("\n--- Step 4: Current Registration Status ---")
        resp = send_at_command(ser, "AT+CEREG?")
        pre_cereg = [r for r in resp if "+CEREG" in r]
        print(f"Pre-config CEREG: {pre_cereg}")

        # Step 5: Configure US NB-IoT bands
        # Band 2: 1900 MHz (T-Mobile PCS)
        # Band 4: 1700/2100 MHz (AWS)
        # Band 12: 700 MHz (T-Mobile primary NB-IoT)
        # Band 13: 700 MHz (Verizon LTE, some NB-IoT)
        print("\n--- Step 5: Configure US NB-IoT Bands (2,4,12,13) ---")
        resp = send_at_command(ser, 'AT+CBANDCFG="NB-IOT",2,4,12,13')
        if "OK" in resp:
            print("Band configuration accepted")
        elif "ERROR" in str(resp):
            print("WARNING: Band config returned error")

        # Step 6: Verify new band configuration
        print("\n--- Step 6: Verify New Band Config ---")
        resp = send_at_command(ser, "AT+CBANDCFG?")
        new_bands = [r for r in resp if "+CBANDCFG" in r]
        print(f"New bands configured: {new_bands}")

        # Step 7: Restart radio (CFUN cycle)
        print("\n--- Step 7: Restart Radio (CFUN=0) ---")
        resp = send_at_command(ser, "AT+CFUN=0", wait_time=2)
        if "OK" in resp:
            print("Radio disabled")

        print("\n--- Step 8: Enable Radio (CFUN=1) ---")
        resp = send_at_command(ser, "AT+CFUN=1", wait_time=3)
        if "OK" in resp:
            print("Radio enabled - waiting for network search...")

        # Step 9: Wait and check registration
        print("\n--- Step 9: Check Registration Status (waiting 5s) ---")
        time.sleep(5)
        resp = send_at_command(ser, "AT+CEREG?")
        post_cereg = [r for r in resp if "+CEREG" in r]
        print(f"Post-config CEREG: {post_cereg}")

        # Decode CEREG status
        if post_cereg:
            # Parse +CEREG: n,stat format
            cereg_str = post_cereg[0]
            if "," in cereg_str:
                parts = cereg_str.split(",")
                if len(parts) >= 2:
                    stat = parts[1].split(",")[0].strip()
                    status_map = {
                        "0": "Not registered, not searching",
                        "1": "Registered, home network",
                        "2": "Not registered, searching",
                        "3": "Registration DENIED",
                        "4": "Unknown",
                        "5": "Registered, roaming"
                    }
                    print(f"Registration status: {status_map.get(stat, f'Unknown ({stat})')}")

        # Step 10: Check signal strength
        print("\n--- Step 10: Check Signal Strength ---")
        resp = send_at_command(ser, "AT+CSQ")
        csq = [r for r in resp if "+CSQ" in r]
        if csq:
            print(f"Signal: {csq}")
            # Parse CSQ value
            csq_str = csq[0]
            if ":" in csq_str:
                vals = csq_str.split(":")[1].strip().split(",")
                if len(vals) >= 1:
                    rssi = vals[0].strip()
                    if rssi == "99":
                        print("RSSI: Not detectable (no signal)")
                    else:
                        rssi_dbm = -113 + (int(rssi) * 2)
                        print(f"RSSI: {rssi} ({rssi_dbm} dBm)")

        # Summary
        print("\n" + "=" * 60)
        print("CONFIGURATION SUMMARY")
        print("=" * 60)
        print(f"Bands configured: 2, 4, 12, 13 (US NB-IoT)")
        print(f"Pre-config registration: {pre_cereg}")
        print(f"Post-config registration: {post_cereg}")
        print(f"Signal: {csq}")
        print("\nNote: Full registration may take 30-60 seconds for NB-IoT")
        print("Re-run AT+CEREG? in a minute if still searching (status 2)")

    finally:
        ser.close()
        print("\nSerial port closed")

if __name__ == "__main__":
    main()
