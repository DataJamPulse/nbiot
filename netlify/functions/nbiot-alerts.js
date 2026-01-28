/**
 * NB-IoT Offline Alert System
 *
 * Scheduled function (runs hourly via Netlify)
 * Sends email alerts when devices go offline for 24+ hours
 *
 * To enable: Add to netlify.toml:
 * [functions."nbiot-alerts"]
 *   schedule = "@hourly"
 */

const https = require('https');

// Configuration
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_KEY;
const RESEND_API_KEY = process.env.RESEND_API_KEY;
const ALERT_EMAIL = process.env.ALERT_EMAIL || 'hello@data-jam.com';

// Offline threshold in hours
const OFFLINE_THRESHOLD_HOURS = 24;

/**
 * Query Supabase
 */
async function supabaseQuery(endpoint) {
    const url = new URL(`${SUPABASE_URL}/rest/v1/${endpoint}`);

    return new Promise((resolve, reject) => {
        const options = {
            hostname: url.hostname,
            path: url.pathname + url.search,
            method: 'GET',
            headers: {
                'apikey': SUPABASE_KEY,
                'Authorization': `Bearer ${SUPABASE_KEY}`,
                'Content-Type': 'application/json'
            }
        };

        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try {
                    resolve(JSON.parse(data));
                } catch (e) {
                    reject(new Error('Failed to parse Supabase response'));
                }
            });
        });

        req.on('error', reject);
        req.end();
    });
}

/**
 * Insert alert record to Supabase
 */
async function insertAlert(deviceId, alertType, message, severity = 'warning') {
    const url = new URL(`${SUPABASE_URL}/rest/v1/nbiot_alerts`);

    const body = JSON.stringify({
        device_id: deviceId,
        alert_type: alertType,
        message: message,
        severity: severity
    });

    return new Promise((resolve, reject) => {
        const options = {
            hostname: url.hostname,
            path: url.pathname,
            method: 'POST',
            headers: {
                'apikey': SUPABASE_KEY,
                'Authorization': `Bearer ${SUPABASE_KEY}`,
                'Content-Type': 'application/json',
                'Prefer': 'return=minimal'
            }
        };

        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => resolve(res.statusCode));
        });

        req.on('error', reject);
        req.write(body);
        req.end();
    });
}

/**
 * Check if we already sent an alert for this device recently (prevent spam)
 */
async function hasRecentAlert(deviceId, alertType, hoursAgo = 24) {
    const since = new Date();
    since.setHours(since.getHours() - hoursAgo);

    const alerts = await supabaseQuery(
        `nbiot_alerts?device_id=eq.${deviceId}&alert_type=eq.${alertType}&created_at=gte.${since.toISOString()}&limit=1`
    );

    return alerts && alerts.length > 0;
}

/**
 * Send email via Resend
 */
async function sendEmail(to, subject, html) {
    if (!RESEND_API_KEY) {
        console.log('[ALERT] No RESEND_API_KEY configured, skipping email');
        return false;
    }

    return new Promise((resolve, reject) => {
        const body = JSON.stringify({
            from: 'DataJam Alerts <alerts@data-jam.com>',
            to: [to],
            subject: subject,
            html: html
        });

        const options = {
            hostname: 'api.resend.com',
            path: '/emails',
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${RESEND_API_KEY}`,
                'Content-Type': 'application/json'
            }
        };

        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                if (res.statusCode === 200 || res.statusCode === 201) {
                    console.log('[ALERT] Email sent successfully');
                    resolve(true);
                } else {
                    console.log(`[ALERT] Email failed: ${res.statusCode} ${data}`);
                    resolve(false);
                }
            });
        });

        req.on('error', (e) => {
            console.log(`[ALERT] Email error: ${e.message}`);
            resolve(false);
        });

        req.write(body);
        req.end();
    });
}

/**
 * Format time ago
 */
function formatTimeAgo(timestamp) {
    const now = new Date();
    const then = new Date(timestamp);
    const hours = Math.floor((now - then) / (1000 * 60 * 60));

    if (hours < 24) return `${hours} hours ago`;
    const days = Math.floor(hours / 24);
    return `${days} day${days > 1 ? 's' : ''} ago`;
}

/**
 * Main handler
 */
exports.handler = async (event) => {
    console.log('[ALERT] Running offline device check...');

    if (!SUPABASE_URL || !SUPABASE_KEY) {
        console.error('[ALERT] Missing Supabase configuration');
        return { statusCode: 500, body: 'Missing configuration' };
    }

    try {
        // Get all active devices
        const devices = await supabaseQuery('nbiot_devices?status=eq.active');

        if (!devices || devices.length === 0) {
            console.log('[ALERT] No active devices found');
            return { statusCode: 200, body: JSON.stringify({ checked: 0, alerts: 0 }) };
        }

        const threshold = new Date();
        threshold.setHours(threshold.getHours() - OFFLINE_THRESHOLD_HOURS);

        let alertsSent = 0;
        const offlineDevices = [];

        for (const device of devices) {
            const lastSeen = device.last_seen_at ? new Date(device.last_seen_at) : null;

            // Check if device is offline (no data in 24 hours)
            if (!lastSeen || lastSeen < threshold) {
                console.log(`[ALERT] Device ${device.device_id} offline since ${lastSeen ? lastSeen.toISOString() : 'never'}`);

                // Check if we already alerted about this device recently
                const alreadyAlerted = await hasRecentAlert(device.device_id, 'offline', 24);

                if (!alreadyAlerted) {
                    // Record the alert
                    const message = `Device ${device.device_id} (${device.location_name || 'Unknown location'}) has been offline for ${lastSeen ? formatTimeAgo(lastSeen) : 'unknown time'}`;

                    await insertAlert(device.device_id, 'offline', message, 'warning');

                    offlineDevices.push({
                        device_id: device.device_id,
                        location: device.location_name || 'Unknown',
                        last_seen: lastSeen ? formatTimeAgo(lastSeen) : 'Never'
                    });

                    alertsSent++;
                } else {
                    console.log(`[ALERT] Already alerted about ${device.device_id} in last 24h, skipping`);
                }
            }
        }

        // Send consolidated email if any devices are offline
        if (offlineDevices.length > 0 && ALERT_EMAIL) {
            const subject = `⚠️ ${offlineDevices.length} DataJam sensor${offlineDevices.length > 1 ? 's' : ''} offline`;

            const html = `
                <div style="font-family: 'Poppins', Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #0A0C11; color: #FEFAF9; padding: 32px; border-radius: 16px;">
                    <h1 style="color: #E62F6E; margin-bottom: 24px;">Sensor Alert</h1>
                    <p style="color: #9A9896; margin-bottom: 24px;">
                        The following sensor${offlineDevices.length > 1 ? 's have' : ' has'} been offline for more than 24 hours:
                    </p>
                    <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
                        <thead>
                            <tr style="border-bottom: 1px solid #1A1D24;">
                                <th style="text-align: left; padding: 12px; color: #5A5856;">Device</th>
                                <th style="text-align: left; padding: 12px; color: #5A5856;">Location</th>
                                <th style="text-align: left; padding: 12px; color: #5A5856;">Last Seen</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${offlineDevices.map(d => `
                                <tr style="border-bottom: 1px solid #1A1D24;">
                                    <td style="padding: 12px; color: #E62F6E;">${d.device_id}</td>
                                    <td style="padding: 12px;">${d.location}</td>
                                    <td style="padding: 12px; color: #E94B52;">${d.last_seen}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                    <p style="color: #5A5856; font-size: 12px;">
                        Check your sensors at <a href="https://nbiot.netlify.app/fleet.html" style="color: #15E0BC;">nbiot.netlify.app</a>
                    </p>
                </div>
            `;

            await sendEmail(ALERT_EMAIL, subject, html);
        }

        console.log(`[ALERT] Check complete. Devices: ${devices.length}, Alerts: ${alertsSent}`);

        return {
            statusCode: 200,
            body: JSON.stringify({
                checked: devices.length,
                offline: offlineDevices.length,
                alerts_sent: alertsSent
            })
        };

    } catch (error) {
        console.error('[ALERT] Error:', error);
        return {
            statusCode: 500,
            body: JSON.stringify({ error: error.message })
        };
    }
};
