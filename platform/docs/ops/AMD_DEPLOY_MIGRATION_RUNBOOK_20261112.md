# AMD deploy migration runbook — serving checkout divergente (2026-11-12)

Target: `main@92913951` (NO incluye rama C1–C5: viaja en el deploy siguiente
al merge). Método: árbol paralelo + flip por renombrado. Cero borrados:
el árbol actual queda intacto como rollback.

NOTA post-deploy-2: el método real probado es OVERLAY (rsync sin
--delete sobre serving), no `mv` limpio de worktree — serving no es un
worktree (plano = `platform/` promovido + estado + leftovers). Ver §7,
que supersede §2/§4 para futuros deploys.

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

## 7. Deploy-2 — main@132db597 (merge #273) + receta overlay real

### 7.1 Receta corregida (supersede §2/§4 para futuros deploys)

- Serving `/home/rlopez/inneros/inneros_core/platform` = contenido de
  `origin/main:platform/` + estado (`.env*`, `var/`, `venv`→symlink
  relativo) + ~650 leftovers planos (era f3a4ecdd) + marker. NO es un
  worktree (no tiene `.git`); `git -C serving rev-parse` hereda el repo
  padre y MIENTE. Probar contenido (list-diff + byte-diff), no HEAD.
- `git worktree add --detach $W origin/main` (temp `$R/.deploy-wt-<SHA>`,
  remover después con `git worktree remove`).
- Stop 4 units → `cp -a platform platform-prev-<SHA-anterior>`
  (verificar: conteo entries + md5 `var/project_runtime_registry/
  registry.json` + symlink venv intacto) →
  `rsync -a --exclude='/var/' --exclude='/venv'
  --exclude='/.runtime_git_sha' $W/platform/ platform/` (SIN --delete:
  leftovers/estado/huérfanos se preservan; `.env*`/huérfanos no existen
  en git ⇒ intactos) → escribir marker con SHA completo (jamás a mano
  fuera del deploy) → limpiar `__pycache__`/`.pytest_cache` (rutinario)
  → verificar convergencia (`diff -rq` filtrado vacío) → start → salud.
- Rollback: stop → `mv platform platform-bad-<SHA>; mv platform-prev-<old>
  platform` → start → salud. No borrar `platform-prev-*` (7 días de
  verde + OK explícito por ruta).
- Gates: convergencia byte-identical; smoke = units + puertos + journal;
  compileall whole-dir puede marcar leftovers muertos (verificar tracked
  con `git ls-tree origin/main`; untracked = pre-existente, no bloquea);
  focal tests vía mirror CI (copiar `test_*.py`+conftest SIN `__init__.py`,
  symlinks al resto, `GITHUB_ACTIONS=true` hermético, venv python,
  cwd=`tests/`, `PYTHONPATH`=serving) — igual que el workflow.

### 7.2 Ejecución deploy-2 (2026-11-12)

- Preflight: origin/main=`132db597` ✓; marker decía `132db597` pero el
  contenido era `92913951` (reescrito a mano 13:40:13Z sin deploy).
- Hallazgo: runtime serving YA traía código rama (pre-convergido, 0
  differs runtime vs target); deltas = 21 (7 adds: 2 docs + 5 tests
  nuevos; 14 refresh tests: 6 rama + 8 foreign-heal solo-tests, riesgo
  runtime cero). Cero bytes runtime cambiaron en el overlay.
- Backup `platform-prev-92913951` verificado (2567 entries, md5 registry
  idéntico, symlink venv preservado). Overlay + marker veraz.
- Salud: 4/4 units, MCP 8102 HTTP 404-baseline, Temporal 7233 OPEN,
  vLLM 8000 intacto, journal 0 errores. Focal: 21 passed. CI main
  post-merge: 413 passed + mismos 4 pre-existentes.

### 7.3 Lecciones duras

- Marker: verificar bytes siempre, nunca fiarse (mintió 2 veces).
- `git fetch origin <rama>` no actualiza el tracker (solo FETCH_HEAD);
  para verdad remota: `git fetch origin`, `ls-remote` o API `gh`.
- `requirements.txt` sin drift 92913951→132db597 ⇒ venv reutilizado.
- Servidor MCP responde 404 en `/` y `/healthz` por diseño; baseline
  de salud = puerto OPEN + HTTP responde (no connection refused).

## 8. Deploy-4 — main@5803c002 (#277 guardrails) + incidente overlay parcial

Deploy-4 (2026-11-13) convergió runtime pero dejó 15 archivos tests/
obsoletos (era Oct/Nov-1): el rsync transfirió archivos nuevos pero no
todos los modificados (causa mecánica exacta no determinada; el árbol
fuente estaba completo: 1244/1244). Se detectó porque un gate vs
serving falló (F4 con fixture viejo) y se reparó copiando los 15 bytes
verificados por md5 contra origin/main. Runtime nunca afectado
(prueba conductual: canarios v4/v5 + gates).

Reglas nuevas (obligatorias todo deploy futuro):

1. Verificar $W completo ANTES del overlay: `find $W/platform -type f |
   wc -l` debe igualar `git ls-tree -r --name-only origin/main platform
   | wc -l`, más grep de 1-2 archivos clave del cambio.
2. Convergencia SIN FILTRO que oculte ausencias: contar por separado
   `differ` (= 0 exigido) y `Only in $W` (= 0 exigido); solo `Only in
   serving` (leftovers) es aceptable. El filtro viejo (`grep -v`)
   escondía source-missing (falso "converged").
3. Comillas simples en greps con `$` (`grep ' differ$'`): en sh/dash,
   `"...$|..."` entre comillas dobles se come el `$` y da conteo 0
   falso. Toda verificación `grep -c` que dé 0 debe venir con prueba de
   que el input no estaba vacío.
4. Spot-check md5 post-overlay de los archivos del cambio
   (`git show origin/main:<path> | md5sum` vs serving).
5. Nunca editar `.runtime_git_sha` a mano (ni owner ni agentes): miente
   al audit readonly (lee markers, no bytes). Solo el deploy la escribe.
6. Veredicto deploy-4: overlay + reparación 15/15 md5-ok, marker veraz,
   salud 4/4 + journal limpio, gate serving FULL 456/0, canario v5
   verde (4/4, SHAs estrictos). Backup `platform-prev-f140b44b`.
