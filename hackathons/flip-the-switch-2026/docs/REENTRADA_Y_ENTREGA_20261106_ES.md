# Flip the Switch | Reentrada y entrega sin colas de agentes

**Cierre oficial:** 7 nov 2026, 13:29 hora Ecuador. **Estado de este documento:** código local probado; la sala existe, pero **no hay evidencia de que ningún agente haya respondido ni operado Home Assistant por Switch**. No publicar un video fabricado ni declarar integración activa sin comprobarlo.

## Primeros tres minutos cuando vuelvas

1. Abre Switch Console y entra al canal existente **#inneros-live-operations**. No crees otro canal. Mira **el hilo** bajo la mención al agente, no solo el canal principal.
2. Publica `!agents-status` como mensaje aislado. Según la [guía oficial](https://docs.switchagents.ai/switch-rooms/using/agent-not-answering), este comando lo responde **Switch**, incluso si Codex está offline. Si aparece `live`, prueba `!agents-greet`; si aparece `awaiting input`, abre la solicitud pendiente. Si nada responde, revisar la comunicación de Mattermost antes de tocar agentes o Windows.
3. Abre el chat **privado Welcome** de `switch-buddy-admin` y escribe: `Responde LISTO. No ejecutes comandos.` Si privado responde pero canal no, es el bridge/mention. Si tampoco responde en privado, revisar el controlador de Codex/Windows. [Diagnóstico Windows](SWITCH_DIAGNOSIS_20261106.md).

## Prueba local de solo lectura desde PowerShell

Extrae el ZIP del proyecto en una carpeta local sin secretos, abre PowerShell dentro de ella:

```powershell
.\scripts\preflight_windows.ps1
```

No requiere privilegios de administrador y **no cambia redes, Docker ni los dispositivos**. Comprueba si `codex`, `agy` y Python están en PATH; busca el servidor Switch en loopback y recuerda los comandos de diagnóstico. Si el servidor usa otro puerto, usa `-SwitchUrl http://127.0.0.1:PUERTO_REAL` tras verlo en Switch Console.

## Ruta recomendada para ganar tiempo: cliente propio independiente de Codex

1. Mantén Switch Console y Mattermost levantados. Registra **un agente personalizado** por la API de Switch. La clave de **registration** la generas en Gateway → API Keys, con tu propia cuenta. No pegues claves en chat ni archivos públicos.
2. Desde PowerShell, en carpeta raíz del proyecto:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[switch]"
$env:SWITCH_REGISTRATION_KEY = Read-Host 'Switch registration key'
.\.venv\Scripts\python.exe scripts\register_agent.py --url http://127.0.0.1:8000
Remove-Item Env:\SWITCH_REGISTRATION_KEY
.\.venv\Scripts\python.exe scripts\discover_rooms.py
```

**El puerto 8000 es ejemplo de la documentación**, no se ha comprobado en tu equipo. Cambiarlo si la URL real difiere. El `register_agent.py` deja el token en un archivo privado del perfil, no en Git. No vuelvas a registrarlo si el nombre existe (409).

3. En Switch Console, añade `inneros-incident-triage` a **#inneros-live-operations**. Usa `discover_rooms.py --room ID_REAL_SALA` para leer los IDs de sala y participante del operador **sin asumir que `@rafagye` sea el ID de aprobación**.
4. Prepara el vínculo **Home Assistant real**: configura variables `HA_URL`, `HA_TOKEN`, `HA_ALLOWED_LIGHTS=light.ID_REAL`. Deja `HA_ENABLE_REAL_ACTIONS` sin definir inicialmente. Selecciona solo luz de bajo riesgo.
5. **Comprueba HA antes de Switch:**

```powershell
.\.venv\Scripts\python.exe scripts\discover_ha_lights.py
$env:SWITCH_ROOM_ID = 'ID_REAL_SALA'
$env:SWITCH_APPROVER_ID = 'ID_REAL_PARTICIPANTE'
.\.venv\Scripts\python.exe scripts\run_live_homeassistant.py --doctor
```

6. Ejecuta `run_live_homeassistant.py` sin `--doctor`. Desde la sala, dirige al nuevo agente `!lights` y `!state light.ID_REAL`. Debe informar **estado real y hora de lectura**; un estado `UNKNOWN`, desconectado o sin respuesta no es éxito. No requiere modelos de pago.
7. Para efectuar una acción física limitada, solo con persona presente y **autorización explícita**, activar la variable `HA_ENABLE_REAL_ACTIONS=YES`, reiniciar el agente, pedir `!propose light.ID_REAL on`, leer el código de acción y aprobar con `!approve HA-...` desde la identidad configurada. Debe aparecer `HA LIVE VERIFIED` y la luz debe cambiar; el texto por sí solo es lectura de Home Assistant, no sensor físico independiente. No habilitar otras familias de dispositivos.

## Ruta de entrega

- Repositorio público ya disponible: [carpeta del hackatón en la rama](https://github.com/Rafa-Innerchispa/innerops-agentic-platform/tree/hackathon/flip-the-switch-20261106/hackathons/flip-the-switch-2026). No lo describir como repositorio independiente: todavía no existe.
- El script `python scripts/submission_preflight.py` produce evidencia JSON local y solo certifica **código**.
- El video debe mostrar: mensaje humano → mensaje real del agente en Switch → lectura HA auténtica → aprobación y acción sobre luz si fue autorizada → verificación. **Nunca mostrar la clave de Switch ni HA**.
- Incluir crédito a código reutilizado anterior al 3 nov; el nuevo adaptador Switch y el flujo del concurso se construyeron desde el 6 nov.
- **El propietario realiza el envío personalmente** en el portal de WeMakeDevs, porque las reglas prohíben inscripciones y presentaciones por bots. Guardar recibo.

## Para no fallar la entrega

Si solo funciona el chat humano-agente pero no Home Assistant, filmar y describir honestamente una tarea real de coordinación (diagnóstico y verificación de logs) como candidatura más pequeña, sin fingir cambio de dispositivo. Si no hay respuesta real de Switch, **no se ha cumplido el requisito central**; no presentar el simulador offline como solución operativa.