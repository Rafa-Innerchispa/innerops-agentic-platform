import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { buildRuntimeContext } = require('../src/runtimeContext.js');
const { publicRuntimePayload, renderRuntimeAwareHtml } = require('../src/appServer.js');

test('runtime payload exposes only enabled Servifran modules', () => {
  const context = buildRuntimeContext({ hostname: 'workforce.servifran.site', trustedTenantId: 'servifran' });
  const payload = publicRuntimePayload(context);
  assert.equal(payload.authenticated, true);
  assert.equal(payload.domainMatchesSession, true);
  assert.equal(payload.sessionTenant.id, 'servifran');
  assert.deepEqual(payload.enabledModules.map((module) => module.id), ['workforce']);
});

test('owner runtime payload exposes complete module catalog', () => {
  const context = buildRuntimeContext({ hostname: 'app.creatoros.dev', trustedTenantId: 'inneros-owner' });
  const payload = publicRuntimePayload(context);
  assert.equal(payload.authenticated, true);
  assert.equal(payload.enabledModules.length, 12);
});

test('runtime aware HTML contains tenant module filtering bootstrap', () => {
  const html = renderRuntimeAwareHtml();
  assert.match(html, /\/api\/runtime/);
  assert.match(html, /Authentication required/);
  assert.match(html, /enabledModules/);
});
