import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const {
  getAllModules,
  getEnabledModulesForTenant,
  isModuleEnabledForTenant,
  resolveModuleAccess
} = require('../src/moduleCatalog.js');

test('owner tenant receives all catalog modules', () => {
  const all = getAllModules();
  const enabled = getEnabledModulesForTenant('inneros-owner');
  assert.equal(enabled.length, all.length);
  assert.ok(enabled.some((module) => module.id === 'workforce'));
  assert.ok(enabled.some((module) => module.id === 'settings'));
});

test('Servifran receives only Workforce entitlement', () => {
  const enabled = getEnabledModulesForTenant('servifran');
  assert.deepEqual(enabled.map((module) => module.id), ['workforce']);
  assert.equal(isModuleEnabledForTenant('servifran', 'workforce'), true);
  assert.equal(isModuleEnabledForTenant('servifran', 'settings'), false);
});

test('unknown tenant receives no modules', () => {
  assert.deepEqual(getEnabledModulesForTenant('not-a-tenant'), []);
});

test('module access requires authenticated tenant', () => {
  const result = resolveModuleAccess({ requestedModule: 'workforce' });
  assert.equal(result.authorized, false);
  assert.equal(result.reason, 'authenticated_tenant_required');
});

test('module access rejects unknown modules', () => {
  const result = resolveModuleAccess({ sessionTenantId: 'inneros-owner', requestedModule: 'imaginary' });
  assert.equal(result.authorized, false);
  assert.equal(result.reason, 'unknown_module');
});

test('module access enforces tenant entitlement server-side', () => {
  const allowed = resolveModuleAccess({ sessionTenantId: 'servifran', requestedModule: 'workforce' });
  assert.equal(allowed.authorized, true);

  const denied = resolveModuleAccess({ sessionTenantId: 'servifran', requestedModule: 'audit' });
  assert.equal(denied.authorized, false);
  assert.equal(denied.reason, 'module_not_entitled');
});
