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

## 5. Upstream `gitlab-org/gitlab` (read/fetch) + fork de escritura

Política enforced en `local_execution_plane` + `gitlab_contributor_policy`:

| Remoto | URL | Push |
|--------|-----|------|
| `upstream` | `https://gitlab.com/gitlab-org/gitlab.git` | **Prohibido** |
| `origin` | fork autenticado (hoy: `gitlab-community/gitlab-org/gitlab`) | Permitido en ramas `chatgpt/*`, `codex/*`, … |

Preflight (identidad API, glab, fork, issue sin duplicado):

```bash
python3 platform/scripts/gitlab_contributorops_preflight.py --issue 631702
```

Carril Dev Swarm (MCP Small):

```text
dev_swarm_scope_status(repo="gitlab-org/gitlab")
dev_swarm_launch_task(repo="gitlab-org/gitlab", objective="…", dry_run=true)
local_exec_acquire_lock → local_exec_prepare_repo → local_exec_create_worktree
→ patch/tests → local_exec_commit_branch → local_exec_push_branch(remote="origin")
→ create_draft_merge_request(source=community fork, target=gitlab-org/gitlab)
```

## Errores comunes

| Error | Causa | Acción |
|-------|--------|--------|
| `project_not_registered` | Falta entrada en Project Runtime Registry | Merge PR registry o `project_runtime_migrate_existing` en ops |
| `tool_not_allowed_for_profile` | Tool fuera de `chatgpt_compact` | Usar `project_runtime_bootstrap` (ya en compact) |
| `remote_url_not_allowlisted` | URL remota no permitida | Usar `repo` GitHub allowlisted; no inventar remotes |
| `repo_not_allowlisted` / `repo_owner_not_allowlisted` | Repo lógico no mapeado | Usar `gitlab-org/gitlab` o `gitlab-community/gitlab-org/gitlab` |
| `upstream_push_forbidden` | Intento de push a upstream | Push solo a `origin` (fork) |
| `duplicate_work_on_issue` | MR abierto del autor en el issue | Reusar rama/MR existente |
