'use strict';

const { getTenantById } = require('./tenantRegistry.js');

const MODULE_CATALOG = Object.freeze([
  Object.freeze({ id: 'overview', label: 'Overview', category: 'core' }),
  Object.freeze({ id: 'workforce', label: 'Workforce', category: 'operations' }),
  Object.freeze({ id: 'payroll', label: 'Payroll', category: 'operations' }),
  Object.freeze({ id: 'access', label: 'Access', category: 'buildings' }),
  Object.freeze({ id: 'visitors', label: 'Visitors', category: 'buildings' }),
  Object.freeze({ id: 'credentials', label: 'Credentials', category: 'buildings' }),
  Object.freeze({ id: 'devices', label: 'Devices', category: 'infrastructure' }),
  Object.freeze({ id: 'aria', label: 'ARIA', category: 'ai' }),
  Object.freeze({ id: 'workflows', label: 'Workflows', category: 'automation' }),
  Object.freeze({ id: 'approvals', label: 'Approvals', category: 'governance' }),
  Object.freeze({ id: 'audit', label: 'Audit', category: 'governance' }),
  Object.freeze({ id: 'settings', label: 'Settings', category: 'administration' })
]);

function getAllModules() {
  return MODULE_CATALOG.map((module) => ({ ...module }));
}

function getEnabledModulesForTenant(tenantId) {
  const tenant = getTenantById(tenantId);
  if (!tenant) return [];
  const enabled = new Set(tenant.entitlements);
  return MODULE_CATALOG.filter((module) => enabled.has(module.id)).map((module) => ({ ...module }));
}

function isModuleEnabledForTenant(tenantId, moduleId) {
  if (typeof moduleId !== 'string') return false;
  return getEnabledModulesForTenant(tenantId).some((module) => module.id === moduleId);
}

function resolveModuleAccess({ sessionTenantId, requestedModule } = {}) {
  if (!sessionTenantId) {
    return { authorized: false, reason: 'authenticated_tenant_required', module: null };
  }

  const module = MODULE_CATALOG.find((candidate) => candidate.id === requestedModule);
  if (!module) {
    return { authorized: false, reason: 'unknown_module', module: null };
  }

  if (!isModuleEnabledForTenant(sessionTenantId, requestedModule)) {
    return { authorized: false, reason: 'module_not_entitled', module: { ...module } };
  }

  return { authorized: true, reason: null, module: { ...module } };
}

module.exports = {
  MODULE_CATALOG,
  getAllModules,
  getEnabledModulesForTenant,
  isModuleEnabledForTenant,
  resolveModuleAccess
};
