#!/bin/bash
#
# NBJBTOOL.sh - NB-IoT JamBox Device Provisioning Tool
#
# Production tool for flashing and configuring NB-IoT JamBox devices.
#
# Usage:
#   ./NBJBTOOL.sh           - Interactive menu
#   ./NBJBTOOL.sh --help    - Show help
#
# Requirements:
#   - PlatformIO CLI installed (~/.platformio/penv/bin/pio)
#   - curl for API calls
#   - jq for JSON parsing (optional, falls back to grep)
#
# Author: Data Jam
# Version: 1.0.0
# Date: 2026-01-25
#

set -e

# =============================================================================
# Configuration
# =============================================================================

# Script version
TOOL_VERSION="2.0.0"

# Get script directory (works even if called from different location)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Backend configuration
BACKEND_URL="http://172.233.144.32:5000"
ADMIN_KEY="djnb-admin-2026-change-me"

# Device configuration
DEVICE_PREFIX="JBNB"
DEVICE_CONFIG_FILE="$PROJECT_DIR/src/device_config.h"

# PlatformIO path
PIO_CMD="${HOME}/.platformio/penv/bin/pio"

# Labels directory
LABELS_DIR="$PROJECT_DIR/labels"

# Activation portal base URL
ACTIVATION_URL_BASE="https://datajamreports.com/activate"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# =============================================================================
# Utility Functions
# =============================================================================

print_header() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  NB-IoT JamBox Provisioning Tool v${TOOL_VERSION}${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_step() {
    echo -e "${BOLD}>>> $1${NC}"
}

# Check if command exists
check_command() {
    if ! command -v "$1" &> /dev/null; then
        return 1
    fi
    return 0
}

# Check prerequisites
check_prerequisites() {
    local missing=0

    print_step "Checking prerequisites..."

    # Check PlatformIO
    if [[ -x "$PIO_CMD" ]]; then
        print_success "PlatformIO found"
    else
        print_error "PlatformIO not found at $PIO_CMD"
        echo "       Install with: curl -fsSL https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py -o get-platformio.py && python3 get-platformio.py"
        missing=1
    fi

    # Check curl
    if check_command curl; then
        print_success "curl found"
    else
        print_error "curl not found (required for API calls)"
        missing=1
    fi

    # Check jq (optional)
    if check_command jq; then
        print_success "jq found"
    else
        print_warning "jq not found (optional, using grep fallback)"
    fi

    # Check project structure
    if [[ -f "$PROJECT_DIR/platformio.ini" ]]; then
        print_success "Project directory valid"
    else
        print_error "platformio.ini not found - are you in the right directory?"
        missing=1
    fi

    if [[ $missing -eq 1 ]]; then
        echo ""
        print_error "Prerequisites check failed"
        return 1
    fi

    print_success "All prerequisites satisfied"
    return 0
}

# =============================================================================
# Serial Port Detection
# =============================================================================

# Find available serial ports
find_serial_ports() {
    local ports=()

    # Look for USB modem devices (macOS pattern)
    while IFS= read -r port; do
        if [[ -n "$port" ]]; then
            ports+=("$port")
        fi
    done < <(ls /dev/cu.usbmodem* 2>/dev/null || true)

    # Also check for tty devices (Linux pattern)
    while IFS= read -r port; do
        if [[ -n "$port" ]]; then
            ports+=("$port")
        fi
    done < <(ls /dev/ttyUSB* 2>/dev/null || true)

    while IFS= read -r port; do
        if [[ -n "$port" ]]; then
            ports+=("$port")
        fi
    done < <(ls /dev/ttyACM* 2>/dev/null || true)

    echo "${ports[@]}"
}

# Select serial port interactively
select_serial_port() {
    local ports
    ports=($(find_serial_ports))

    if [[ ${#ports[@]} -eq 0 ]]; then
        print_error "No serial devices found"
        echo "       Please connect your device and try again"
        return 1
    elif [[ ${#ports[@]} -eq 1 ]]; then
        SELECTED_PORT="${ports[0]}"
        print_info "Auto-selected port: $SELECTED_PORT"
    else
        echo ""
        echo "Multiple serial ports found:"
        for i in "${!ports[@]}"; do
            echo "  $((i+1)). ${ports[$i]}"
        done
        echo ""
        read -p "Select port [1-${#ports[@]}]: " selection

        if [[ "$selection" =~ ^[0-9]+$ ]] && [[ "$selection" -ge 1 ]] && [[ "$selection" -le ${#ports[@]} ]]; then
            SELECTED_PORT="${ports[$((selection-1))]}"
        else
            print_error "Invalid selection"
            return 1
        fi
    fi

    return 0
}

# =============================================================================
# Label Generation Functions
# =============================================================================

# Generate a 4-digit PIN
generate_pin() {
    printf "%04d" $((RANDOM % 10000))
}

# Create labels directory if it doesn't exist
ensure_labels_dir() {
    if [[ ! -d "$LABELS_DIR" ]]; then
        mkdir -p "$LABELS_DIR"
        print_info "Created labels directory: $LABELS_DIR"
    fi
}

# Generate QR code (requires qrencode)
generate_qr_code() {
    local device_id="$1"
    local activation_url="${ACTIVATION_URL_BASE}/${device_id}"
    local qr_file="$LABELS_DIR/${device_id}_qr.png"

    if check_command qrencode; then
        qrencode -o "$qr_file" -s 8 -m 2 "$activation_url" 2>/dev/null
        if [[ $? -eq 0 ]]; then
            print_success "QR code saved: $qr_file"
            return 0
        fi
    else
        print_warning "qrencode not installed - skipping QR generation"
        echo "       Install with: brew install qrencode (macOS)"
    fi
    return 1
}

# Generate printable HTML label (3"x2.25" thermal label size)
generate_label_html() {
    local device_id="$1"
    local device_pin="$2"
    local activation_url="${ACTIVATION_URL_BASE}/${device_id}"
    local label_file="$LABELS_DIR/${device_id}_label.html"
    local qr_file="${device_id}_qr.png"

    cat > "$label_file" << 'LABEL_EOF'
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>DEVICE_ID_PLACEHOLDER - Device Label</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    @page {
      size: 3in 2.25in;
      margin: 0;
    }

    body {
      font-family: 'Poppins', -apple-system, sans-serif;
      width: 3in;
      height: 2.25in;
      padding: 0.15in;
      background: #0A0C11;
      color: #FEFAF9;
      display: flex;
      flex-direction: column;
    }

    .header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 0.08in;
    }

    .logo {
      font-weight: 500;
      font-size: 9px;
      letter-spacing: 0.5px;
      opacity: 0.6;
    }

    .device-id {
      font-size: 18px;
      font-weight: 700;
      background: linear-gradient(90deg, #E62F6E, #E94B52);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }

    .main {
      display: flex;
      gap: 0.12in;
      flex: 1;
    }

    .qr-section {
      width: 0.7in;
      height: 0.7in;
      background: white;
      border-radius: 4px;
      padding: 3px;
      flex-shrink: 0;
    }

    .qr-section img {
      width: 100%;
      height: 100%;
    }

    .qr-placeholder {
      width: 100%;
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 8px;
      color: #333;
      text-align: center;
    }

    .info-section {
      flex: 1;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }

    .steps {
      font-size: 8px;
      line-height: 1.4;
    }

    .steps ol {
      padding-left: 12px;
      margin-top: 2px;
    }

    .steps li {
      margin-bottom: 1px;
    }

    .pin-box {
      background: rgba(21, 224, 188, 0.15);
      border: 1px solid #15E0BC;
      border-radius: 4px;
      padding: 4px 8px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-top: 4px;
    }

    .pin-label {
      font-size: 7px;
      color: rgba(254, 250, 249, 0.6);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .pin-value {
      font-size: 14px;
      font-weight: 600;
      color: #15E0BC;
      letter-spacing: 2px;
      font-family: monospace;
    }

    .footer {
      font-size: 6.5px;
      color: rgba(254, 250, 249, 0.5);
      text-align: center;
      padding-top: 0.06in;
      border-top: 1px solid rgba(254, 250, 249, 0.1);
      margin-top: 0.06in;
    }

    @media print {
      body {
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }
    }
  </style>
</head>
<body>
  <div class="header">
    <span class="logo">datajam</span>
    <span class="device-id">DEVICE_ID_PLACEHOLDER</span>
  </div>

  <div class="main">
    <div class="qr-section">
      <img src="QR_FILE_PLACEHOLDER" alt="QR Code" onerror="this.outerHTML='<div class=qr-placeholder>Scan QR<br>from PNG</div>'">
    </div>

    <div class="info-section">
      <div class="steps">
        <strong>Quick Setup:</strong>
        <ol>
          <li>Plug in USB-C power</li>
          <li>Wait for green light</li>
          <li>Scan QR to name device</li>
        </ol>
      </div>

      <div class="pin-box">
        <span class="pin-label">PIN</span>
        <span class="pin-value">PIN_PLACEHOLDER</span>
      </div>
    </div>
  </div>

  <div class="footer">
    Scan QR for status &bull; hello@data-jam.com
  </div>
</body>
</html>
LABEL_EOF

    # Replace placeholders
    sed -i '' "s/DEVICE_ID_PLACEHOLDER/${device_id}/g" "$label_file" 2>/dev/null || \
        sed -i "s/DEVICE_ID_PLACEHOLDER/${device_id}/g" "$label_file"
    sed -i '' "s/PIN_PLACEHOLDER/${device_pin}/g" "$label_file" 2>/dev/null || \
        sed -i "s/PIN_PLACEHOLDER/${device_pin}/g" "$label_file"
    sed -i '' "s|QR_FILE_PLACEHOLDER|${qr_file}|g" "$label_file" 2>/dev/null || \
        sed -i "s|QR_FILE_PLACEHOLDER|${qr_file}|g" "$label_file"

    print_success "Label HTML saved: $label_file"
    return 0
}

# Store PIN in backend via update endpoint
store_device_pin() {
    local device_id="$1"
    local pin="$2"

    local response
    response=$(curl -s -X PUT "$BACKEND_URL/api/device/$device_id/pin" \
        -H "Authorization: Bearer $ADMIN_KEY" \
        -H "Content-Type: application/json" \
        -d "{\"pin\": \"$pin\"}" 2>/dev/null)

    if echo "$response" | grep -q '"success"'; then
        return 0
    fi
    return 1
}

# Generate all label assets for a device
generate_device_label() {
    local device_id="$1"
    local device_pin="$2"

    print_step "Generating label assets for $device_id..."

    ensure_labels_dir

    # Generate QR code
    generate_qr_code "$device_id"

    # Generate HTML label
    generate_label_html "$device_id" "$device_pin"

    echo ""
    print_success "Label assets ready in: $LABELS_DIR"
    print_info "Activation URL: ${ACTIVATION_URL_BASE}/${device_id}"
    print_info "Device PIN: $device_pin"
    echo ""
    echo "To print:"
    echo "  1. Open $LABELS_DIR/${device_id}_label.html in browser"
    echo "  2. Print at actual size (3\" x 2.25\")"
    echo ""
}

# =============================================================================
# Backend API Functions
# =============================================================================

# Get list of registered devices
get_registered_devices() {
    local response
    response=$(curl -s -X GET "$BACKEND_URL/api/devices" \
        -H "Authorization: Bearer $ADMIN_KEY" \
        -H "Content-Type: application/json" 2>/dev/null)

    if [[ $? -ne 0 ]]; then
        print_error "Failed to connect to backend"
        return 1
    fi

    echo "$response"
}

# Get next available device ID
get_next_device_id() {
    local devices_json
    devices_json=$(get_registered_devices 2>/dev/null)

    if [[ -z "$devices_json" ]]; then
        echo "${DEVICE_PREFIX}0001"
        return
    fi

    # Extract JBNB device IDs and find highest number
    local max_num=0
    local nums

    if check_command jq; then
        # Get only JBNB device IDs and extract the number part
        nums=$(echo "$devices_json" | jq -r '.[].device_id // empty' 2>/dev/null | grep "^JBNB" | grep -oE '[0-9]+$' || true)
    else
        nums=$(echo "$devices_json" | grep -oE '"device_id"\s*:\s*"JBNB[0-9]+"' | grep -oE '[0-9]+' || true)
    fi

    while IFS= read -r num; do
        if [[ -n "$num" ]] && [[ "$num" =~ ^[0-9]+$ ]]; then
            num=$((10#$num))  # Remove leading zeros
            if [[ $num -gt $max_num ]]; then
                max_num=$num
            fi
        fi
    done <<< "$nums"

    local next_num=$((max_num + 1))
    printf "%s%04d" "$DEVICE_PREFIX" "$next_num"
}

# Register new device with backend
register_device() {
    local device_id="$1"
    local response

    print_step "Registering device $device_id with backend..."

    response=$(curl -s -X POST "$BACKEND_URL/api/device/register" \
        -H "Authorization: Bearer $ADMIN_KEY" \
        -H "Content-Type: application/json" \
        -d "{\"device_id\": \"$device_id\"}" 2>/dev/null)

    if [[ $? -ne 0 ]]; then
        print_error "Failed to connect to backend"
        return 1
    fi

    # Check for error in response
    if echo "$response" | grep -q '"error"'; then
        local error_msg
        if check_command jq; then
            error_msg=$(echo "$response" | jq -r '.error // "Unknown error"')
        else
            error_msg=$(echo "$response" | grep -oE '"error"\s*:\s*"[^"]+"' | sed 's/.*": *"//' | sed 's/"$//')
        fi
        print_error "Registration failed: $error_msg"
        return 1
    fi

    # Extract token from response
    local token
    if check_command jq; then
        token=$(echo "$response" | jq -r '.token // empty')
    else
        token=$(echo "$response" | grep -oE '"token"\s*:\s*"[^"]+"' | sed 's/.*": *"//' | sed 's/"$//')
    fi

    if [[ -z "$token" ]]; then
        print_error "No token received from backend"
        echo "Response: $response"
        return 1
    fi

    DEVICE_TOKEN="$token"
    print_success "Device registered successfully"
    print_info "Token: ${token:0:20}..."

    return 0
}

# Get device status from backend
get_device_status() {
    local device_id="$1"
    local response

    response=$(curl -s -X GET "$BACKEND_URL/api/devices" \
        -H "Authorization: Bearer $ADMIN_KEY" \
        -H "Content-Type: application/json" 2>/dev/null)

    if [[ $? -ne 0 ]]; then
        return 1
    fi

    # Find device in list
    if check_command jq; then
        echo "$response" | jq -r ".[] | select(.device_id == \"$device_id\")" 2>/dev/null
    else
        echo "$response" | grep -o "{[^}]*\"device_id\"[^}]*\"$device_id\"[^}]*}" | head -1
    fi
}

# =============================================================================
# Configuration Generation
# =============================================================================

# Generate device_config.h file
generate_config() {
    local device_id="$1"
    local auth_token="$2"

    print_step "Generating device configuration..."

    cat > "$DEVICE_CONFIG_FILE" << EOF
/**
 * Device Configuration - Auto-generated by NBJBTOOL.sh
 *
 * DO NOT EDIT MANUALLY - This file is overwritten during provisioning.
 *
 * Device ID: $device_id
 * Generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')
 *
 * To provision a new device, run:
 *   ./scripts/NBJBTOOL.sh
 */

#ifndef DEVICE_CONFIG_H
#define DEVICE_CONFIG_H

// =============================================================================
// Device Identity
// =============================================================================

// Device ID in format JBNB#### (e.g., JBNB0001)
#define DEVICE_ID "$device_id"

// Authentication token issued by backend during registration
#define AUTH_TOKEN "$auth_token"

// =============================================================================
// Backend Configuration
// =============================================================================

// Backend server address
#define BACKEND_HOST "172.233.144.32"
#define BACKEND_PORT 5000

// API endpoints
#define BACKEND_PATH "/api/reading"
#define HEARTBEAT_PATH "/api/heartbeat"
#define GEOLOCATION_PATH "/api/geolocation"

// =============================================================================
// Reporting Configuration
// =============================================================================

// Report interval in milliseconds (default: 5 minutes)
#define REPORT_INTERVAL_MS (5UL * 60UL * 1000UL)

// Heartbeat interval in milliseconds (default: 24 hours)
#define HEARTBEAT_INTERVAL_MS (24UL * 60UL * 60UL * 1000UL)

// =============================================================================
// OTA Configuration
// =============================================================================

// WiFi AP credentials for OTA mode
#define OTA_AP_SSID "JamBox-OTA"
#define OTA_AP_PASSWORD "jambox2026"

// OTA timeout in milliseconds (default: 5 minutes)
#define OTA_TIMEOUT_MS 300000

#endif // DEVICE_CONFIG_H
EOF

    print_success "Configuration written to $DEVICE_CONFIG_FILE"
}

# =============================================================================
# Firmware Operations
# =============================================================================

# Build firmware
build_firmware() {
    print_step "Building firmware..."

    cd "$PROJECT_DIR"

    if "$PIO_CMD" run 2>&1; then
        print_success "Firmware built successfully"
        return 0
    else
        print_error "Firmware build failed"
        return 1
    fi
}

# Flash firmware to device
flash_firmware() {
    local port="$1"

    print_step "Flashing firmware to $port..."

    cd "$PROJECT_DIR"

    # Update platformio.ini with selected port
    if "$PIO_CMD" run --target upload --upload-port "$port" 2>&1; then
        print_success "Firmware flashed successfully"
        return 0
    else
        print_error "Firmware flash failed"
        return 1
    fi
}

# Monitor serial output
monitor_device() {
    local port="$1"
    local timeout="${2:-30}"

    print_step "Monitoring device output (${timeout}s timeout)..."
    echo "Press Ctrl+C to stop"
    echo ""

    cd "$PROJECT_DIR"

    # Use timeout if available, otherwise just run monitor
    if check_command timeout; then
        timeout "$timeout" "$PIO_CMD" device monitor --port "$port" --baud 115200 2>/dev/null || true
    else
        "$PIO_CMD" device monitor --port "$port" --baud 115200
    fi
}

# =============================================================================
# Device Verification
# =============================================================================

# Wait for device to boot and verify
verify_device() {
    local port="$1"
    local device_id="$2"
    local timeout=30

    print_step "Waiting for device to boot..."

    # Wait a moment for device to reset
    sleep 3

    # Try to read serial output to verify boot
    local output=""
    local start_time=$(date +%s)

    # Use screen or cat to read serial
    if check_command screen; then
        # Read for a few seconds
        timeout 10 cat "$port" 2>/dev/null | head -50 > /tmp/nbjb_verify.txt &
        local pid=$!
        sleep 8
        kill $pid 2>/dev/null || true
        output=$(cat /tmp/nbjb_verify.txt 2>/dev/null || true)
        rm -f /tmp/nbjb_verify.txt
    fi

    if echo "$output" | grep -q "$device_id"; then
        print_success "Device verified: $device_id detected in boot output"
        return 0
    elif echo "$output" | grep -q "NB-IoT JamBox"; then
        print_success "Device booted successfully"
        return 0
    else
        print_warning "Could not verify device automatically"
        print_info "Use 'Monitor device' option to check manually"
        return 0
    fi
}

# Send test heartbeat
test_connectivity() {
    local device_id="$1"
    local token="$2"

    print_step "Testing backend connectivity for $device_id..."

    local response
    response=$(curl -s -X POST "$BACKEND_URL/api/heartbeat" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "{\"d\": \"$device_id\", \"v\": \"test\", \"uptime\": 0, \"cell_rssi\": -999}" \
        --max-time 10 2>/dev/null)

    if [[ $? -ne 0 ]]; then
        print_error "Failed to connect to backend"
        return 1
    fi

    if echo "$response" | grep -q '"status"\s*:\s*"ok"' || echo "$response" | grep -q '"message"'; then
        print_success "Backend connectivity verified"
        return 0
    else
        print_warning "Unexpected response: $response"
        return 1
    fi
}

# =============================================================================
# Menu Functions
# =============================================================================

# Show main menu
show_menu() {
    echo ""
    echo -e "${BOLD}Main Menu${NC}"
    echo "========="
    echo ""
    echo "  1. Flash Pre-Registered Device (portal workflow)"
    echo "  2. Full Provisioning (Register + Flash)"
    echo "  3. Register Device Only"
    echo "  4. Flash with Current Config"
    echo "  5. Test Device Connectivity"
    echo "  6. View Registered Devices"
    echo "  7. View Current Config"
    echo "  8. Monitor Serial Output"
    echo ""
    echo "  0. Exit"
    echo ""
}

# Flash a device that was pre-registered in the portal
do_flash_preregistered() {
    echo ""
    print_step "Flash Pre-Registered Device"
    echo ""
    echo "This flashes a device that was already created in the portal/backend."
    echo "Just enter the Device ID - the tool will fetch a fresh token automatically."
    echo ""

    # Get device ID
    read -p "Enter device ID (e.g., JBNB0002): " device_id
    if [[ -z "$device_id" ]]; then
        print_error "Device ID is required"
        return 1
    fi

    # Validate device ID format
    if ! [[ "$device_id" =~ ^JBNB[0-9]{4}$ ]]; then
        print_error "Invalid device ID format. Must be JBNB followed by 4 digits (e.g., JBNB0002)"
        return 1
    fi

    # Check if device exists in backend
    print_step "Checking if device exists in backend..."
    local device_status
    device_status=$(get_device_status "$device_id" 2>/dev/null) || true

    if [[ -z "$device_status" ]]; then
        print_error "Device $device_id not found in backend"
        echo ""
        echo "The device must be registered first. Options:"
        echo "  - Register in the portal UI"
        echo "  - Use option 2 (Full Provisioning) or option 3 (Register Only)"
        return 1
    fi
    print_success "Device $device_id found in backend"

    # Get fresh token via regenerate-token endpoint
    print_step "Fetching fresh token from backend..."
    local response
    response=$(curl -s -X POST \
        -H "Authorization: Bearer $ADMIN_KEY" \
        "$BACKEND_URL/api/device/$device_id/regenerate-token")

    local DEVICE_TOKEN
    if check_command jq; then
        DEVICE_TOKEN=$(echo "$response" | jq -r '.token // empty')
    else
        DEVICE_TOKEN=$(echo "$response" | grep -oE '"token"\s*:\s*"[^"]+"' | sed 's/.*": *"//' | sed 's/"$//')
    fi

    if [[ -z "$DEVICE_TOKEN" ]]; then
        print_error "Failed to get token from backend"
        echo "Response: $response"
        return 1
    fi
    print_success "Got fresh token: ${DEVICE_TOKEN:0:10}..."

    echo ""
    print_info "Device ID: $device_id"
    print_info "Token: ${DEVICE_TOKEN:0:10}..."
    echo ""
    read -p "Proceed with flashing? [Y/n]: " confirm
    if [[ "$confirm" == "n" || "$confirm" == "N" ]]; then
        print_info "Cancelled"
        return 0
    fi

    # Generate config
    print_step "Generating device configuration..."
    generate_config "$device_id" "$DEVICE_TOKEN"

    # Build firmware
    print_step "Building firmware..."
    if ! build_firmware; then
        print_error "Build failed"
        return 1
    fi
    print_success "Firmware built successfully"

    # Detect port
    print_step "Detecting serial port..."
    if ! select_serial_port; then
        return 1
    fi
    local port="$SELECTED_PORT"

    # Flash
    print_step "Flashing firmware to $port..."
    if ! flash_firmware "$port"; then
        print_error "Flash failed"
        return 1
    fi
    print_success "Firmware flashed successfully"

    # Log provisioning (NO TOKEN - security)
    local log_file="$PROJECT_DIR/provisioning.log"
    echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") | $device_id | flashed" >> "$log_file"
    print_success "Logged to provisioning.log (token NOT saved for security)"

    # Generate PIN and labels
    local DEVICE_PIN
    DEVICE_PIN=$(generate_pin)

    print_step "Storing PIN in backend..."
    if store_device_pin "$device_id" "$DEVICE_PIN"; then
        print_success "PIN stored successfully"
    else
        print_warning "Could not store PIN - backend may need update"
    fi

    # Generate label assets
    generate_device_label "$device_id" "$DEVICE_PIN"

    echo ""
    print_success "Device $device_id flashed successfully!"
    echo ""
    echo "Next steps:"
    echo "  1. Power cycle the device"
    echo "  2. Watch serial output to verify boot (option 8)"
    echo "  3. Print label from: $LABELS_DIR/${device_id}_label.html"
    echo "  4. Attach label to device"
    echo ""
}

# Full provisioning flow
do_full_provisioning() {
    echo ""
    print_step "Starting full provisioning workflow..."
    echo ""

    # Get next device ID
    local suggested_id
    suggested_id=$(get_next_device_id)

    echo "Suggested device ID: $suggested_id"
    read -p "Enter device ID [$suggested_id]: " device_id
    device_id="${device_id:-$suggested_id}"

    # Validate device ID format
    if ! [[ "$device_id" =~ ^JBNB[0-9]{4}$ ]]; then
        print_error "Invalid device ID format. Must be JBNB followed by 4 digits (e.g., JBNB0001)"
        return 1
    fi

    # Check if already registered
    local existing
    existing=$(get_device_status "$device_id" 2>/dev/null) || true
    if [[ -n "$existing" ]]; then
        print_warning "Device $device_id is already registered"
        read -p "Continue anyway? (will use existing token) [y/N]: " confirm
        if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
            return 1
        fi
        # Extract existing token
        if check_command jq; then
            DEVICE_TOKEN=$(echo "$existing" | jq -r '.token // empty')
        else
            DEVICE_TOKEN=$(echo "$existing" | grep -oE '"token"\s*:\s*"[^"]+"' | sed 's/.*": *"//' | sed 's/"$//')
        fi
        if [[ -z "$DEVICE_TOKEN" ]]; then
            print_error "Could not retrieve existing token"
            return 1
        fi
    else
        # Register new device
        if ! register_device "$device_id"; then
            return 1
        fi
    fi

    # Generate configuration
    generate_config "$device_id" "$DEVICE_TOKEN"

    # Build firmware
    if ! build_firmware; then
        return 1
    fi

    # Select serial port
    if ! select_serial_port; then
        return 1
    fi

    # Flash firmware
    if ! flash_firmware "$SELECTED_PORT"; then
        return 1
    fi

    # Verify device
    verify_device "$SELECTED_PORT" "$device_id"

    # Generate PIN and labels
    local DEVICE_PIN
    DEVICE_PIN=$(generate_pin)

    print_step "Storing PIN in backend..."
    if store_device_pin "$device_id" "$DEVICE_PIN"; then
        print_success "PIN stored successfully"
    else
        print_warning "Could not store PIN - backend may need update"
    fi

    # Generate label assets
    generate_device_label "$device_id" "$DEVICE_PIN"

    # Log provisioning (NO TOKEN for security - token only exists on device)
    local log_file="$PROJECT_DIR/provisioning.log"
    echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") | $device_id | provisioned+flashed | PIN=$DEVICE_PIN" >> "$log_file"
    print_success "Logged to provisioning.log"
    print_info "Token is NOT saved locally (security) - it only exists on the device"

    echo ""
    print_success "Provisioning complete for $device_id"
    echo ""
    echo "Device Summary:"
    echo "  Device ID: $device_id"
    echo "  Token: ${DEVICE_TOKEN:0:20}..."
    echo "  Port: $SELECTED_PORT"
    echo "  PIN: $DEVICE_PIN"
    echo ""
    echo "The device should now be sending data to the backend."
    echo ""
    echo "Next steps:"
    echo "  1. Print label from: $LABELS_DIR/${device_id}_label.html"
    echo "  2. Attach label to device"
    echo "  3. Use option 8 to monitor serial output"
    echo ""

    return 0
}

# Register device only
do_register_only() {
    echo ""
    print_step "Device Registration"
    echo ""

    local suggested_id
    suggested_id=$(get_next_device_id)

    echo "Suggested device ID: $suggested_id"
    read -p "Enter device ID [$suggested_id]: " device_id
    device_id="${device_id:-$suggested_id}"

    # Validate device ID format
    if ! [[ "$device_id" =~ ^JBNB[0-9]{4}$ ]]; then
        print_error "Invalid device ID format. Must be JBNB followed by 4 digits"
        return 1
    fi

    if register_device "$device_id"; then
        echo ""
        print_success "Device registered: $device_id"
        echo ""
        print_warning "Token shown once - NOT saved for security."
        print_warning "If you lose it, use 'regenerate-token' to get a new one."
        echo ""

        # Log registration (NO TOKEN)
        local log_file="$PROJECT_DIR/provisioning.log"
        echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") | $device_id | registered" >> "$log_file"

        read -p "Flash this device now? [Y/n]: " do_flash
        if [[ "$do_flash" != "n" && "$do_flash" != "N" ]]; then
            generate_config "$device_id" "$DEVICE_TOKEN"

            print_step "Building firmware..."
            if ! build_firmware; then
                print_error "Build failed"
                return 1
            fi

            print_step "Detecting serial port..."
            if ! select_serial_port; then
                return 1
            fi

            print_step "Flashing to $SELECTED_PORT..."
            if flash_firmware "$SELECTED_PORT"; then
                print_success "Device $device_id registered and flashed!"
            fi
        fi
    fi
}

# Flash firmware only
do_flash_only() {
    echo ""
    print_step "Flash Firmware"
    echo ""

    # Check current config
    if [[ -f "$DEVICE_CONFIG_FILE" ]]; then
        local current_id
        current_id=$(grep '#define DEVICE_ID' "$DEVICE_CONFIG_FILE" | grep -oE '"[^"]+"' | tr -d '"')
        print_info "Current config device ID: $current_id"
    else
        print_warning "No device_config.h found - using default config"
    fi

    read -p "Proceed with flash? [Y/n]: " confirm
    if [[ "$confirm" == "n" || "$confirm" == "N" ]]; then
        return 1
    fi

    # Build firmware
    if ! build_firmware; then
        return 1
    fi

    # Select serial port
    if ! select_serial_port; then
        return 1
    fi

    # Flash firmware
    flash_firmware "$SELECTED_PORT"
}

# Test device connectivity
do_test_connectivity() {
    echo ""
    print_step "Test Device Connectivity"
    echo ""

    # Get device ID from config
    local device_id token
    if [[ -f "$DEVICE_CONFIG_FILE" ]]; then
        device_id=$(grep '#define DEVICE_ID' "$DEVICE_CONFIG_FILE" | grep -oE '"[^"]+"' | tr -d '"')
        token=$(grep '#define AUTH_TOKEN' "$DEVICE_CONFIG_FILE" | grep -oE '"[^"]+"' | tr -d '"')
    fi

    if [[ -n "$device_id" && -n "$token" ]]; then
        print_info "Testing device: $device_id"
        test_connectivity "$device_id" "$token"
    else
        read -p "Enter device ID: " device_id
        read -p "Enter auth token: " token
        test_connectivity "$device_id" "$token"
    fi
}

# View registered devices
do_view_devices() {
    echo ""
    print_step "Registered Devices"
    echo ""

    local response
    response=$(get_registered_devices)

    if [[ $? -ne 0 || -z "$response" ]]; then
        print_error "Failed to retrieve devices"
        return 1
    fi

    if check_command jq; then
        echo "$response" | jq -r '.[] | "  \(.device_id) - Status: \(.status) - Last seen: \(.last_seen_at // "never")"' 2>/dev/null
    else
        echo "$response"
    fi
    echo ""
}

# View current config
do_view_config() {
    echo ""
    print_step "Current Device Configuration"
    echo ""

    if [[ -f "$DEVICE_CONFIG_FILE" ]]; then
        echo "File: $DEVICE_CONFIG_FILE"
        echo ""
        grep -E '^\s*(#define\s+(DEVICE_ID|AUTH_TOKEN|BACKEND_HOST|BACKEND_PORT))' "$DEVICE_CONFIG_FILE" | while read line; do
            echo "  $line"
        done
        echo ""
    else
        print_warning "No device_config.h found"
    fi
}

# Monitor serial output
do_monitor() {
    echo ""
    print_step "Serial Monitor"
    echo ""

    if ! select_serial_port; then
        return 1
    fi

    echo "Starting serial monitor on $SELECTED_PORT..."
    echo "Press Ctrl+C to exit"
    echo ""

    "$PIO_CMD" device monitor --port "$SELECTED_PORT" --baud 115200
}

# =============================================================================
# Main
# =============================================================================

main() {
    # Handle command line arguments
    case "${1:-}" in
        --help|-h)
            echo "NBJBTOOL.sh - NB-IoT JamBox Device Provisioning Tool"
            echo ""
            echo "Usage:"
            echo "  $0           Interactive menu"
            echo "  $0 --help    Show this help"
            echo ""
            echo "This tool is used to provision NB-IoT JamBox devices for"
            echo "the Data Jam network. It handles device registration,"
            echo "firmware configuration, and flashing."
            echo ""
            exit 0
            ;;
        --version|-v)
            echo "NBJBTOOL.sh version $TOOL_VERSION"
            exit 0
            ;;
    esac

    print_header

    # Check prerequisites
    if ! check_prerequisites; then
        exit 1
    fi

    # Main menu loop
    while true; do
        show_menu
        read -p "Select option: " choice

        case "$choice" in
            1)
                do_flash_preregistered
                ;;
            2)
                do_full_provisioning
                ;;
            3)
                do_register_only
                ;;
            4)
                do_flash_only
                ;;
            5)
                do_test_connectivity
                ;;
            6)
                do_view_devices
                ;;
            7)
                do_view_config
                ;;
            8)
                do_monitor
                ;;
            0|q|Q)
                echo ""
                print_info "Goodbye!"
                exit 0
                ;;
            *)
                print_error "Invalid option"
                ;;
        esac

        echo ""
        read -p "Press Enter to continue..."
    done
}

# Run main function
main "$@"
