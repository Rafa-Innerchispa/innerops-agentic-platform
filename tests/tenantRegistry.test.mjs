import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const {
  normalizeDomain,
  getTenantByDomain,
  getTenantById,
  getAllTenants,
  resolveRequestContext
} = require('../src/tenantRegistry.js');

test('maps app.creatoros.dev to InnerOS owner tenant', () => {
  const tenant = getTenantByDomain('app.creatoros.dev');
  assert.equal(tenant.id, 'inneros-owner');
  assert.equal(tenant.app, 'InnerOS');
  assert.ok(tenant.entitlements.includes('overview'));
});

test('maps servifran.site to Servifran', () => {
  const tenant = getTenantByDomain('servifran.site');
  assert.equal(tenant.id, 'servifran');
  assert.equal(tenant.module, 'workforce');
});

test('maps workforce.servifran.site to same Servifran tenant', () => {
  const tenant = getTenantByDomain('workforce.servifran.site');
  assert.equal(tenant.id, 'servifran');
  assert.equal(tenant.domain, 'workforce.servifran.site');
});

test('normalizes URL-like domain input', () => {
  assert.equal(normalizeDomain('HTTPS://APP.CREATOROS.DEV:443/path'), 'app.creatoros.dev');
});

test('unknown domain does not resolve a tenant', () => {
  assert.equal(getTenantByDomain('unknown.example.com'), null);
});

test('tenant lookup by id returns an isolated copy', () => {
  const first = getTenantById('servifran');
  first.entitlements.push('settings');
  const second = getTenantById('servifran');
  assert.deepEqual(second.entitlements, ['workforce']);
});

test('registry contains canonical tenant records without duplicate Servifran tenant', () => {
  const tenants = getAllTenants();
  assert.equal(tenants.length, 2);
  assert.equal(tenants.filter((tenant) => tenant.id === 'servifran').length, 1);
});

test('domain mapping never grants authorization without authenticated tenant context', () => {
  const context = resolveRequestContext({
    domain: 'app.creatoros.dev',
    requestedModule: 'overview'
  });
  assert.equal(context.authorized, false);
  assert.equal(context.reason, 'authenticated_tenant_required');
  assert.equal(context.domainTenant.id, 'inneros-owner');
});

test('authenticated tenant entitlement controls module access', () => {
  const allowed = resolveRequestContext({
    domain: 'workforce.servifran.site',
    sessionTenantId: 'servifran',
    requestedModule: 'workforce'
  });
  assert.equal(allowed.authorized, true);
  assert.equal(allowed.tenant.id, 'servifran');

  const denied = resolveRequestContext({
    domain: 'workforce.servifran.site',
    sessionTenantId: 'servifran',
    requestedModule: 'settings'
  });
  assert.equal(denied.authorized, false);
  assert.equal(denied.reason, 'module_not_entitled');
});
