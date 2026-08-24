import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { DeviceGateway, DeviceGatewayError } = require('../src/devices/gateway.js');
const { ZKTecoAdapter, HikvisionAdapter, createZKTecoMock, createHikvisionMock } = require('../src/devices/adapters.js');

test('normalizes ZKTeco attendance without hardcoded network configuration', async () => {
  const gateway = new DeviceGateway();
  gateway.register(new ZKTecoAdapter({
    client: createZKTecoMock([{ id: 10, userId: 42, timestamp: '2026-08-24T14:00:00-05:00', verification: 'face', state: 'check-in' }]),
    deviceId: 'zk-frontdesk', tenantId: 'tenant-femar', siteId: 'hq'
  }));
  const [event] = await gateway.collect({ tenantId: 'tenant-femar', deviceId: 'zk-frontdesk' });
  assert.equal(event.schema, 'inneros.device_event.v1');
  assert.equal(event.vendor, 'zkteco');
  assert.equal(event.subjectId, '42');
  assert.equal(event.type, 'attendance.mark');
  assert.equal(event.tenantId, 'tenant-femar');
  assert.equal(event.payload.verification, 'face');
});

test('normalizes Hikvision access events', async () => {
  const gateway = new DeviceGateway();
  gateway.register(new HikvisionAdapter({
    client: createHikvisionMock([{ id: 'evt-1', personId: 'p-9', timestamp: '2026-08-24T19:00:00Z', door: 'north', direction: 'in', granted: true }]),
    deviceId: 'hik-north', tenantId: 'tenant-a'
  }));
  const [event] = await gateway.collect({ tenantId: 'tenant-a', deviceId: 'hik-north' });
  assert.equal(event.vendor, 'hikvision');
  assert.equal(event.type, 'access.event');
  assert.equal(event.payload.granted, true);
  assert.equal(event.payload.door, 'north');
});

test('same device id can exist in separate tenants without collision', async () => {
  const gateway = new DeviceGateway();
  gateway.register(new ZKTecoAdapter({ client: createZKTecoMock([]), deviceId: 'device-1', tenantId: 'tenant-a' }));
  gateway.register(new ZKTecoAdapter({ client: createZKTecoMock([]), deviceId: 'device-1', tenantId: 'tenant-b' }));
  assert.equal(gateway.get({ tenantId: 'tenant-a', deviceId: 'device-1' }).tenantId, 'tenant-a');
  assert.equal(gateway.get({ tenantId: 'tenant-b', deviceId: 'device-1' }).tenantId, 'tenant-b');
});

test('rejects missing injected vendor clients', () => {
  assert.throws(() => new ZKTecoAdapter({ deviceId: 'x', tenantId: 't' }), (e) => e instanceof DeviceGatewayError && e.code === 'zkteco_client_required');
  assert.throws(() => new HikvisionAdapter({ deviceId: 'x', tenantId: 't' }), (e) => e instanceof DeviceGatewayError && e.code === 'hikvision_client_required');
});

test('rejects invalid timestamps and unknown device lookups', async () => {
  const gateway = new DeviceGateway();
  gateway.register(new ZKTecoAdapter({ client: createZKTecoMock([{ userId: 1, timestamp: 'not-a-date' }]), deviceId: 'zk', tenantId: 'tenant' }));
  await assert.rejects(gateway.collect({ tenantId: 'tenant', deviceId: 'zk' }), (e) => e.code === 'invalid_timestamp');
  assert.throws(() => gateway.get({ tenantId: 'other', deviceId: 'zk' }), (e) => e.code === 'adapter_not_found');
});
