#!/usr/bin/env python3
"""
SIM7028 Configuration Script
Clean command interface with proper response parsing
"""

import serial
import time
import sys
import re

SERIAL_PORT = "/dev/cu.usbmodem101"
BAUD_RATE = 115200
TIMEOUT = 5

def send_command(ser, cmd, wait_time=2):
    """Send AT command and extract modem response from RX << lines"""
    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())

    time.sleep(wait_time)

    raw_response = ""
    while ser.in_waiting:
        raw_response += ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
        time.sleep(0.05)

    # Extract actual modem responses (after "RX <<")
    modem_responses = []
    for line in raw_response.split('\n'):
        if 'RX <<' in line:
            # Extract content after RX <<
            match = re.search(r'RX <<\s*(.+)', line)
            if match:
                resp = match.group(1).strip()
                # Clean up [CRLF] markers
                resp = resp.replace('[CRLF]', '\n').strip()
                if resp and resp != '(no response - timeout)':
                    modem_responses.append(resp)

    return modem_responses

def run_command(ser, cmd, description, wait_time=2):
    """Run command and display result"""
    print(f"\n{description}")
    print(f"  Command: {cmd}")
    responses = send_command(ser, cmd, wait_time)
    if responses:
        for resp in responses:
            for line in resp.split('\n'):
                if line.strip():
                    print(f"  Response: {line.strip()}")
    else:
        print("  Response: (no response/timeout)")
    return responses

def main():
    print("=" * 70)
    print("SIM7028 NB-IoT Configuration Utility")
    print("=" * 70)

    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=TIMEOUT)
        print(f"Connected to {SERIAL_PORT}")
        time.sleep(1)
        ser.reset_input_buffer()

        # Verify connection
        run_command(ser, "AT", "Basic AT Test")

        # Get modem info
        run_command(ser, "ATI", "Modem Information")

        print("\n" + "-" * 70)
        print("CURRENT NETWORK STATUS")
        print("-" * 70)

        run_command(ser, "AT+CPIN?", "SIM Status")
        run_command(ser, "AT+CEREG?", "Network Registration")
        run_command(ser, "AT+CSQ", "Signal Quality (99,99 = no signal)")
        run_command(ser, "AT+COPS?", "Current Operator")
        run_command(ser, "AT+CGDCONT?", "APN Configuration")

        print("\n" + "-" * 70)
        print("BAND CONFIGURATION QUERIES")
        print("-" * 70)

        # SIM7028 uses AT+CBAND for band configuration
        # Format varies by firmware version
        run_command(ser, "AT+CBAND?", "Band Query (Standard)")

        # Try SIMCOM specific NB-IoT band commands
        run_command(ser, "AT+CBANDCFG=\"NB-IOT\"", "NB-IoT Band Config Query")

        # Frequency scan range
        run_command(ser, "AT+CNACT?", "Network Activation Status")

        # Get supported bands from capability
        run_command(ser, "AT+CGMM", "Model (for band capability lookup)")

        print("\n" + "-" * 70)
        print("CONFIGURING FOR US NB-IoT (T-Mobile via Hologram)")
        print("-" * 70)
        print("Target bands: 12 (700MHz), 71 (600MHz), 2 (1900MHz), 4 (1700MHz)")

        # Set minimum functionality first
        run_command(ser, "AT+CFUN=0", "Set Minimum Functionality (for config)")

        time.sleep(2)

        # Try different band configuration syntaxes for SIM7028
        print("\nAttempting band configuration...")

        # SIM7028 band config - try common formats
        band_cmds = [
            ('AT+CBAND="NB-IOT",12,71,2,4', "CBAND NB-IOT with bands"),
            ('AT+CBANDCFG="NB-IOT",12,71,2,4', "CBANDCFG with bands"),
            ('AT+CNBP=0,0,0,0x0000000000000002,0x0000000000001002', "CNBP bit mask (bands 2,12)"),
        ]

        for cmd, desc in band_cmds:
            run_command(ser, cmd, desc, wait_time=2)

        # Set full functionality
        run_command(ser, "AT+CFUN=1", "Restore Full Functionality", wait_time=3)

        # Force automatic operator selection
        run_command(ser, "AT+COPS=0", "Automatic Operator Selection", wait_time=2)

        print("\n" + "-" * 70)
        print("FORCING NETWORK REGISTRATION")
        print("-" * 70)

        # Enable registration URCs
        run_command(ser, "AT+CEREG=2", "Enable Registration URCs")

        # Force network deregister/reregister
        run_command(ser, "AT+COPS=2", "Deregister from Network", wait_time=2)
        time.sleep(2)
        run_command(ser, "AT+COPS=0", "Re-enable Auto Registration", wait_time=2)

        print("\n" + "-" * 70)
        print("NETWORK SCAN (This may take 60+ seconds)")
        print("-" * 70)

        # Network scan
        responses = run_command(ser, "AT+COPS=?", "Available Networks", wait_time=60)

        print("\n" + "-" * 70)
        print("POST-CONFIGURATION STATUS")
        print("-" * 70)

        run_command(ser, "AT+CEREG?", "Network Registration")
        run_command(ser, "AT+CSQ", "Signal Quality")
        run_command(ser, "AT+COPS?", "Current Operator")

        ser.close()
        print("\n" + "=" * 70)
        print("Configuration Complete")
        print("=" * 70)

    except serial.SerialException as e:
        print(f"Serial error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted")
        if 'ser' in locals():
            ser.close()

if __name__ == "__main__":
    main()
