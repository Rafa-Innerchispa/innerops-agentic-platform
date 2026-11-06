# Flip the Switch: plan de ejecución real (6-7 nov 2026)

**Cierre:** 7 de noviembre de 2026 a las 13:29 de Ecuador (23:59 IST).
**Objetivo mínimo que cuenta:** humano + un agente trabajando mediante una sala auténtica de Switch y Mattermost, con evidencia de una tarea completada. El resto es optativo.

## Ya terminado en este paquete

- Código sintético y contrato de evidencia reutilizados del trabajo previo al evento, con atribución en `docs/REUSE_MANIFEST.md`.
- Nuevo durante el evento: adaptador de WebSocket y respuesta HTTP para Switch, registro de agente, diagnóstico de conexión, journal local sin secretos, pruebas de integración contra un servidor **FALSO** compatible con la forma de los mensajes documentados, y enlace opcional a LLM local OpenAI-compatible.
- 53 pruebas locales, incluyendo una secuencia HTTP+WebSocket real **contra un servidor de pruebas**, no contra Switch instalado de verdad. Jamás llamar a ese test "Switch live".
- Nada de cámaras, hardware, dispositivos físicos o routers reales se cambia.

## Topología recomendada con los dos Wi-Fi

```text
Internet del teléfono (Wi-Fi 1) -> descarga Switch Console y dependencias
Casa (Wi-Fi 2) -> acceso LAN al AMD 1.5 y al Intel 1.4
              -> inferencia local opcional, únicamente datos ficticios
Computadora Windows local -> Switch Console + Switch + Mattermost + Python agent
```

**No modificar IP, gateway, DHCP, ruta predeterminada, DNS, métricas de adaptadores ni UniFi.** El sistema operativo selecciona la ruta para cada destino; la verificación es de solo lectura.

1. Abre PowerShell en el equipo Windows. Comprueba las dos IP completas de los servidores con:
   `Get-NetIPConfiguration`
2. Ejecuta `./scripts/diagnostico_lan.ps1 -AmdIP "IP_COMPLETA_AMD" -IntelIP "IP_COMPLETA_INTEL"` desde la carpeta del proyecto. No adivines direcciones ("1.5" y "1.4" pueden ser solo sufijos).
3. Si la red local no se alcanza desde Windows, la inferencia local es **opcional**: continúa la demo sin ella. No bloquees el hackatón por la conectividad.

## Instalar Switch, sin esperar por DevSwarm

1. Instala **Switch Console para Windows x64** mediante su guía oficial: https://docs.switchagents.ai/switch-rooms/getting-started/install-switch-console
2. Abre la aplicación y elige **Add a server -> local**. La Console inicia los servicios necesarios usando Docker. Debe existir el **Switch API** en una URL (a menudo `http://127.0.0.1:8000`), verificable en el navegador con `/health`. Nunca confundir el puerto Switch con vLLM AMD :8000.
3. Completa la sala de Mattermost que crea Switch; crea o usa **tu propia identidad real de operador**. Mantén la sala sin conexiones a datos de clientes.
4. En el Gateway de Switch, crea una **registration API key** en la página de API Keys de tu cuenta. No compartir la clave por chat y no pegarla en GitHub. El agent API key es distinto.
5. En PowerShell, desde el proyecto, instala Python 3.11+ si falta y ejecuta:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[switch]"
$env:SWITCH_REGISTRATION_KEY = Read-Host "Switch registration key"
.\.venv\Scripts\python.exe scripts\register_agent.py --url http://127.0.0.1:8000
Remove-Item Env:\SWITCH_REGISTRATION_KEY
.\.venv\Scripts\python.exe scripts\discover_rooms.py
```

> **Registro de agente**, no del hackatón. Este script guarda la clave del agente en tu perfil de usuario, **fuera del repositorio**, y nunca la imprime.

6. Invita el agente `inneros-incident-triage` a la sala con Switch Console/Gateway. Repite la consulta para identificar el `room_id` auténtico y el `sender` del **operador que aprobará**, no su alias de pantalla:

```powershell
.\.venv\Scripts\python.exe scripts\discover_rooms.py --room "ID_REAL_SALA"
$env:SWITCH_ROOM_ID = "ID_REAL_SALA"
$env:SWITCH_APPROVER_ID = "ID_REAL_OPERADOR"
.\.venv\Scripts\python.exe scripts\run_agent.py --doctor
.\.venv\Scripts\python.exe scripts\run_agent.py
```

Si falla el doctor, **no declares conectado**. Comprueba que el health corresponde al API de Switch y que el registro se hizo con la cuenta adecuada.

## Opcional: inferencia AMD 1.5 por Wi-Fi de casa

En el equipo Windows, prueba primero que exista un servicio de inferencia local autorizado y accesible, **sin exponer credenciales**. Por seguridad, usa un túnel SSH si está disponible y autorizado:

```powershell
# En una segunda terminal, si existe SSH autorizado en AMD:
ssh -N -L 18780:127.0.0.1:8000 USUARIO_SSH@IP_COMPLETA_AMD
# En la terminal del agente:
$env:LOCAL_MODEL_URL = "http://127.0.0.1:18780/v1"
# Verifica el nombre real con GET /v1/models; no supongas qué modelo sirve.
$env:LOCAL_MODEL_NAME = "NOMBRE_REPORTADO_POR_SERVIDOR"
```

Solo se envían datos **sintéticos** al modelo local. Si hay interrupciones, el agente funciona con la narrativa determinista. El modelo no puede aprobar ni ejecutar.

## Ensayo real dentro de la sala Switch

Dirígete al agente por mención, con estas órdenes:

1. `@inneros-incident-triage !incident` -> diagnóstico sintético, justificación y `ACTION_ID`.
2. `@inneros-incident-triage !deny ACTION_ID` -> verás **DENIED** y estado degradado.
3. `@inneros-incident-triage !incident` -> nuevo incidente sintético.
4. `@inneros-incident-triage !approve ACTION_ID` -> verás `verified_simulation`, checksum y estado simulado reparado.
5. Haz una aprobación desde otra identidad o con otro `ACTION_ID` -> verás **BLOCKED**; no cambia nada.

Todas estas acciones deben llegar como **eventos dirigidos** (`addressed=true`) por Switch. Si la consola muestra respuestas pero no existe un evento auténtico de la sala, no cuenta.

## Entrega

1. Graba la pantalla **del Switch real**, el operador humano, la decisión y la respuesta del agente. No usar el mock como si fuera una captura oficial.
2. Crea repositorio independiente público, con el código seguro de este paquete, README, instrucciones y tests. No copies credenciales del perfil de usuario ni registros de IP privadas.
3. En la web WeMakeDevs, inicia sesión con la **identidad legal correcta**, crea/sube el proyecto manualmente, comparte URL GitHub y video y guarda el recibo de envío. Las reglas prohíben registros/submisiones automatizados por bots.
4. No depender de Temporal, DevSwarm, antiGravity, Codex ni de que exista un servidor AMD accesible para cumplir los mínimos.

## Bloqueos actuales verificados desde ChatGPT

- La herramienta de acceso a InnerOS/MCP falla internamente; no prueba conectividad a AMD/Intel y **no autoriza afirmar acceso al LAN desde el contenedor de ChatGPT**.
- El conector GitHub actual puede publicar en repositorios existentes, pero no crear uno nuevo directamente.
- Sin la instalación de Switch, la clave de registro generada por el propietario y una sala autenticada, no puede certificarse el demo de extremo a extremo.

## Guías oficiales

- https://docs.switchagents.ai/switch-rooms/internals/agent-protocol
- https://docs.switchagents.ai/switch-rooms/internals/agent-connection
- https://docs.switchagents.ai/switch-rooms/getting-started
- https://www.wemakedevs.org/hackathons/switch