'use strict';

const http = require('http');
const { html: baseHtml } = require('./server.js');
const { requestHostname, buildRuntimeContext } = require('./runtimeContext.js');

const PORT = Number(process.env.PORT || 8080);

function publicRuntimePayload(context) {
  return {
    authenticated: context.authenticated,
    hostname: context.hostname,
    domainMatchesSession: context.domainMatchesSession,
    domainTenant: context.domainTenant ? {
      id: context.domainTenant.id,
      name: context.domainTenant.name,
      module: context.domainTenant.module,
      branding: context.domainTenant.branding
    } : null,
    sessionTenant: context.sessionTenant ? {
      id: context.sessionTenant.id,
      name: context.sessionTenant.name,
      branding: context.sessionTenant.branding
    } : null,
    enabledModules: context.enabledModules.map((module) => ({ id: module.id, label: module.label, category: module.category }))
  };
}

function runtimeScript() {
  return `<script>
(async()=>{
  try {
    const response=await fetch('/api/runtime',{headers:{accept:'application/json'}});
    const runtime=await response.json();
    const tenantName=runtime.sessionTenant?.name||runtime.domainTenant?.name||'Sign in required';
    const tenantLabel=document.querySelector('.tenantbox strong');
    if(tenantLabel) tenantLabel.textContent=tenantName;
    const enabled=new Set((runtime.enabledModules||[]).map(m=>m.id));
    const buttons=[...document.querySelectorAll('[data-page]')];
    if(runtime.authenticated){
      buttons.forEach(button=>{
        const id=button.dataset.page;
        button.hidden=!enabled.has(id);
      });
      document.querySelectorAll('.page').forEach(page=>{ if(!enabled.has(page.id)) page.classList.remove('active'); });
      const first=buttons.find(button=>!button.hidden);
      if(first){
        buttons.forEach(button=>button.classList.remove('active'));
        first.classList.add('active');
        const page=document.getElementById(first.dataset.page);
        if(page) page.classList.add('active');
      }
    } else {
      buttons.forEach(button=>button.hidden=true);
      document.querySelectorAll('.page').forEach(page=>page.classList.remove('active'));
      const content=document.querySelector('.content');
      if(content) content.innerHTML='<div class="card"><strong>Authentication required</strong><p>Sign in to load the modules enabled for your organization.</p></div>';
    }
  } catch(error) {
    console.error('runtime context unavailable');
  }
})();
</script>`;
}

function renderRuntimeAwareHtml() {
  return baseHtml.replace('</body>', `${runtimeScript()}</body>`);
}

function createAppServer({ trustedTenantId = process.env.INNEROS_DEMO_TENANT_ID || null } = {}) {
  return http.createServer((req, res) => {
    const context = buildRuntimeContext({ hostname: requestHostname(req), trustedTenantId });

    if (req.url === '/health') {
      res.writeHead(200, { 'content-type': 'application/json' });
      return res.end(JSON.stringify({ ok: true, service: 'inneros', runtime: 'tenant-aware' }));
    }

    if (req.url === '/api/runtime') {
      if (context.authenticated && context.domainTenant && !context.domainMatchesSession) {
        res.writeHead(403, { 'content-type': 'application/json' });
        return res.end(JSON.stringify({ ok: false, error: 'tenant_domain_mismatch' }));
      }
      res.writeHead(context.authenticated ? 200 : 401, { 'content-type': 'application/json' });
      return res.end(JSON.stringify(publicRuntimePayload(context)));
    }

    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    res.end(renderRuntimeAwareHtml());
  });
}

if (require.main === module) {
  createAppServer().listen(PORT, '0.0.0.0', () => console.log(`InnerOS listening on ${PORT}`));
}

module.exports = { createAppServer, publicRuntimePayload, renderRuntimeAwareHtml };
