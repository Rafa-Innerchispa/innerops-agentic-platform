import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { html, modules } = require('../src/server.js');

test('renders required InnerOS modules', () => {
  for (const label of ['Overview','Workforce','Payroll','Access','Visitors','Credentials','Devices','ARIA','Workflows','Approvals','Audit','Settings']) {
    assert.ok(modules.includes(label));
    assert.match(html, new RegExp(`>${label}<`));
  }
});

test('does not expose cross-tenant organization selector or known tenant list', () => {
  assert.doesNotMatch(html, /<select[^>]*id="tenant"/i);
  assert.doesNotMatch(html, />FEMAR</);
  assert.doesNotMatch(html, />IA PRO</);
  assert.doesNotMatch(html, />PC Doctor</);
  assert.match(html, /Current organization/);
  assert.match(html, /cross-company selector/);
});

test('keeps health and security posture visible', () => {
  assert.match(html, /Tenant isolation/);
  assert.match(html, /Approval gates/);
  assert.match(html, /Audit trail/);
  assert.match(html, /Cloud-ready/);
});
