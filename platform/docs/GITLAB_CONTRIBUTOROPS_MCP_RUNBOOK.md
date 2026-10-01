# GitLab ContributorOps — runbook MCP (ChatGPT / Carril GitLab)

**Correlación:** `gitlab-contributorops-20261001`  
**Endpoint:** `https://mcp.pcdoctor.ai/router/mcp` (perfil `chatgpt_compact`)

Cursor habilita el camino; **tú ejecutas** las tools y interpretas resultados (no sustituir al agente humano/ChatGPT).

## 1. Bootstrap (obligatorio)

```text
project_runtime_bootstrap(
  project_id="gitlab-contributorops-agent",
  repo="Rafa-Innerchispa/gitlab-contributorops-agent",
  node="primary",
  correlation_id="gitlab-contributorops-20261001",
  dry_run=true
)
```

Repetir con `dry_run=false` solo cuando el dry-run devuelva `ok: true` y tengas carril/approval.

Fork GitLab upstream (runner/gitlab):

```text
project_runtime_bootstrap(
  project_id="gitlab-runner",
  repo="rafagye/gitlab-runner",
  node="primary",
  correlation_id="gitlab-contributorops-20261001",
  dry_run=true
)
```

## 2. Estado y alineación Git

```text
project_runtime_status(
  project_id="gitlab-contributorops-agent",
  node="primary"
)
```

## 3. MR ContributorOps (read-only / gobernanza)

En runtime autorizado (no desde laptop random):

```bash
python3 platform/scripts/gitlab_contributorops_mr.py --help
```

Modos típicos: inspección de MR, sync de handlers MCP — **sin imprimir tokens**. El PAT se resuelve server-side (`local_gitlab_plane`).

## 4. Coordinación

```text
create_agent_message(
  target_agent="notion",
  message_type="message",
  correlation_id="gitlab-contributorops-20261001",
  title="[GitLab][STATE] …",
  body="STATE: …\nEVIDENCE: …\nNEXT: …"
)
```

## Errores comunes

| Error | Causa | Acción |
|-------|--------|--------|
| `project_not_registered` | Falta entrada en Project Runtime Registry | Merge PR registry o `project_runtime_migrate_existing` en ops |
| `tool_not_allowed_for_profile` | Tool fuera de `chatgpt_compact` | Usar `project_runtime_bootstrap` (ya en compact) |
| `remote_url_not_allowlisted` | URL remota no permitida | Usar `repo` GitHub allowlisted; no inventar remotes |
