'use strict';

const { getTenantByDomain, getTenantById } = require('./tenantRegistry.js');
const { getEnabledModulesForTenant } = require('./moduleCatalog.js');

function requestHostname(req) {
  const raw = String(req?.headers?.host || '').trim().toLowerCase();
  return raw.split(':')[0];
}

function buildRuntimeContext({ hostname, trustedTenantId } = {}) {
  const normalizedHostname = String(hostname || '').trim().toLowerCase().split(':')[0];
  const domainTenant = getTenantByDomain(normalizedHostname);
  const sessionTenant = trustedTenantId ? getTenantById(trustedTenantId) : null;
  const enabledModules = sessionTenant ? getEnabledModulesForTenant(sessionTenant.id) : [];

  return {
    hostname: normalizedHostname,
    domainTenant,
    sessionTenant,
    authenticated: Boolean(sessionTenant),
    enabledModules,
    domainMatchesSession: Boolean(domainTenant && sessionTenant && domainTenant.id === sessionTenant.id)
  };
}

module.exports = { requestHostname, buildRuntimeContext };
