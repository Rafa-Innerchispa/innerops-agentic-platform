# AMD deploy migration runbook — serving checkout divergente (2026-11-12)

Target: `main@92913951` (NO incluye rama C1–C5: viaja en el deploy siguiente
al merge). Método: árbol paralelo + flip por renombrado. Cero borrados:
el árbol actual queda intacto como rollback.

## 0. Estado probado (forense read-only, no asumir)

- Repo serving: `/home/rlopez/inneros/inneros_core/` @ `f3a4ecdd` (27-oct),
  rama `main` local; origin/main fresco = `92913951`. NO fast-forward
  (era squash): behind 732 + 5 commits locales (contifico/hosting/cpanel,
  14–27 oct) parcialmente ya en main.
- Drift: 123 `M` (110 byte-identicos a main; 7 runtime AUSENTES en main:
  hosting/contifico/cpanel — sin importadores en main; 3 tests; 1 config;
  1 registry.json = ESTADO; 1 gitlink) + 892 `??` (182 colisionan con main:
  178 identicos, 4 tests divergentes; 710 solo-worktree).
- Solo-worktree con carga: `inneros_core_runtime/ops_post_owner_autopilot.py`
  (lo importa `notifications/ops_ha_owner_auth.py:246` con try/except:
  sin él, autopilot post-auth se degrada en silencio). Resto importable
  verificado sin importadores exactos (dups top-level muertos).
- Estado: `.env` (untracked, 600) + `.env.*`, `venv/` 6.1G untracked,
  `var/` 72K, `registry.json` trackeado-pero-estado. `requirements.txt`
  SIN drift f3a4ecdd→main ⇒ venv reutilizable.
- `.runtime_git_sha` dice `92913951` con árbol `f3a4ecdd`+drift: MIENTE.
  Regenerar post-deploy, jamás copiarlo.
- Servicios leen `.../platform` como root (`PYTHONPATH=.../platform`,
  `WorkingDirectory=.../platform`, `.env` vía `EnvironmentFile`).
  Drop-ins systemd (ej. colas `amd-gpu-ops`) se conservan solos (viven
  en `~/.config`, no en el repo).

## 1. Preflight (abortar si algo difiere)

```bash
R=/home/rlopez/inneros/inneros_core
git -C $R fetch origin --quiet
git -C $R rev-parse origin/main  # debe ser 92913951b521ec49bf4ed6773be39611dcc8c60c
systemctl --user list-units --type=service --state=running --no-pager | grep -E "temporal-worker|ralfia-mcp|external-repair"
curl -sf http://127.0.0.1:8102/healthz || curl -sf http://127.0.0.1:8102/  # baseline MCP
```

## 2. Árbol nuevo (sin tocar el que sirve)

```bash
R=/home/rlopez/inneros/inneros_core
N=$R/platform-next-92913951
git -C $R worktree add --detach $N origin/main
# Estado + huérfanos con carga (lista reproducible, §4):
cp $R/platform/.env $R/platform/.env.bak_20261106 $R/platform/.env.ops-notify $R/platform/.env.telegram-load $N/ 2>/dev/null || true
cp $R/platform/inneros_core_runtime/ops_post_owner_autopilot.py $N/inneros_core_runtime/
# Módulos ausentes-en-main (muertos según imports estáticos; se portan por si
# hay imports dinámicos — peso muerto si no se usan, salvavidas si sí):
for f in capability_gateway_hosting contifico_read_query cpanel_client hosting_authorization hosting_control_plane; do
  cp $R/platform/inneros_core_runtime/$f.py $N/inneros_core_runtime/ 2>/dev/null || true
done
cp $R/platform/var/project_runtime_registry/registry.json $N/var/project_runtime_registry/ 2>/dev/null || true
echo -n 92913951b521ec49bf4ed6773be39611dcc8c60c > $N/.runtime_git_sha
# OJO: el venv NO se linkea aquí (la ruta absoluta se rompería en el flip).
# Se crea el symlink relativo DESPUÉS del flip (§4) y los gates usan el
# binario venv actual por ruta absoluta + sys.path apuntando a $N.
```

## 3. Gates (todo debe pasar; si uno falla: parar, reportar, rollback N/A)

1. `diff -rq $R/platform $N --exclude=venv --exclude=.env* --exclude=var --exclude=__pycache__ --exclude=.runtime_git_sha` ⇒ solo deltas esperados
   (código main + huérfano portado). Cero sorpresas o abortar.
2. Smoke imports con el venv servido:
   `.../platform/venv/bin/python3 -c "import sys; sys.path.insert(0,'$N'); import inneros_core_runtime.temporal_worker, inneros_core_runtime.mcp_server"`.
3. `python3 -m compileall -q $N/inneros_core_runtime $N/scripts`.
4. Gate focal: `test_ops_cancel_eviction + test_ops_expired_lease_recovery + test_ops_claim_spawn_ack`
   contra ESTE árbol (post-merge; hoy fallan por import — esperado).

## 4. Flip (ventana corta, rollback trivial)

```bash
systemctl --user stop inneros-temporal-worker.service ralfia-mcp.service ralfia-external-repair-agent.service ralfia-mcp-profile@chatgpt_compact.service
mv $R/platform $R/platform-prev-f3a4ecdd && mv $N $R/platform
# venv: symlink relativo al árbol preservado (el venv servido no se toca):
ln -s ../platform-prev-f3a4ecdd/venv $R/platform/venv
test -x $R/platform/venv/bin/python3 && $R/platform/venv/bin/python3 --version
systemctl --user start inneros-temporal-worker.service ralfia-mcp.service ralfia-external-repair-agent.service ralfia-mcp-profile@chatgpt_compact.service
# Salud: MCP 8102, Temporal 7233, worker logs (journalctl --user -u ... --since -5m), vLLM 8000 intacto (no se toca).
```

Rollback: stop → `rm $R/platform/venv` (solo el symlink creado aquí) →
`mv platform platform-bad; mv platform-prev-f3a4ecdd platform` → start → salud.
`platform-prev-*` NO se borra hasta 7 días de verde (regla: borrados solo con OK por ruta).

## 5. Regenerar listas (triage reproducible, si main avanzó)

```bash
git -C $R status --porcelain -uall | grep '^\s*??' | sed 's/^?? //' | LC_ALL=C sort -u > /tmp/u.txt
git -C $R ls-tree -r --name-only origin/main | LC_ALL=C sort -u > /tmp/m.txt
comm -12 /tmp/m.txt /tmp/u.txt            # colisiones (hoy: 182)
comm -13 /tmp/m.txt /tmp/u.txt | grep '\.py$'  # huérfanos importables: re-verificar importadores
```

## 6. Fuera de alcance aquí

Merge rama C1–C5 (owner), deploy Intel (sin shell desde AMD: replicar este
runbook allá), timers AMD (cero hoy), sync Mongo, failover-kill (trigger owner).
