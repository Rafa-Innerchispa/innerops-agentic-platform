'use strict';

class DeviceGatewayError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = 'DeviceGatewayError';
    this.code = code;
    this.details = details;
  }
}

function asIsoTimestamp(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) throw new DeviceGatewayError('invalid_timestamp', 'Device event timestamp is invalid');
  return date.toISOString();
}

function normalizeDeviceEvent({ vendor, deviceId, tenantId, siteId = null, type, subjectId = null, occurredAt, payload = {}, sourceId = null }) {
  if (!vendor) throw new DeviceGatewayError('vendor_required', 'Vendor is required');
  if (!deviceId) throw new DeviceGatewayError('device_id_required', 'Device id is required');
  if (!tenantId) throw new DeviceGatewayError('tenant_id_required', 'Tenant id is required');
  if (!type) throw new DeviceGatewayError('event_type_required', 'Event type is required');
  const timestamp = asIsoTimestamp(occurredAt);
  return {
    schema: 'inneros.device_event.v1',
    vendor,
    deviceId,
    tenantId,
    siteId,
    type,
    subjectId,
    occurredAt: timestamp,
    sourceId,
    payload: { ...payload },
  };
}

class DeviceAdapter {
  constructor({ vendor, deviceId, tenantId, siteId = null } = {}) {
    if (!vendor || !deviceId || !tenantId) throw new DeviceGatewayError('adapter_identity_required', 'vendor, deviceId and tenantId are required');
    this.vendor = vendor;
    this.deviceId = deviceId;
    this.tenantId = tenantId;
    this.siteId = siteId;
  }

  normalize(raw) {
    return normalizeDeviceEvent({
      vendor: this.vendor,
      deviceId: this.deviceId,
      tenantId: this.tenantId,
      siteId: this.siteId,
      ...raw,
    });
  }

  async health() { return { ok: true, vendor: this.vendor, deviceId: this.deviceId }; }
  async readEvents() { throw new DeviceGatewayError('read_not_implemented', `${this.vendor} adapter does not implement readEvents`); }
}

class DeviceGateway {
  constructor() { this.adapters = new Map(); }

  register(adapter) {
    if (!(adapter instanceof DeviceAdapter)) throw new DeviceGatewayError('invalid_adapter', 'Adapter must extend DeviceAdapter');
    const key = `${adapter.tenantId}:${adapter.deviceId}`;
    if (this.adapters.has(key)) throw new DeviceGatewayError('adapter_already_registered', 'Device adapter already registered', { key });
    this.adapters.set(key, adapter);
    return key;
  }

  get({ tenantId, deviceId }) {
    const adapter = this.adapters.get(`${tenantId}:${deviceId}`);
    if (!adapter) throw new DeviceGatewayError('adapter_not_found', 'Device adapter not found');
    return adapter;
  }

  async collect({ tenantId, deviceId, cursor = null } = {}) {
    const adapter = this.get({ tenantId, deviceId });
    const result = await adapter.readEvents({ cursor });
    const events = Array.isArray(result) ? result : result?.events || [];
    return events.map((event) => adapter.normalize(event));
  }
}

module.exports = { DeviceGatewayError, DeviceAdapter, DeviceGateway, normalizeDeviceEvent };
