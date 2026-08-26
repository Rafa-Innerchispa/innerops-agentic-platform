import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { requestHostname, buildRuntimeContext } = require('../src/runtimeContext.js');

test('extracts hostname without port', () => {
  assert.equal(requestHostname({ headers: { host: 'WORKFORCE.SERVIFRAN.SITE:443' } }), 'workforce.servifran.site');
});

test('domain alone never creates authenticated runtime context', () => {
  const context = buildRuntimeContext({ hostname: 'workforce.servifran.site' });
  assert.equal(context.domainTenant.id, 'servifran');
  assert.equal(context.authenticated, false);
  assert.deepEqual(context.enabledModules, []);
});

test('trusted server tenant controls module catalog', () => {
  const context = buildRuntimeContext({ hostname: 'workforce.servifran.site', trustedTenantId: 'servifran' });
  assert.equal(context.authenticated, true);
  assert.equal(context.domainMatchesSession, true);
  assert.deepEqual(context.enabledModules.map((module) => module.id), ['workforce']);
});

test('domain mismatch is observable and cannot change trusted tenant', () => {
  const context = buildRuntimeContext({ hostname: 'app.creatoros.dev', trustedTenantId: 'servifran' });
  assert.equal(context.sessionTenant.id, 'servifran');
  assert.equal(context.domainTenant.id, 'inneros-owner');
  assert.equal(context.domainMatchesSession, false);
});
