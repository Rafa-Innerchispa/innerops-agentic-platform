'use strict';

const { DeviceAdapter, DeviceGatewayError } = require('./gateway.js');

class ZKTecoAdapter extends DeviceAdapter {
  constructor({ client, deviceId, tenantId, siteId = null } = {}) {
    super({ vendor: 'zkteco', deviceId, tenantId, siteId });
    if (!client || typeof client.readAttendance !== 'function') {
      throw new DeviceGatewayError('zkteco_client_required', 'ZKTeco adapter requires an injected readAttendance client');
    }
    this.client = client;
  }

  async readEvents({ cursor = null } = {}) {
    const rows = await this.client.readAttendance({ cursor });
    if (!Array.isArray(rows)) throw new DeviceGatewayError('invalid_zkteco_response', 'ZKTeco client must return an array');
    return rows.map((row) => ({
      type: 'attendance.mark',
      subjectId: String(row.userId ?? row.employeeId ?? ''),
      occurredAt: row.timestamp,
      sourceId: row.id ? String(row.id) : null,
      payload: {
        verification: row.verification ?? null,
        state: row.state ?? null,
      },
    }));
  }
}

class HikvisionAdapter extends DeviceAdapter {
  constructor({ client, deviceId, tenantId, siteId = null } = {}) {
    super({ vendor: 'hikvision', deviceId, tenantId, siteId });
    if (!client || typeof client.readEvents !== 'function') {
      throw new DeviceGatewayError('hikvision_client_required', 'Hikvision adapter requires an injected readEvents client');
    }
    this.client = client;
  }

  async readEvents({ cursor = null } = {}) {
    const rows = await this.client.readEvents({ cursor });
    if (!Array.isArray(rows)) throw new DeviceGatewayError('invalid_hikvision_response', 'Hikvision client must return an array');
    return rows.map((row) => ({
      type: row.type || 'access.event',
      subjectId: row.personId ? String(row.personId) : null,
      occurredAt: row.timestamp,
      sourceId: row.id ? String(row.id) : null,
      payload: {
        door: row.door ?? null,
        direction: row.direction ?? null,
        granted: row.granted ?? null,
      },
    }));
  }
}

function createZKTecoMock(events = []) {
  return { readAttendance: async () => events.map((event) => ({ ...event })) };
}

function createHikvisionMock(events = []) {
  return { readEvents: async () => events.map((event) => ({ ...event })) };
}

module.exports = { ZKTecoAdapter, HikvisionAdapter, createZKTecoMock, createHikvisionMock };
