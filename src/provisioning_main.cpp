/**
 * NB-IoT JamBox Cellular Provisioning Firmware
 *
 * PURPOSE: Manufacturing-grade cellular provisioning that runs ONCE on
 * factory-fresh devices to bring up the NB-IoT modem and persist a success flag.
 *
 * This firmware is intended for initial device validation during manufacturing.
 * After successful cellular provisioning, the production firmware (main.cpp)
 * should be flashed for normal operation.
 *
 * Hardware Configuration:
 *   M5Stack AtomS3 DTU-NB-IoT (ESP32-S3 + SIM7028)
 *   - GPIO5 = ESP32 TX -> Modem RX
 *   - GPIO6 = ESP32 RX <- Modem TX
 *   - GPIO35 = Built-in RGB LED (WS2812, single LED)
 *   - GPIO41 = Main Button (retry on failure)
 *   - Modem Baud: 115200
 *
 * LED Status:
 *   - PURPLE solid: Booting/initializing
 *   - RED slow blink (500ms): Searching for network
 *   - GREEN solid: Success - provisioning complete
 *   - RED fast blink (100ms): Failure
 *
 * On Success:
 *   - NVS key stored: namespace="jambox", key="cellular_ok", value=1
 *   - LED set to solid GREEN
 *   - Idle loop prints status every 30 seconds
 *
 * On Failure:
 *   - LED set to fast-blink RED
 *   - Detailed diagnostics printed to serial
 *   - Button press on GPIO41 triggers manual retry
 *
 * AT Command Sequence (deterministic order):
 *   1. AT - Test modem alive (10 retries, 2s delay)
 *   2. ATE0 - Disable echo
 *   3. AT+CPIN? - Verify SIM ready
 *   4. AT+QCBAND=0,2,4,12,13,66 - Lock to US NB-IoT bands
 *   5. AT+CFUN=1,1 - Full functionality + modem reset
 *   6. (5 second wait for modem reset)
 *   7. AT+CEREG? - Poll until registered (5 min timeout)
 *   8. AT+CGATT=1 - Attach to packet domain (30s timeout)
 *   9. AT+NETOPEN - Open IP stack (60s timeout)
 *   10. AT+IPADDR - Verify IP obtained
 *
 * Version: 1.0.0
 * Target: M5Stack AtomS3 DTU-NB-IoT
 * Framework: Arduino on ESP32
 */

#include <Arduino.h>
#include <FastLED.h>
#include <Preferences.h>

// =============================================================================
// Hardware Pin Definitions
// =============================================================================

#define MODEM_TX_PIN    5       // ESP32 TX -> Modem RX
#define MODEM_RX_PIN    6       // ESP32 RX <- Modem TX
#define MODEM_BAUD      115200
#define LED_PIN         35      // AtomS3 RGB LED (WS2812)
#define BUTTON_PIN      41      // AtomS3 Main Button
#define NUM_LEDS        1       // Single RGB LED

// =============================================================================
// Timing Constants
// =============================================================================

#define MODEM_TEST_RETRIES      10      // Number of AT test retries
#define MODEM_TEST_DELAY_MS     2000    // Delay between AT test retries
#define MODEM_RESET_WAIT_MS     5000    // Wait after CFUN=1,1
#define CEREG_POLL_INTERVAL_MS  5000    // Poll interval for registration
#define CEREG_TIMEOUT_MS        300000  // 5 minutes for registration
#define CGATT_TIMEOUT_MS        30000   // 30 seconds for PS attach
#define NETOPEN_TIMEOUT_MS      60000   // 60 seconds for NETOPEN
#define AT_COMMAND_TIMEOUT_MS   10000   // Default AT command timeout
#define STATUS_PRINT_INTERVAL   30000   // Print status every 30 seconds

// =============================================================================
// LED Colors (RGB order for WS2812)
// =============================================================================

#define COLOR_OFF       CRGB::Black
#define COLOR_GREEN     CRGB::Green
#define COLOR_RED       CRGB::Red
#define COLOR_PURPLE    CRGB::Purple

// =============================================================================
// LED Status States
// =============================================================================

enum LedStatus {
    LED_STATUS_BOOTING,     // PURPLE solid
    LED_STATUS_SEARCHING,   // RED slow blink (500ms)
    LED_STATUS_SUCCESS,     // GREEN solid
    LED_STATUS_FAILURE      // RED fast blink (100ms)
};

// =============================================================================
// Provisioning Result Codes
// =============================================================================

enum ProvisioningResult {
    PROV_SUCCESS = 0,
    PROV_FAIL_MODEM_NOT_RESPONDING,
    PROV_FAIL_ECHO_DISABLE,
    PROV_FAIL_SIM_NOT_READY,
    PROV_FAIL_BAND_CONFIG,
    PROV_FAIL_MODEM_RESET,
    PROV_FAIL_REGISTRATION_TIMEOUT,
    PROV_FAIL_PS_ATTACH,
    PROV_FAIL_NETOPEN,
    PROV_FAIL_NO_IP_ADDRESS,
    PROV_FAIL_NVS_WRITE
};

// =============================================================================
// Global State
// =============================================================================

// FastLED array
CRGB g_leds[NUM_LEDS];

// LED state
static LedStatus g_ledStatus = LED_STATUS_BOOTING;
static uint32_t g_lastLedUpdate = 0;
static bool g_ledBlinkState = false;

// UART for modem communication
HardwareSerial ModemSerial(1);

// AT command response buffer
static char g_atBuffer[512];
static size_t g_atBufferLen = 0;

// Provisioning state
static ProvisioningResult g_lastResult = PROV_SUCCESS;
static char g_lastAtResponse[256] = "";
static char g_failedStep[64] = "";
static char g_ipAddress[32] = "";
static bool g_provisioningComplete = false;

// NVS
Preferences g_preferences;

// =============================================================================
// Forward Declarations
// =============================================================================

static void ledSetStatus(LedStatus status);
static void ledUpdate();
static void ledSetColor(CRGB color);
static void atClearBuffer();
static bool atSendCommand(const char* cmd, const char* expect, uint32_t timeoutMs);
static ProvisioningResult runProvisioningSequence();
static void printDiagnostics();
static const char* getResultString(ProvisioningResult result);

// =============================================================================
// LED Management
// =============================================================================

/**
 * Set LED to a specific color immediately
 */
static void ledSetColor(CRGB color) {
    g_leds[0] = color;
    FastLED.show();
}

/**
 * Set LED status mode
 */
static void ledSetStatus(LedStatus status) {
    g_ledStatus = status;
    g_lastLedUpdate = millis();
    g_ledBlinkState = false;

    switch (status) {
        case LED_STATUS_BOOTING:
            ledSetColor(COLOR_PURPLE);
            break;
        case LED_STATUS_SEARCHING:
            ledSetColor(COLOR_RED);
            break;
        case LED_STATUS_SUCCESS:
            ledSetColor(COLOR_GREEN);
            break;
        case LED_STATUS_FAILURE:
            ledSetColor(COLOR_RED);
            break;
    }
}

/**
 * Update LED animation (call from loop)
 * Handles blinking patterns for searching and failure states
 */
static void ledUpdate() {
    uint32_t now = millis();
    uint32_t elapsed = now - g_lastLedUpdate;

    switch (g_ledStatus) {
        case LED_STATUS_BOOTING:
        case LED_STATUS_SUCCESS:
            // Solid color, no animation needed
            break;

        case LED_STATUS_SEARCHING:
            // Slow blink red (500ms on, 500ms off)
            if (elapsed >= 500) {
                g_lastLedUpdate = now;
                g_ledBlinkState = !g_ledBlinkState;
                ledSetColor(g_ledBlinkState ? COLOR_RED : COLOR_OFF);
            }
            break;

        case LED_STATUS_FAILURE:
            // Fast blink red (100ms on, 100ms off)
            if (elapsed >= 100) {
                g_lastLedUpdate = now;
                g_ledBlinkState = !g_ledBlinkState;
                ledSetColor(g_ledBlinkState ? COLOR_RED : COLOR_OFF);
            }
            break;
    }
}

// =============================================================================
// AT Command Interface
// =============================================================================

/**
 * Clear the AT response buffer
 */
static void atClearBuffer() {
    g_atBufferLen = 0;
    g_atBuffer[0] = '\0';
}

/**
 * Send AT command and wait for expected response
 *
 * @param cmd       AT command string (without CR/LF)
 * @param expect    Expected response substring (or NULL to just wait for any response)
 * @param timeoutMs Maximum time to wait for response
 * @return true if expected response found, false on timeout or ERROR
 */
static bool atSendCommand(const char* cmd, const char* expect, uint32_t timeoutMs) {
    atClearBuffer();

    // Flush any pending input from modem
    while (ModemSerial.available()) {
        ModemSerial.read();
    }

    // Send command
    Serial.printf("[AT TX] %s\n", cmd);
    ModemSerial.print(cmd);
    ModemSerial.print("\r\n");

    uint32_t startTime = millis();
    bool found = false;

    // Read response with timeout
    while ((millis() - startTime) < timeoutMs && !found) {
        // Update LED animation during long waits
        ledUpdate();

        while (ModemSerial.available() && g_atBufferLen < sizeof(g_atBuffer) - 1) {
            char c = ModemSerial.read();
            g_atBuffer[g_atBufferLen++] = c;
            g_atBuffer[g_atBufferLen] = '\0';

            // Check for expected response
            if (expect && strstr(g_atBuffer, expect)) {
                found = true;
                break;
            }

            // Check for error response
            if (strstr(g_atBuffer, "ERROR")) {
                Serial.printf("[AT RX] %s\n", g_atBuffer);
                // Save last response for diagnostics
                strncpy(g_lastAtResponse, g_atBuffer, sizeof(g_lastAtResponse) - 1);
                g_lastAtResponse[sizeof(g_lastAtResponse) - 1] = '\0';
                return false;
            }
        }
        delay(10);
    }

    Serial.printf("[AT RX] %s\n", g_atBuffer);

    // Save last response for diagnostics
    strncpy(g_lastAtResponse, g_atBuffer, sizeof(g_lastAtResponse) - 1);
    g_lastAtResponse[sizeof(g_lastAtResponse) - 1] = '\0';

    return found;
}

// =============================================================================
// Provisioning Sequence
// =============================================================================

/**
 * Run the complete cellular provisioning sequence
 *
 * This function executes the deterministic AT command sequence required
 * to bring up the NB-IoT modem and verify data connectivity.
 *
 * @return ProvisioningResult indicating success or specific failure point
 */
static ProvisioningResult runProvisioningSequence() {
    Serial.println("========================================");
    Serial.println("NB-IoT CELLULAR PROVISIONING");
    Serial.println("========================================");
    Serial.println();

    // -------------------------------------------------------------------------
    // Step 1: Test modem alive
    // AT Command: AT
    // Purpose: Verify modem is responding
    // Expected Response: OK
    // Timeout: 2000ms per attempt, 10 retries
    // -------------------------------------------------------------------------
    Serial.println("[STEP 1/10] Testing modem communication...");
    strncpy(g_failedStep, "AT - Modem test", sizeof(g_failedStep));

    bool modemReady = false;
    for (int attempt = 1; attempt <= MODEM_TEST_RETRIES; attempt++) {
        Serial.printf("  Attempt %d/%d...\n", attempt, MODEM_TEST_RETRIES);

        if (atSendCommand("AT", "OK", 2000)) {
            modemReady = true;
            Serial.println("  SUCCESS: Modem responding");
            break;
        }

        Serial.printf("  No response, waiting %d ms...\n", MODEM_TEST_DELAY_MS);

        // Update LED during wait
        uint32_t waitStart = millis();
        while ((millis() - waitStart) < MODEM_TEST_DELAY_MS) {
            ledUpdate();
            delay(50);
        }
    }

    if (!modemReady) {
        Serial.println("  FAILED: Modem not responding after all retries");
        return PROV_FAIL_MODEM_NOT_RESPONDING;
    }
    Serial.println();

    // -------------------------------------------------------------------------
    // Step 2: Disable echo
    // AT Command: ATE0
    // Purpose: Disable command echo for cleaner parsing
    // Expected Response: OK
    // Timeout: 2000ms
    // -------------------------------------------------------------------------
    Serial.println("[STEP 2/10] Disabling echo...");
    strncpy(g_failedStep, "ATE0 - Disable echo", sizeof(g_failedStep));

    if (!atSendCommand("ATE0", "OK", 2000)) {
        Serial.println("  WARNING: Echo disable failed (non-fatal)");
        // Continue anyway - this is not critical
    } else {
        Serial.println("  SUCCESS: Echo disabled");
    }
    Serial.println();

    // -------------------------------------------------------------------------
    // Step 3: Verify SIM ready
    // AT Command: AT+CPIN?
    // Purpose: Check SIM card is present and ready
    // Expected Response: +CPIN: READY
    // Timeout: 5000ms
    // Reference: SIM7028 AT Command Manual Section 5.5
    // -------------------------------------------------------------------------
    Serial.println("[STEP 3/10] Checking SIM card status...");
    strncpy(g_failedStep, "AT+CPIN? - SIM status", sizeof(g_failedStep));

    if (!atSendCommand("AT+CPIN?", "READY", 5000)) {
        Serial.println("  FAILED: SIM card not ready");
        Serial.println("  Check: Is SIM inserted correctly?");
        Serial.println("  Check: Gold contacts up, cutaway edge out");
        return PROV_FAIL_SIM_NOT_READY;
    }
    Serial.println("  SUCCESS: SIM card ready");
    Serial.println();

    // -------------------------------------------------------------------------
    // Step 4: Lock to US NB-IoT bands
    // AT Command: AT+QCBAND=0,2,4,12,13,66
    // Purpose: Configure modem to search only US NB-IoT bands
    //          Speeds up registration by avoiding non-US bands
    // Expected Response: OK
    // Timeout: 5000ms
    // Bands: 2 (1900MHz), 4 (1700MHz), 12 (700MHz), 13 (700MHz), 66 (AWS-3)
    // -------------------------------------------------------------------------
    Serial.println("[STEP 4/10] Configuring US NB-IoT bands...");
    strncpy(g_failedStep, "AT+QCBAND - Band config", sizeof(g_failedStep));

    if (!atSendCommand("AT+QCBAND=0,2,4,12,13,66", "OK", 5000)) {
        Serial.println("  FAILED: Band configuration failed");
        return PROV_FAIL_BAND_CONFIG;
    }
    Serial.println("  SUCCESS: Bands locked to 2,4,12,13,66");
    Serial.println();

    // -------------------------------------------------------------------------
    // Step 5: Full functionality + modem reset
    // AT Command: AT+CFUN=1,1
    // Purpose: Set full functionality mode and reset modem
    //          Required after band change to apply new configuration
    // Expected Response: OK
    // Timeout: 5000ms
    // Note: Modem will reset and need time to reinitialize
    // -------------------------------------------------------------------------
    Serial.println("[STEP 5/10] Resetting modem with full functionality...");
    strncpy(g_failedStep, "AT+CFUN=1,1 - Modem reset", sizeof(g_failedStep));

    if (!atSendCommand("AT+CFUN=1,1", "OK", 5000)) {
        Serial.println("  FAILED: Modem reset command failed");
        return PROV_FAIL_MODEM_RESET;
    }
    Serial.println("  SUCCESS: Reset command accepted");
    Serial.println();

    // -------------------------------------------------------------------------
    // Step 6: Wait for modem reset
    // Purpose: Allow modem time to reinitialize after CFUN reset
    // Wait: 5000ms
    // -------------------------------------------------------------------------
    Serial.println("[STEP 6/10] Waiting for modem reset...");
    Serial.printf("  Waiting %d ms for modem to reinitialize...\n", MODEM_RESET_WAIT_MS);

    uint32_t waitStart = millis();
    while ((millis() - waitStart) < MODEM_RESET_WAIT_MS) {
        ledUpdate();
        delay(100);
    }
    Serial.println("  Wait complete");
    Serial.println();

    // Verify modem is back up
    Serial.println("  Verifying modem is responding...");
    if (!atSendCommand("AT", "OK", 5000)) {
        Serial.println("  FAILED: Modem not responding after reset");
        return PROV_FAIL_MODEM_RESET;
    }
    Serial.println("  SUCCESS: Modem responding after reset");
    Serial.println();

    // -------------------------------------------------------------------------
    // Step 7: Poll for network registration
    // AT Command: AT+CEREG?
    // Purpose: Query EPS (LTE/NB-IoT) network registration status
    // Expected Response: +CEREG: <n>,<stat> where stat=1 (home) or stat=5 (roaming)
    // Timeout: 5 minutes total, poll every 5 seconds
    // Reference: SIM7028 AT Command Manual Section 7.2
    // Registration codes:
    //   0 = Not registered, not searching
    //   1 = Registered, home network
    //   2 = Not registered, searching
    //   3 = Registration denied
    //   5 = Registered, roaming (normal for Hologram)
    // -------------------------------------------------------------------------
    Serial.println("[STEP 7/10] Waiting for network registration...");
    Serial.println("  This may take 1-3 minutes for NB-IoT...");
    strncpy(g_failedStep, "AT+CEREG? - Network registration", sizeof(g_failedStep));

    ledSetStatus(LED_STATUS_SEARCHING);

    uint32_t regStartTime = millis();
    bool registered = false;
    int pollCount = 0;

    while ((millis() - regStartTime) < CEREG_TIMEOUT_MS) {
        pollCount++;

        if (atSendCommand("AT+CEREG?", "OK", 5000)) {
            // Parse registration status
            char* ptr = strstr(g_atBuffer, "+CEREG:");
            if (ptr) {
                int n = 0, stat = 0;
                if (sscanf(ptr, "+CEREG: %d,%d", &n, &stat) == 2 ||
                    sscanf(ptr, "+CEREG:%d,%d", &n, &stat) == 2) {

                    Serial.printf("  Poll %d: stat=%d ", pollCount, stat);

                    switch (stat) {
                        case 0: Serial.println("(not registered, not searching)"); break;
                        case 1: Serial.println("(registered, home network)"); break;
                        case 2: Serial.println("(not registered, searching...)"); break;
                        case 3: Serial.println("(registration denied)"); break;
                        case 4: Serial.println("(unknown)"); break;
                        case 5: Serial.println("(registered, roaming)"); break;
                        default: Serial.println("(unknown status)"); break;
                    }

                    if (stat == 1 || stat == 5) {
                        registered = true;
                        break;
                    }

                    if (stat == 3) {
                        Serial.println("  FAILED: Registration denied by network");
                        return PROV_FAIL_REGISTRATION_TIMEOUT;
                    }
                }
            }
        }

        // Wait before next poll
        uint32_t pollWaitStart = millis();
        while ((millis() - pollWaitStart) < CEREG_POLL_INTERVAL_MS) {
            ledUpdate();
            delay(50);
        }
    }

    if (!registered) {
        uint32_t elapsedSec = (millis() - regStartTime) / 1000;
        Serial.printf("  FAILED: Registration timeout after %lu seconds\n", elapsedSec);
        Serial.println("  Check: Is antenna connected?");
        Serial.println("  Check: Is SIM activated with carrier?");
        Serial.println("  Check: Are you in NB-IoT coverage area?");
        return PROV_FAIL_REGISTRATION_TIMEOUT;
    }

    uint32_t regTime = (millis() - regStartTime) / 1000;
    Serial.printf("  SUCCESS: Registered to network in %lu seconds\n", regTime);
    Serial.println();

    // Get and display signal quality
    if (atSendCommand("AT+CSQ", "OK", 5000)) {
        char* ptr = strstr(g_atBuffer, "+CSQ:");
        if (ptr) {
            int rssi = 99, ber = 99;
            if (sscanf(ptr, "+CSQ: %d,%d", &rssi, &ber) == 2 ||
                sscanf(ptr, "+CSQ:%d,%d", &rssi, &ber) == 2) {
                int dbm = (rssi == 99) ? -999 : (-113 + rssi * 2);
                Serial.printf("  Signal quality: RSSI=%d (%d dBm)\n", rssi, dbm);
            }
        }
    }

    // Get and display network info
    if (atSendCommand("AT+COPS?", "OK", 5000)) {
        char* ptr = strstr(g_atBuffer, "+COPS:");
        if (ptr) {
            Serial.printf("  Operator: %s\n", ptr);
        }
    }
    Serial.println();

    // -------------------------------------------------------------------------
    // Step 8: Close any existing network connection (clean slate)
    // AT Command: AT+NETCLOSE
    // Purpose: Ensure we start from a clean state
    // Expected Response: OK or +NETCLOSE (may already be closed)
    // Timeout: 5000ms
    // -------------------------------------------------------------------------
    Serial.println("[STEP 8/12] Closing any existing network connection...");
    atSendCommand("AT+NETCLOSE", "OK", 5000);  // Ignore errors - may already be closed
    Serial.println("  Done (cleaned network state)");
    delay(1000);  // Brief settle time
    Serial.println();

    // -------------------------------------------------------------------------
    // Step 9: Configure PDP context with Hologram APN
    // AT Command: AT+CGDCONT=0,"IP","hologram"
    // Purpose: Define PDP context 0 with Hologram APN
    //          THIS IS CRITICAL - without it, NETOPEN won't get an IP
    // Expected Response: OK
    // Timeout: 5000ms
    // Reference: SIM7028 AT Command Manual Section 7.5
    // -------------------------------------------------------------------------
    Serial.println("[STEP 9/12] Configuring PDP context with Hologram APN...");
    strncpy(g_failedStep, "AT+CGDCONT - Configure APN", sizeof(g_failedStep));

    if (!atSendCommand("AT+CGDCONT=0,\"IP\",\"hologram\"", "OK", 5000)) {
        Serial.println("  FAILED: Could not configure PDP context");
        Serial.printf("  Response: %s\n", g_atBuffer);
        return PROV_FAIL_PS_ATTACH;  // Reuse this error code
    }
    Serial.println("  SUCCESS: PDP context configured (CID 0, APN: hologram)");
    Serial.println();

    // -------------------------------------------------------------------------
    // Step 10: Attach to packet domain
    // AT Command: AT+CGATT=1
    // Purpose: Attach to PS (Packet Switched) domain for data services
    // Expected Response: OK
    // Timeout: 30000ms
    // Reference: SIM7028 AT Command Manual Section 7.9
    // -------------------------------------------------------------------------
    Serial.println("[STEP 10/12] Attaching to packet domain...");
    strncpy(g_failedStep, "AT+CGATT=1 - PS attach", sizeof(g_failedStep));

    if (!atSendCommand("AT+CGATT=1", "OK", CGATT_TIMEOUT_MS)) {
        Serial.println("  FAILED: Packet domain attach failed");
        return PROV_FAIL_PS_ATTACH;
    }
    Serial.println("  SUCCESS: Attached to packet domain");
    Serial.println();

    // -------------------------------------------------------------------------
    // Step 11: Open IP stack
    // AT Command: AT+NETOPEN
    // Purpose: Open the IP network connection
    //          CRITICAL: Registration alone does NOT enable data!
    // Expected Response: +NETOPEN: 0
    // Timeout: 60000ms
    // Reference: SIM7028 AT Command Manual Section 9.2
    // Note: Error code 0 = success, other codes indicate failure
    // -------------------------------------------------------------------------
    Serial.println("[STEP 11/12] Opening IP stack...");
    Serial.println("  CRITICAL: This enables data connectivity");
    strncpy(g_failedStep, "AT+NETOPEN - Open IP stack", sizeof(g_failedStep));

    if (!atSendCommand("AT+NETOPEN", "+NETOPEN: 0", NETOPEN_TIMEOUT_MS)) {
        // Check if already open (not an error)
        if (strstr(g_atBuffer, "Network is already opened")) {
            Serial.println("  INFO: Network already open (OK)");
        } else {
            Serial.println("  FAILED: Could not open IP stack");
            Serial.printf("  Response: %s\n", g_atBuffer);
            return PROV_FAIL_NETOPEN;
        }
    } else {
        Serial.println("  SUCCESS: IP stack opened");
    }

    // Wait for IP assignment - NB-IoT can be slow
    Serial.println("  Waiting 3 seconds for IP assignment...");
    delay(3000);
    Serial.println();

    // -------------------------------------------------------------------------
    // Step 12: Verify IP address obtained
    // First try AT+CGDCONT? which shows IP in PDP context
    // Then try AT+CGPADDR and AT+IPADDR as fallbacks
    // -------------------------------------------------------------------------
    Serial.println("[STEP 12/12] Verifying IP address...");
    strncpy(g_failedStep, "IP address verification", sizeof(g_failedStep));

    bool gotIp = false;

    // Method 1: Extract IP from CGDCONT response (most reliable)
    Serial.println("  Checking PDP context for IP (AT+CGDCONT?)...");
    if (atSendCommand("AT+CGDCONT?", "OK", 5000)) {
        // Look for: +CGDCONT: 0,"IP","hologram","10.x.x.x"
        char* ptr = strstr(g_atBuffer, "+CGDCONT: 0,");
        if (ptr) {
            // Find the IP address (4th field, after 3rd comma)
            int commaCount = 0;
            char* ipStart = ptr;
            while (*ipStart && commaCount < 3) {
                if (*ipStart == ',') commaCount++;
                ipStart++;
            }
            // Skip the opening quote
            if (*ipStart == '"') ipStart++;

            // Check if we have a digit (IP address)
            if (*ipStart >= '0' && *ipStart <= '9') {
                char* ipEnd = ipStart;
                while (*ipEnd && *ipEnd != '"' && *ipEnd != '\r' && *ipEnd != '\n') ipEnd++;

                size_t ipLen = ipEnd - ipStart;
                if (ipLen > 0 && ipLen < sizeof(g_ipAddress)) {
                    strncpy(g_ipAddress, ipStart, ipLen);
                    g_ipAddress[ipLen] = '\0';
                    Serial.printf("  SUCCESS: IP from CGDCONT: %s\n", g_ipAddress);
                    gotIp = true;
                }
            }
        }
    }

    // Method 2: Try AT+CGPADDR=0 (PDP address for context 0)
    if (!gotIp) {
        Serial.println("  Trying AT+CGPADDR=0...");
        if (atSendCommand("AT+CGPADDR=0", "+CGPADDR:", 5000)) {
            // Format: +CGPADDR: 0,"10.x.x.x"
            char* ptr = strstr(g_atBuffer, "+CGPADDR:");
            if (ptr) {
                ptr = strchr(ptr, '"');
                if (ptr) {
                    ptr++;  // Skip opening quote
                    char* ipEnd = strchr(ptr, '"');
                    if (ipEnd && (ipEnd - ptr) < (int)sizeof(g_ipAddress)) {
                        strncpy(g_ipAddress, ptr, ipEnd - ptr);
                        g_ipAddress[ipEnd - ptr] = '\0';
                        Serial.printf("  SUCCESS: IP from CGPADDR: %s\n", g_ipAddress);
                        gotIp = true;
                    }
                }
            }
        }
    }

    // Method 3: Try AT+IPADDR (original method, may not work on all firmware)
    if (!gotIp) {
        Serial.println("  Trying AT+IPADDR...");
        if (atSendCommand("AT+IPADDR", "+IPADDR:", 5000)) {
            char* ptr = strstr(g_atBuffer, "+IPADDR:");
            if (ptr) {
                ptr += 8;
                while (*ptr == ' ') ptr++;
                if (*ptr >= '0' && *ptr <= '9') {
                    char* ipEnd = ptr;
                    while (*ipEnd && *ipEnd != '\r' && *ipEnd != '\n') ipEnd++;
                    size_t ipLen = ipEnd - ptr;
                    if (ipLen > 0 && ipLen < sizeof(g_ipAddress)) {
                        strncpy(g_ipAddress, ptr, ipLen);
                        g_ipAddress[ipLen] = '\0';
                        Serial.printf("  SUCCESS: IP from IPADDR: %s\n", g_ipAddress);
                        gotIp = true;
                    }
                }
            }
        }
    }

    // Check PDP context activation status
    Serial.println("  Checking PDP context activation (AT+CGACT?)...");
    atSendCommand("AT+CGACT?", "OK", 5000);

    if (!gotIp) {
        Serial.println("  FAILED: Could not obtain IP address from any method");
        return PROV_FAIL_NO_IP_ADDRESS;
    }

    Serial.println();

    // Extract IP address for display
    char* ipPtr = strstr(g_atBuffer, "+IPADDR:");
    if (ipPtr) {
        ipPtr += 8;  // Skip "+IPADDR:"
        while (*ipPtr == ' ') ipPtr++;  // Skip spaces

        char* ipEnd = ipPtr;
        while (*ipEnd && *ipEnd != '\r' && *ipEnd != '\n') ipEnd++;

        size_t ipLen = ipEnd - ipPtr;
        if (ipLen > 0 && ipLen < sizeof(g_ipAddress)) {
            strncpy(g_ipAddress, ipPtr, ipLen);
            g_ipAddress[ipLen] = '\0';
        }
    }

    Serial.printf("  SUCCESS: IP address assigned: %s\n", g_ipAddress);
    Serial.println();

    // -------------------------------------------------------------------------
    // All steps complete - provisioning successful
    // -------------------------------------------------------------------------
    Serial.println("========================================");
    Serial.println("CELLULAR PROVISIONING COMPLETE");
    Serial.println("========================================");
    Serial.printf("IP Address: %s\n", g_ipAddress);
    Serial.println();

    return PROV_SUCCESS;
}

// =============================================================================
// NVS Storage
// =============================================================================

/**
 * Store provisioning success flag in NVS
 *
 * @return true if successfully stored, false on error
 */
static bool storeProvisioningFlag() {
    Serial.println("[NVS] Storing provisioning flag...");

    if (!g_preferences.begin("jambox", false)) {
        Serial.println("[NVS] FAILED: Could not open namespace");
        return false;
    }

    // Store cellular_ok = 1 to indicate successful provisioning
    if (g_preferences.putUChar("cellular_ok", 1) == 0) {
        Serial.println("[NVS] FAILED: Could not write key");
        g_preferences.end();
        return false;
    }

    // Verify the write
    uint8_t readBack = g_preferences.getUChar("cellular_ok", 0);
    g_preferences.end();

    if (readBack != 1) {
        Serial.println("[NVS] FAILED: Verification failed");
        return false;
    }

    Serial.println("[NVS] SUCCESS: cellular_ok=1 stored and verified");
    return true;
}

/**
 * Check if device was already provisioned
 *
 * @return true if cellular_ok flag is set
 */
static bool checkAlreadyProvisioned() {
    if (!g_preferences.begin("jambox", true)) {  // Read-only
        return false;
    }

    uint8_t flag = g_preferences.getUChar("cellular_ok", 0);
    g_preferences.end();

    return (flag == 1);
}

// =============================================================================
// Diagnostics
// =============================================================================

/**
 * Get human-readable string for provisioning result
 */
static const char* getResultString(ProvisioningResult result) {
    switch (result) {
        case PROV_SUCCESS:                      return "SUCCESS";
        case PROV_FAIL_MODEM_NOT_RESPONDING:    return "MODEM_NOT_RESPONDING";
        case PROV_FAIL_ECHO_DISABLE:            return "ECHO_DISABLE_FAILED";
        case PROV_FAIL_SIM_NOT_READY:           return "SIM_NOT_READY";
        case PROV_FAIL_BAND_CONFIG:             return "BAND_CONFIG_FAILED";
        case PROV_FAIL_MODEM_RESET:             return "MODEM_RESET_FAILED";
        case PROV_FAIL_REGISTRATION_TIMEOUT:    return "REGISTRATION_TIMEOUT";
        case PROV_FAIL_PS_ATTACH:               return "PS_ATTACH_FAILED";
        case PROV_FAIL_NETOPEN:                 return "NETOPEN_FAILED";
        case PROV_FAIL_NO_IP_ADDRESS:           return "NO_IP_ADDRESS";
        case PROV_FAIL_NVS_WRITE:               return "NVS_WRITE_FAILED";
        default:                                return "UNKNOWN_ERROR";
    }
}

/**
 * Print detailed diagnostics for troubleshooting
 */
static void printDiagnostics() {
    Serial.println();
    Serial.println("========================================");
    Serial.println("PROVISIONING DIAGNOSTICS");
    Serial.println("========================================");
    Serial.printf("Result: %s\n", getResultString(g_lastResult));
    Serial.printf("Failed Step: %s\n", g_failedStep);
    Serial.printf("Last AT Response: %s\n", g_lastAtResponse);
    Serial.println();
    Serial.println("Troubleshooting Steps:");

    switch (g_lastResult) {
        case PROV_FAIL_MODEM_NOT_RESPONDING:
            Serial.println("1. Check hardware connections (TX/RX wiring)");
            Serial.println("2. Verify modem power supply");
            Serial.println("3. Check baud rate (should be 115200)");
            Serial.println("4. Try power cycling the device");
            break;

        case PROV_FAIL_SIM_NOT_READY:
            Serial.println("1. Remove and reinsert SIM card");
            Serial.println("2. Verify SIM orientation (gold contacts up, cutaway out)");
            Serial.println("3. Check SIM is activated with carrier");
            Serial.println("4. Try a different SIM card");
            break;

        case PROV_FAIL_REGISTRATION_TIMEOUT:
            Serial.println("1. Check cellular antenna connection");
            Serial.println("2. Move to area with better signal");
            Serial.println("3. Verify SIM is activated for NB-IoT");
            Serial.println("4. Check carrier coverage map for NB-IoT");
            Serial.println("5. Try outdoor location near window");
            break;

        case PROV_FAIL_PS_ATTACH:
        case PROV_FAIL_NETOPEN:
        case PROV_FAIL_NO_IP_ADDRESS:
            Serial.println("1. SIM may not have data plan activated");
            Serial.println("2. APN configuration may be incorrect");
            Serial.println("3. Network may be congested, try again");
            Serial.println("4. Contact carrier support");
            break;

        default:
            Serial.println("1. Check serial output for specific error");
            Serial.println("2. Power cycle and retry");
            Serial.println("3. Check all hardware connections");
            break;
    }

    Serial.println();
    Serial.println("Press button on GPIO41 to retry provisioning");
    Serial.println("========================================");
    Serial.println();
}

// =============================================================================
// Main Setup and Loop
// =============================================================================

void setup() {
    // Initialize serial for debug output
    Serial.begin(115200);
    delay(1000);  // Wait for serial monitor to connect

    Serial.println();
    Serial.println("========================================");
    Serial.println("NB-IoT JAMBOX PROVISIONING FIRMWARE");
    Serial.println("Version 1.0.0");
    Serial.println("========================================");
    Serial.println();

    // Initialize button pin FIRST - check immediately for force re-provision
    pinMode(BUTTON_PIN, INPUT_PULLUP);
    delay(50);  // Brief settle time for pin

    // Check if button is held on boot to force re-provisioning
    // This check happens IMMEDIATELY before any other init
    bool forceReprovision = false;
    if (digitalRead(BUTTON_PIN) == LOW) {
        forceReprovision = true;
        Serial.println();
        Serial.println("========================================");
        Serial.println("BUTTON HELD - FORCE RE-PROVISIONING");
        Serial.println("========================================");

        // Clear the NVS flag immediately
        Preferences tempPrefs;
        if (tempPrefs.begin("jambox", false)) {
            tempPrefs.remove("cellular_ok");
            tempPrefs.end();
            Serial.println("[NVS] Flag cleared");
        }

        Serial.println("Release button to continue...");

        // Wait for button release
        while (digitalRead(BUTTON_PIN) == LOW) {
            delay(50);
        }
        delay(500);  // Debounce
        Serial.println();
    }

    // Initialize LED
    FastLED.addLeds<WS2812, LED_PIN, GRB>(g_leds, NUM_LEDS);
    FastLED.setBrightness(50);
    ledSetStatus(LED_STATUS_BOOTING);

    // Initialize modem serial
    Serial.println("[INIT] Initializing modem serial...");
    Serial.printf("  TX Pin: GPIO%d (ESP32 -> Modem)\n", MODEM_TX_PIN);
    Serial.printf("  RX Pin: GPIO%d (Modem -> ESP32)\n", MODEM_RX_PIN);
    Serial.printf("  Baud: %d\n", MODEM_BAUD);
    ModemSerial.begin(MODEM_BAUD, SERIAL_8N1, MODEM_RX_PIN, MODEM_TX_PIN);
    delay(1000);
    Serial.println("[INIT] Modem serial initialized");
    Serial.println();

    // Check if already provisioned (skip if force re-provision)
    if (!forceReprovision && checkAlreadyProvisioned()) {
        Serial.println("========================================");
        Serial.println("DEVICE ALREADY PROVISIONED");
        Serial.println("========================================");
        Serial.println("NVS flag 'cellular_ok' is already set.");
        Serial.println();
        Serial.println("To force re-provisioning:");
        Serial.println("  1. Hold the TOP BUTTON while resetting");
        Serial.println("  2. Or press SIDE BUTTON to reboot while holding TOP");
        Serial.println();
        Serial.println("Device is ready for production firmware.");
        Serial.println("========================================");
        Serial.println();

        ledSetStatus(LED_STATUS_SUCCESS);
        g_provisioningComplete = true;
        return;
    }

    // Run provisioning sequence
    Serial.println("[INIT] Starting cellular provisioning...");
    Serial.println();

    g_lastResult = runProvisioningSequence();

    if (g_lastResult == PROV_SUCCESS) {
        // Store success flag in NVS
        if (!storeProvisioningFlag()) {
            g_lastResult = PROV_FAIL_NVS_WRITE;
            strncpy(g_failedStep, "NVS write", sizeof(g_failedStep));
            Serial.println("[ERROR] Failed to store provisioning flag!");
            ledSetStatus(LED_STATUS_FAILURE);
            printDiagnostics();
            return;
        }

        // Success!
        Serial.println();
        Serial.println("========================================");
        Serial.println("PROVISIONING SUCCESSFUL");
        Serial.println("========================================");
        Serial.printf("IP Address: %s\n", g_ipAddress);
        Serial.println("NVS Flag: cellular_ok=1 stored");
        Serial.println();
        Serial.println("Device is ready for production firmware.");
        Serial.println("========================================");
        Serial.println();

        ledSetStatus(LED_STATUS_SUCCESS);
        g_provisioningComplete = true;
    } else {
        // Failure - show diagnostics
        ledSetStatus(LED_STATUS_FAILURE);
        printDiagnostics();
    }
}

void loop() {
    static uint32_t lastStatusPrint = 0;
    static bool buttonWasPressed = false;

    // Update LED animation
    ledUpdate();

    // Check for button press (retry on failure)
    bool buttonPressed = (digitalRead(BUTTON_PIN) == LOW);

    if (buttonPressed && !buttonWasPressed) {
        // Button just pressed
        if (!g_provisioningComplete) {
            Serial.println();
            Serial.println("[BUTTON] Retry requested...");
            Serial.println();

            // Reset state and retry
            ledSetStatus(LED_STATUS_BOOTING);
            delay(500);

            g_lastResult = runProvisioningSequence();

            if (g_lastResult == PROV_SUCCESS) {
                if (!storeProvisioningFlag()) {
                    g_lastResult = PROV_FAIL_NVS_WRITE;
                    strncpy(g_failedStep, "NVS write", sizeof(g_failedStep));
                    ledSetStatus(LED_STATUS_FAILURE);
                    printDiagnostics();
                } else {
                    Serial.println();
                    Serial.println("========================================");
                    Serial.println("PROVISIONING SUCCESSFUL (RETRY)");
                    Serial.println("========================================");
                    Serial.printf("IP Address: %s\n", g_ipAddress);
                    Serial.println("NVS Flag: cellular_ok=1 stored");
                    Serial.println();

                    ledSetStatus(LED_STATUS_SUCCESS);
                    g_provisioningComplete = true;
                }
            } else {
                ledSetStatus(LED_STATUS_FAILURE);
                printDiagnostics();
            }
        } else {
            Serial.println("[BUTTON] Device already provisioned successfully.");
        }
    }
    buttonWasPressed = buttonPressed;

    // Periodic status print
    if (g_provisioningComplete && (millis() - lastStatusPrint) >= STATUS_PRINT_INTERVAL) {
        lastStatusPrint = millis();
        Serial.println("Provisioning complete. Device ready for production firmware.");
    }

    // Print diagnostics periodically if failed
    if (!g_provisioningComplete && (millis() - lastStatusPrint) >= STATUS_PRINT_INTERVAL) {
        lastStatusPrint = millis();
        Serial.println("[STATUS] Provisioning FAILED - Press button to retry");
        Serial.printf("[STATUS] Last error: %s at step: %s\n",
                      getResultString(g_lastResult), g_failedStep);
    }

    delay(10);
}
