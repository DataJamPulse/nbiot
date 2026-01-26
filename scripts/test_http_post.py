#!/usr/bin/env python3
"""
Test HTTP POST from SIM7028 NB-IoT modem to backend server.
Sends a reading payload to the /api/reading endpoint.
"""

import serial
import time
import sys

# Configuration
SERIAL_PORT = "/dev/cu.usbmodem2101"
BAUD_RATE = 115200
TIMEOUT = 10

# Backend configuration
SERVER_IP = "172.233.144.32"
SERVER_PORT = 5000
ENDPOINT = "/api/reading"
AUTH_TOKEN = "5kYnw7ICbn3XBL04OjuX91iuD3KzV-mmjbbdVP9P0T4"

# Test payload
PAYLOAD = '{"d":"NB000001","t":1706230000,"i":100,"u":50,"sig":-85}'


def send_at(ser, cmd, wait=2, expect="OK"):
    """Send AT command and wait for response."""
    print(f"\n>>> {cmd}")
    ser.write((cmd + "\r\n").encode())
    time.sleep(wait)
    response = ser.read(ser.in_waiting).decode(errors='ignore')
    print(f"<<< {response.strip()}")
    return response


def send_raw(ser, data, wait=2):
    """Send raw data without adding CRLF."""
    print(f"\n>>> [RAW DATA: {len(data)} bytes]")
    ser.write(data.encode())
    time.sleep(wait)
    response = ser.read(ser.in_waiting).decode(errors='ignore')
    print(f"<<< {response.strip()}")
    return response


def build_http_request():
    """Build the HTTP POST request."""
    http_request = (
        f"POST {ENDPOINT} HTTP/1.1\r\n"
        f"Host: {SERVER_IP}:{SERVER_PORT}\r\n"
        f"Authorization: Bearer {AUTH_TOKEN}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(PAYLOAD)}\r\n"
        f"\r\n"
        f"{PAYLOAD}"
    )
    return http_request


def main():
    print("=" * 60)
    print("SIM7028 HTTP POST Test")
    print("=" * 60)
    print(f"Server: {SERVER_IP}:{SERVER_PORT}{ENDPOINT}")
    print(f"Port: {SERIAL_PORT}")
    print("=" * 60)

    # Build HTTP request
    http_request = build_http_request()
    request_length = len(http_request)
    print(f"\nHTTP Request ({request_length} bytes):")
    print("-" * 40)
    print(http_request)
    print("-" * 40)

    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=TIMEOUT)
        print(f"\nOpened {SERIAL_PORT} at {BAUD_RATE} baud")
        time.sleep(1)

        # Clear any pending data
        ser.read(ser.in_waiting)

        # Step 1: Basic modem check
        print("\n" + "=" * 40)
        print("Step 1: Check modem")
        print("=" * 40)
        response = send_at(ser, "AT")
        if "OK" not in response:
            print("ERROR: Modem not responding")
            return

        # Step 2: Check registration
        print("\n" + "=" * 40)
        print("Step 2: Check registration")
        print("=" * 40)
        send_at(ser, "AT+CEREG?")
        send_at(ser, "AT+IPADDR")

        # Step 3: Ensure network is open
        print("\n" + "=" * 40)
        print("Step 3: Open network (if needed)")
        print("=" * 40)
        response = send_at(ser, "AT+IPADDR")
        if "ERROR" in response:
            print("Network not open, opening...")
            send_at(ser, "AT+NETOPEN", wait=5)
            time.sleep(3)
            send_at(ser, "AT+IPADDR")

        # Step 4: Close any existing connection
        print("\n" + "=" * 40)
        print("Step 4: Close existing connections")
        print("=" * 40)
        send_at(ser, "AT+CIPCLOSE=0", wait=2)

        # Step 5: Open TCP connection
        print("\n" + "=" * 40)
        print("Step 5: Open TCP connection")
        print("=" * 40)
        response = send_at(ser, f'AT+CIPOPEN=0,"TCP","{SERVER_IP}",{SERVER_PORT}', wait=10)

        if "ERROR" in response:
            print("ERROR: Failed to open TCP connection")
            print("Check if server is listening on port 5000")
            return

        # Wait for connection confirmation
        time.sleep(2)
        extra = ser.read(ser.in_waiting).decode(errors='ignore')
        if extra:
            print(f"<<< {extra.strip()}")

        # Step 6: Send data
        print("\n" + "=" * 40)
        print("Step 6: Send HTTP POST")
        print("=" * 40)
        response = send_at(ser, f"AT+CIPSEND=0,{request_length}", wait=2)

        if ">" in response or ">" in ser.read(ser.in_waiting).decode(errors='ignore'):
            # Send the HTTP request
            response = send_raw(ser, http_request, wait=5)
        else:
            print("ERROR: Did not receive > prompt")
            return

        # Step 7: Wait for and read response
        print("\n" + "=" * 40)
        print("Step 7: Read server response")
        print("=" * 40)
        time.sleep(3)

        # Check for incoming data notification
        incoming = ser.read(ser.in_waiting).decode(errors='ignore')
        if incoming:
            print(f"<<< {incoming.strip()}")

        # Try to read response data
        response = send_at(ser, "AT+CIPRXGET=2,0,500", wait=3)

        # Step 8: Close connection
        print("\n" + "=" * 40)
        print("Step 8: Close connection")
        print("=" * 40)
        send_at(ser, "AT+CIPCLOSE=0", wait=2)

        print("\n" + "=" * 60)
        print("Test complete!")
        print("=" * 60)

    except serial.SerialException as e:
        print(f"Serial error: {e}")
        print("Check if the device is connected and port is correct")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("Serial port closed")


if __name__ == "__main__":
    main()
