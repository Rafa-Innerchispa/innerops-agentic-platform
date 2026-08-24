'use strict';

class RuntimeError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = 'RuntimeError';
    this.code = code;
    this.details = details;
  }
}

class ProviderAdapter {
  constructor(name, { external = false } = {}) {
    if (!name) throw new RuntimeError('provider_name_required', 'Provider name is required');
    this.name = name;
    this.external = Boolean(external);
  }

  async invoke() {
    throw new RuntimeError('provider_not_implemented', `${this.name} adapter has no invoke implementation`);
  }
}

class LocalAgentAdapter extends ProviderAdapter {
  constructor(handler, name = 'local') {
    super(name, { external: false });
    if (typeof handler !== 'function') throw new RuntimeError('local_handler_required', 'Local adapter requires a handler');
    this.handler = handler;
  }

  async invoke(request) {
    return this.handler(request);
  }
}

class GeminiAdkAdapter extends ProviderAdapter {
  constructor(client, { name = 'gemini-adk' } = {}) {
    super(name, { external: true });
    this.client = client;
  }

  async invoke(request) {
    if (!this.client || typeof this.client.runAgent !== 'function') {
      throw new RuntimeError('gemini_adk_unavailable', 'Gemini/ADK client is not configured');
    }
    return this.client.runAgent({
      agent: request.agent,
      input: request.input,
      context: request.context,
      tools: request.tools,
    });
  }
}

function validateRequest(request) {
  if (!request || typeof request !== 'object') throw new RuntimeError('request_required', 'Runtime request is required');
  if (!request.agent) throw new RuntimeError('agent_required', 'Agent id/name is required');
  if (!request.context || !request.context.tenantId) {
    throw new RuntimeError('tenant_context_required', 'Tenant-scoped context is required');
  }
  if (request.input === undefined || request.input === null) {
    throw new RuntimeError('input_required', 'Agent input is required');
  }
}

class AgentRuntime {
  constructor({ local, external = [], policy = {} } = {}) {
    if (!(local instanceof ProviderAdapter) || local.external) {
      throw new RuntimeError('local_provider_required', 'A non-external local provider is required');
    }
    this.local = local;
    this.external = external.filter((adapter) => adapter instanceof ProviderAdapter && adapter.external);
    this.policy = {
      localFirst: policy.localFirst !== false,
      allowExternalByDefault: policy.allowExternalByDefault === true,
      maxAttemptsPerProvider: Math.max(1, Number(policy.maxAttemptsPerProvider || 1)),
    };
  }

  async run(request) {
    validateRequest(request);
    const allowExternal = request.allowExternal === true || this.policy.allowExternalByDefault;
    const providers = this.policy.localFirst ? [this.local, ...this.external] : [...this.external, this.local];
    const trace = [];
    let lastError = null;

    for (const provider of providers) {
      if (provider.external && !allowExternal) {
        trace.push({ provider: provider.name, status: 'skipped', reason: 'external_not_allowed' });
        continue;
      }

      for (let attempt = 1; attempt <= this.policy.maxAttemptsPerProvider; attempt += 1) {
        try {
          const output = await provider.invoke({
            ...request,
            context: { ...request.context },
            tools: Array.isArray(request.tools) ? [...request.tools] : [],
          });
          trace.push({ provider: provider.name, status: 'ok', attempt });
          return {
            ok: true,
            provider: provider.name,
            external: provider.external,
            output,
            trace,
          };
        } catch (error) {
          lastError = error;
          trace.push({
            provider: provider.name,
            status: 'failed',
            attempt,
            code: error && error.code ? error.code : 'provider_error',
          });
        }
      }
    }

    throw new RuntimeError('all_providers_failed', 'No eligible agent provider completed the request', {
      trace,
      lastCode: lastError && lastError.code ? lastError.code : null,
    });
  }
}

module.exports = {
  RuntimeError,
  ProviderAdapter,
  LocalAgentAdapter,
  GeminiAdkAdapter,
  AgentRuntime,
  validateRequest,
};
