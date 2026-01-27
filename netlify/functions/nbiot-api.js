/**
 * NB-IoT Device Management API v1.1.0
 * Standalone admin portal for NB-IoT JamBox fleet management.
 *
 * Endpoints:
 * - GET  /nbiot-api/devices         List all devices
 * - GET  /nbiot-api/device/:id      Get single device + readings
 * - GET  /nbiot-api/readings        Get readings (query: device_id, limit, days)
 * - GET  /nbiot-api/stats           Fleet statistics with Apple/Android breakdown
 * - GET  /nbiot-api/hourly          Hourly aggregated data (query: device_id, days)
 * - POST /nbiot-api/device/register Register new device (proxy to Linode)
 * - POST /nbiot-api/device/:id/regenerate  Regenerate token (proxy to Linode)
 */

const https = require('https');
const http = require('http');

// Supabase configuration
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_KEY;

// Linode NB-IoT backend configuration
const NBIOT_LINODE_URL = process.env.NBIOT_LINODE_URL || 'http://172.233.144.32:5000';
const NBIOT_ADMIN_KEY = process.env.NBIOT_ADMIN_KEY;

// Device status thresholds (in hours)
const STATUS_THRESHOLDS = {
  ONLINE: 24,
  WARNING: 48
};

/**
 * Get CORS headers
 */
function getCorsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    'Content-Type': 'application/json'
  };
}

/**
 * Query Supabase
 */
async function supabaseQuery(method, endpoint, body = null) {
  const url = new URL(`${SUPABASE_URL}/rest/v1/${endpoint}`);

  return new Promise((resolve, reject) => {
    const options = {
      hostname: url.hostname,
      path: url.pathname + url.search,
      method: method,
      headers: {
        'apikey': SUPABASE_KEY,
        'Authorization': `Bearer ${SUPABASE_KEY}`,
        'Content-Type': 'application/json',
        'Prefer': method === 'POST' ? 'return=representation' : 'return=minimal'
      }
    };

    if (method === 'GET' || method === 'DELETE') {
      delete options.headers['Prefer'];
    }

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const result = data ? JSON.parse(data) : null;
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(result);
          } else {
            reject(new Error(result?.message || `Supabase error: ${res.statusCode}`));
          }
        } catch (e) {
          resolve(data);
        }
      });
    });

    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

/**
 * Proxy request to Linode NB-IoT backend
 */
async function linodeRequest(method, path, body = null) {
  const url = new URL(path, NBIOT_LINODE_URL);
  const isHttps = url.protocol === 'https:';
  const httpModule = isHttps ? https : http;

  return new Promise((resolve, reject) => {
    const options = {
      hostname: url.hostname,
      port: url.port || (isHttps ? 443 : 80),
      path: url.pathname,
      method: method,
      headers: {
        'Authorization': `Bearer ${NBIOT_ADMIN_KEY}`,
        'Content-Type': 'application/json'
      },
      timeout: 10000
    };

    const req = httpModule.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const result = data ? JSON.parse(data) : null;
          resolve({ statusCode: res.statusCode, data: result });
        } catch (e) {
          resolve({ statusCode: res.statusCode, data: data });
        }
      });
    });

    req.on('error', (e) => reject(new Error(`Linode request failed: ${e.message}`)));
    req.on('timeout', () => { req.destroy(); reject(new Error('Linode request timeout')); });
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

/**
 * Calculate device status based on last_seen_at
 */
function calculateDeviceStatus(lastSeenAt) {
  if (!lastSeenAt) return 'unknown';

  const lastSeen = new Date(lastSeenAt);
  const now = new Date();
  const hoursAgo = (now - lastSeen) / (1000 * 60 * 60);

  if (hoursAgo <= STATUS_THRESHOLDS.ONLINE) return 'online';
  if (hoursAgo <= STATUS_THRESHOLDS.WARNING) return 'warning';
  return 'offline';
}

/**
 * Format device for API response
 */
function formatDevice(device) {
  return {
    ...device,
    connection_status: calculateDeviceStatus(device.last_seen_at),
    last_seen_ago: device.last_seen_at ? formatTimeAgo(device.last_seen_at) : 'Never'
  };
}

/**
 * Format time ago string
 */
function formatTimeAgo(timestamp) {
  const now = new Date();
  const then = new Date(timestamp);
  const seconds = Math.floor((now - then) / 1000);

  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hours ago`;
  return `${Math.floor(seconds / 86400)} days ago`;
}

/**
 * Main handler
 */
exports.handler = async (event) => {
  const headers = getCorsHeaders();

  // Handle CORS preflight
  if (event.httpMethod === 'OPTIONS') {
    return { statusCode: 204, headers, body: '' };
  }

  // Check Supabase config
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    console.error('[NBIOT-API] Missing Supabase configuration');
    return {
      statusCode: 500,
      headers,
      body: JSON.stringify({ error: 'Server configuration error: Missing Supabase config' })
    };
  }

  const path = event.path.replace('/.netlify/functions/nbiot-api', '').replace(/^\/+/, '');
  const segments = path.split('/').filter(Boolean);
  const method = event.httpMethod;
  const query = event.queryStringParameters || {};

  console.log(`[NBIOT-API] ${method} /${segments.join('/')}`);

  try {
    // =====================
    // GET /devices - List all devices
    // =====================
    if (method === 'GET' && (segments[0] === 'devices' || segments.length === 0)) {
      const devices = await supabaseQuery('GET', 'nbiot_devices?order=device_id');
      const formatted = (devices || []).map(formatDevice);

      const stats = {
        total: formatted.length,
        online: formatted.filter(d => d.connection_status === 'online').length,
        warning: formatted.filter(d => d.connection_status === 'warning').length,
        offline: formatted.filter(d => d.connection_status === 'offline').length
      };

      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({ devices: formatted, stats })
      };
    }

    // =====================
    // GET /device/:id - Get single device
    // =====================
    if (method === 'GET' && segments[0] === 'device' && segments[1] && !segments[2]) {
      const deviceId = segments[1].toUpperCase();
      const results = await supabaseQuery('GET', `nbiot_devices?device_id=eq.${deviceId}`);

      if (!results || results.length === 0) {
        return { statusCode: 404, headers, body: JSON.stringify({ error: 'Device not found' }) };
      }

      const device = formatDevice(results[0]);

      // Get recent readings
      const readings = await supabaseQuery('GET',
        `nbiot_readings?device_id=eq.${deviceId}&order=timestamp.desc&limit=20`
      );

      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({ device, recent_readings: readings || [] })
      };
    }

    // =====================
    // GET /readings - Get readings
    // =====================
    if (method === 'GET' && segments[0] === 'readings') {
      let queryStr = 'nbiot_readings?order=timestamp.desc';

      if (query.device_id) {
        const sanitizedId = query.device_id.toUpperCase();
        if (!/^JBNB\d{4}$/.test(sanitizedId)) {
          return { statusCode: 400, headers, body: JSON.stringify({ error: 'Invalid device_id format' }) };
        }
        queryStr += `&device_id=eq.${sanitizedId}`;
      }

      const limit = Math.min(parseInt(query.limit, 10) || 100, 1000);
      queryStr += `&limit=${limit}`;

      if (query.days) {
        const days = parseInt(query.days, 10);
        if (!isNaN(days) && days > 0 && days <= 365) {
          const daysAgo = new Date();
          daysAgo.setDate(daysAgo.getDate() - days);
          queryStr += `&timestamp=gte.${daysAgo.toISOString()}`;
        }
      }

      const readings = await supabaseQuery('GET', queryStr);
      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({
          readings: readings || [],
          count: (readings || []).length
        })
      };
    }

    // =====================
    // GET /stats - Fleet statistics
    // =====================
    if (method === 'GET' && segments[0] === 'stats') {
      const devices = await supabaseQuery('GET', 'nbiot_devices?order=device_id');
      const formatted = (devices || []).map(formatDevice);

      // Get today's readings with all metrics including dwell time and RSSI zones
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const todayStats = await supabaseQuery('GET',
        `nbiot_readings?timestamp=gte.${today.toISOString()}&select=impressions,unique_count,apple_count,android_count,signal_dbm,dwell_0_1,dwell_1_5,dwell_5_10,dwell_10plus,rssi_immediate,rssi_near,rssi_far,rssi_remote`
      );

      const totalImpressions = (todayStats || []).reduce((sum, r) => sum + (r.impressions || 0), 0);
      const totalUnique = (todayStats || []).reduce((sum, r) => sum + (r.unique_count || 0), 0);
      const totalApple = (todayStats || []).reduce((sum, r) => sum + (r.apple_count || 0), 0);
      const totalAndroid = (todayStats || []).reduce((sum, r) => sum + (r.android_count || 0), 0);
      const avgSignal = todayStats && todayStats.length > 0
        ? Math.round(todayStats.reduce((sum, r) => sum + (r.signal_dbm || 0), 0) / todayStats.length)
        : null;

      // Dwell time aggregates
      const dwell0_1 = (todayStats || []).reduce((sum, r) => sum + (r.dwell_0_1 || 0), 0);
      const dwell1_5 = (todayStats || []).reduce((sum, r) => sum + (r.dwell_1_5 || 0), 0);
      const dwell5_10 = (todayStats || []).reduce((sum, r) => sum + (r.dwell_5_10 || 0), 0);
      const dwell10plus = (todayStats || []).reduce((sum, r) => sum + (r.dwell_10plus || 0), 0);

      // RSSI zone aggregates
      const rssiImmediate = (todayStats || []).reduce((sum, r) => sum + (r.rssi_immediate || 0), 0);
      const rssiNear = (todayStats || []).reduce((sum, r) => sum + (r.rssi_near || 0), 0);
      const rssiFar = (todayStats || []).reduce((sum, r) => sum + (r.rssi_far || 0), 0);
      const rssiRemote = (todayStats || []).reduce((sum, r) => sum + (r.rssi_remote || 0), 0);

      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({
          fleet: {
            total: formatted.length,
            online: formatted.filter(d => d.connection_status === 'online').length,
            warning: formatted.filter(d => d.connection_status === 'warning').length,
            offline: formatted.filter(d => d.connection_status === 'offline').length
          },
          today: {
            readings_count: (todayStats || []).length,
            total_impressions: totalImpressions,
            total_unique: totalUnique,
            total_apple: totalApple,
            total_android: totalAndroid,
            avg_signal: avgSignal,
            // Dwell time buckets
            dwell_0_1: dwell0_1,
            dwell_1_5: dwell1_5,
            dwell_5_10: dwell5_10,
            dwell_10plus: dwell10plus,
            // RSSI distance zones
            rssi_immediate: rssiImmediate,
            rssi_near: rssiNear,
            rssi_far: rssiFar,
            rssi_remote: rssiRemote
          },
          devices: formatted.map(d => ({
            device_id: d.device_id,
            status: d.connection_status,
            last_seen: d.last_seen_ago,
            signal: d.last_signal_dbm
          }))
        })
      };
    }

    // =====================
    // GET /hourly - Hourly aggregated data
    // =====================
    if (method === 'GET' && segments[0] === 'hourly') {
      const days = Math.min(parseInt(query.days, 10) || 7, 30);
      const startDate = new Date();
      startDate.setDate(startDate.getDate() - days);
      startDate.setHours(0, 0, 0, 0);

      let queryStr = `nbiot_readings?timestamp=gte.${startDate.toISOString()}&order=timestamp.asc`;

      if (query.device_id) {
        const sanitizedId = query.device_id.toUpperCase();
        if (!/^JBNB\d{4}$/.test(sanitizedId)) {
          return { statusCode: 400, headers, body: JSON.stringify({ error: 'Invalid device_id format' }) };
        }
        queryStr += `&device_id=eq.${sanitizedId}`;
      }

      const readings = await supabaseQuery('GET', queryStr);

      // Aggregate by hour
      const hourlyMap = {};
      (readings || []).forEach(r => {
        const date = new Date(r.timestamp);
        const hourKey = `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')} ${String(date.getHours()).padStart(2,'0')}:00`;

        if (!hourlyMap[hourKey]) {
          hourlyMap[hourKey] = {
            hour: hourKey,
            impressions: 0,
            unique_count: 0,
            apple_count: 0,
            android_count: 0,
            readings: 0,
            avg_signal: []
          };
        }
        hourlyMap[hourKey].impressions += r.impressions || 0;
        hourlyMap[hourKey].unique_count += r.unique_count || 0;
        hourlyMap[hourKey].apple_count += r.apple_count || 0;
        hourlyMap[hourKey].android_count += r.android_count || 0;
        hourlyMap[hourKey].readings += 1;
        if (r.signal_dbm) hourlyMap[hourKey].avg_signal.push(r.signal_dbm);
      });

      // Convert to array and calculate avg signal
      const hourly = Object.values(hourlyMap).map(h => ({
        ...h,
        avg_signal: h.avg_signal.length > 0
          ? Math.round(h.avg_signal.reduce((a,b) => a+b, 0) / h.avg_signal.length)
          : null
      }));

      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({
          hourly,
          period: { start: startDate.toISOString(), days },
          totals: {
            impressions: hourly.reduce((s, h) => s + h.impressions, 0),
            unique_count: hourly.reduce((s, h) => s + h.unique_count, 0),
            apple_count: hourly.reduce((s, h) => s + h.apple_count, 0),
            android_count: hourly.reduce((s, h) => s + h.android_count, 0)
          }
        })
      };
    }

    // =====================
    // POST /device/register - Register new device
    // =====================
    if (method === 'POST' && segments[0] === 'device' && segments[1] === 'register') {
      if (!NBIOT_ADMIN_KEY) {
        return { statusCode: 500, headers, body: JSON.stringify({ error: 'Linode admin key not configured' }) };
      }

      const body = JSON.parse(event.body || '{}');

      if (!body.device_id || !/^JBNB\d{4}$/.test(body.device_id.toUpperCase())) {
        return { statusCode: 400, headers, body: JSON.stringify({ error: 'Invalid device_id format (JBNB####)' }) };
      }

      const response = await linodeRequest('POST', '/api/device/register', {
        device_id: body.device_id.toUpperCase(),
        project_name: body.project_name || null,
        location_name: body.location_name || null,
        timezone: body.timezone || 'UTC'
      });

      if (response.statusCode === 201 || response.statusCode === 200) {
        return {
          statusCode: 201,
          headers,
          body: JSON.stringify({
            success: true,
            device_id: body.device_id.toUpperCase(),
            token: response.data.token,
            message: 'Device registered. Save this token - shown only once.'
          })
        };
      } else {
        return {
          statusCode: response.statusCode,
          headers,
          body: JSON.stringify({ error: response.data?.error || 'Registration failed' })
        };
      }
    }

    // =====================
    // POST /device/:id/regenerate - Regenerate token
    // =====================
    if (method === 'POST' && segments[0] === 'device' && segments[1] && segments[2] === 'regenerate') {
      if (!NBIOT_ADMIN_KEY) {
        return { statusCode: 500, headers, body: JSON.stringify({ error: 'Linode admin key not configured' }) };
      }

      const deviceId = segments[1].toUpperCase();
      const response = await linodeRequest('POST', `/api/device/${deviceId}/regenerate-token`);

      if (response.statusCode === 200) {
        return {
          statusCode: 200,
          headers,
          body: JSON.stringify({
            success: true,
            device_id: deviceId,
            token: response.data.token,
            message: 'Token regenerated. Old token is now invalid.'
          })
        };
      } else {
        return {
          statusCode: response.statusCode,
          headers,
          body: JSON.stringify({ error: response.data?.error || 'Token regeneration failed' })
        };
      }
    }

    // =====================
    // Unknown route
    // =====================
    return {
      statusCode: 404,
      headers,
      body: JSON.stringify({
        error: 'Not found',
        available: ['GET /devices', 'GET /device/:id', 'GET /readings', 'GET /stats', 'GET /hourly', 'POST /device/register', 'POST /device/:id/regenerate']
      })
    };

  } catch (error) {
    console.error('[NBIOT-API] Error:', error);
    return {
      statusCode: 500,
      headers,
      body: JSON.stringify({ error: error.message || 'Internal server error' })
    };
  }
};
