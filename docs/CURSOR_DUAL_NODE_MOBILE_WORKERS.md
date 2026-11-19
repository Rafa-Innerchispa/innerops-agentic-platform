# Cursor: móvil + IDE + dos nodos (Intel y AMD)

**Audiencia:** InnerChispa / InnerOS — Rafael  
**Objetivo:** Trabajar desde **cualquier lado** (celular, web, IDE) con **ejecución real** en los servidores, no solo en la VM genérica de GitHub.

| Nodo | LAN | Hostname típico | Rol |
|------|-----|-----------------|-----|
| **Intel** | `192.168.1.4` | `ralphi-ia-ver-10` | Coordinación, Mongo, MCP `:8102`, Temporal, HA |
| **AMD** | `192.168.1.5` | `ralfiia-amd` | vLLM/GPU, media, workers secundarios |

Tailscale complementa la LAN (misma cuenta InnerChispa en laptop y servidores). Los workers **no abren puertos entrantes**: solo salida HTTPS a Cursor.

---

## Las tres formas (úsalas todas)

| Modo | Cuándo | Dónde ejecuta |
|------|--------|---------------|
| **IDE + Remote SSH** | En casa / con laptop | Intel o AMD (tú eliges el host SSH) |
| **Cloud Agent + My Machine (worker)** | Celular, `cursor.com/agents`, afuera | El nodo donde corre el **worker** que eliges |
| **Cloud Agent sin worker** | Solo lectura / PRs en GitHub | VM Cursor (no sirve para coordinación InnerOS viva) |

**Créditos:** se consumen cuando hay una **sesión de agente activa** (IDE o Cloud), no por tener el worker conectado en idle. Dos sesiones en paralelo = doble uso.

---

## Arquitectura (dos workers)

```text
  Celular / Web (cursor.com/agents)
           │
           ▼
  Cerebro Cloud Agent (Cursor)
           │
     ┌─────┴─────┐
     ▼           ▼
 worker       worker
 inneros-     inneros-
 intel-4      amd-5
 (1.4)        (1.5)
```

Al iniciar un agente desde el móvil, en el selector **My Machines** eliges:

- **`inneros-intel-4`** — coordinación, MCP, ops, Mongo, la mayoría de tareas InnerOS.
- **`inneros-amd-5`** — GPU, vLLM, benchmarks AMD, tareas con `preferred_execution_host` AMD.

Cada worker se registra solo para los repos cuyo `git remote` apunta desde su `--worker-dir`.

---

## Bootstrap único por servidor (una vez)

Quien tenga **una** sesión en el servidor (consola, SSH existente, o Remote SSH) ejecuta el instalador de este repo. **No pegar claves ni API keys en chats.**

### Intel (`192.168.1.4`)

```bash
cd /home/rlopez/innerops-agentic-platform   # o tu clone canónico
git pull origin main
export INNEROS_NODE_ROLE=intel
export CURSOR_WORKER_NAME=inneros-intel-4
export CURSOR_WORKER_DIRS="/home/rlopez/innerops-agentic-platform:/home/rlopez/projects/raphiia-openai"
./platform/scripts/setup_cursor_my_machine_worker.sh
```

Luego **una vez**: `agent login` (navegador) **o** API key personal en Dashboard → API Keys:

```bash
agent worker start --name inneros-intel-4 --api-key "$(cat ~/.config/cursor/agent-api-key)" \
  --worker-dir /home/rlopez/innerops-agentic-platform \
  --worker-dir /home/rlopez/projects/raphiia-openai
```

(O usa la unit systemd user que instala el script.)

### AMD (`192.168.1.5`)

```bash
cd /home/rlopez/innerops-agentic-platform
git pull origin main
export INNEROS_NODE_ROLE=amd
export CURSOR_WORKER_NAME=inneros-amd-5
export CURSOR_WORKER_DIRS="/home/rlopez/innerops-agentic-platform"
./platform/scripts/setup_cursor_my_machine_worker.sh
```

Misma cuenta Cursor (InnerChispa) que en Intel. Nombre distinto: **`inneros-amd-5`**.

### Comprobar desde el móvil

1. Abre **Cursor → Agents** (app iOS o web).
2. Menú **dónde corre** → deben aparecer **inneros-intel-4** e **inneros-amd-5**.
3. Prueba inocua: «Lista `hostname` y `INNEROS_NODE_ROLE`» en cada máquina.

```bash
agent worker debug   # en cada servidor, si no aparecen en el picker
```

---

## Celular: flujo recomendado

1. **Agents** → nuevo agente → repo `innerops-agentic-platform`.
2. **Machine:** `inneros-intel-4` (salvo que el objetivo sea GPU AMD).
3. Prompt corto + referencia a `docs/CURSOR_DUAL_NODE_MOBILE_WORKERS.md` y coordinación.
4. Para coordinación viva: pedir `external_repair_agent_status` vía MCP (stdio en el servidor, no en la VM cloud).

App iOS: [Cursor docs — Cloud Agents](https://cursor.com/docs/cloud-agent).

---

## systemd (opcional, worker siempre listo)

El script `setup_cursor_my_machine_worker.sh` puede instalar:

- `~/.config/systemd/user/cursor-inneros-worker.service`
- `cursor-inneros-worker.timer` **no** — el worker es long-lived; habilitar `enable --now` del service.

Requisitos:

- `loginctl enable-linger rlopez` para que sobreviva sin sesión gráfica.
- Salida a `api2.cursor.sh` (firewall).

---

## IDE local (sigue igual)

- Remote SSH a **Tailscale IP** o `192.168.1.4` / `.5`.
- Carpeta del repo en el nodo correcto.
- No sustituye al worker; lo **complementa**.

---

## Qué no puede hacer el Cloud Agent sin worker

- Ver CLIs `codex` / `cursor-agent` / `agy` del host.
- Timers `inneros-*`, Mongo local, MCP `127.0.0.1:8102`.
- Certificar coordinación Telegram/HA end-to-end.

Con **dos workers**, el agente móvil puede hacerlo eligiendo la máquina correcta.

---

## Seguridad

- API keys solo en **Cursor Dashboard → API Keys** o archivo `chmod 600` en el servidor, nunca en Git ni en chats.
- Workers usan la **misma cuenta** que tú; un agente en `inneros-amd-5` no ejecuta en Intel por error si eliges el nombre bien.
- InnerOS sigue exigiendo **aprobación** para gasto IDE (Telegram/HA); el worker no la omite.

---

## Referencias

- [My Machines (Cursor)](https://cursor.com/docs/cloud-agent/self-hosted/my-machines)
- `platform/docs/INNEROS_DUAL_NODE_LANES_HA_COORDINATION_20261031.md`
- `platform/scripts/setup_cursor_my_machine_worker.sh`
- `platform/systemd/user/cursor-inneros-worker.service.example`