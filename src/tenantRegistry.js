'use strict';

const tenants = Object.freeze([
  Object.freeze({
    id: 'inneros-owner',
    domains: Object.freeze(['app.creatoros.dev']),
    app: 'InnerOS',
    module: 'overview',
    name: 'CreatorOS',
    branding: Object.freeze({ productName: 'InnerOS', organizationLabel: 'CreatorOS' }),
    entitlements: Object.freeze(['overview', 'workforce', 'payroll', 'access', 'visitors', 'credentials', 'devices', 'aria', 'workflows', 'approvals', 'audit', 'settings'])
  }),
  Object.freeze({
    id: 'servifran',
    domains: Object.freeze(['servifran.site', 'workforce.servifran.site']),
    app: 'InnerOS',
    module: 'workforce',
    name: 'Servifran',
    branding: Object.freeze({ productName: 'Workforce', organizationLabel: 'Servifran' }),
    entitlements: Object.freeze(['workforce'])
  })
]);

function normalizeDomain(value) {
  if (typeof value !== 'string') return '';
  return value.trim().toLowerCase().replace(/^https?:\/\//, '').split('/')[0].split(':')[0].replace(/\.$/, '');
}

function cloneTenant(tenant, matchedDomain) {
  if (!tenant) return null;
  return {
    id: tenant.id,
    domain: matchedDomain || tenant.domains[0],
    domains: [...tenant.domains],
    app: tenant.app,
    module: tenant.module,
    name: tenant.name,
    branding: { ...tenant.branding },
    entitlements: [...tenant.entitlements]
  };
}

function getTenantByDomain(domain) {
  const normalized = normalizeDomain(domain);
  if (!normalized) return null;
  const tenant = tenants.find((candidate) => candidate.domains.includes(normalized));
  return cloneTenant(tenant, normalized);
}

function getTenantById(id) {
  if (typeof id !== 'string') return null;
  const tenant = tenants.find((candidate) => candidate.id === id.trim());
  return cloneTenant(tenant);
}

function getAllTenants() {
  return tenants.map((tenant) => cloneTenant(tenant));
}

function resolveRequestContext({ domain, sessionTenantId, requestedModule } = {}) {
  const domainTenant = getTenantByDomain(domain);
  const sessionTenant = getTenantById(sessionTenantId);

  if (!sessionTenant) {
    return { authorized: false, reason: 'authenticated_tenant_required', domainTenant };
  }

  const moduleName = requestedModule || domainTenant?.module || 'overview';
  const authorized = sessionTenant.entitlements.includes(moduleName);

  return {
    authorized,
    reason: authorized ? null : 'module_not_entitled',
    tenant: sessionTenant,
    domainTenant,
    module: moduleName,
    branding: sessionTenant.branding
  };
}

module.exports = {
  normalizeDomain,
  getTenantByDomain,
  getTenantById,
  getAllTenants,
  resolveRequestContext
};
