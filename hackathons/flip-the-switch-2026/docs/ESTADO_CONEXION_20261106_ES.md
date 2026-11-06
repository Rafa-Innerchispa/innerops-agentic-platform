# Estado de integración y conexión — 6 de noviembre de 2026

**Corte de verificación:** 12:02 Ecuador (UTC-5), durante el período del hackatón.
**Origen:** inspección read-only de MCP Small / AG-41 PEER_OPS y pruebas de una copia limpia del paquete de entrega.

## Qué es Switch
Switch AI es una plataforma de colaboración humano-agente en salas de chat; no es un switch de red, un router, un modelo de IA, ni sustituye a InnerOS. El cliente recibe eventos por WebSocket y publica respuestas por HTTP. Switch Console ejecuta la plataforma y Mattermost localmente para la demo.

## Confirmado
- InnerOS MCP Small respondió satisfactoriamente (bridge 2.70.0); su capa A2A respondió y la conexión Temporal figura disponible.
- AG-41 obtuvo snapshots de solo lectura de AMD e Intel. Ambos están levantados. La inferencia local de AMD está en marcha y expone su servicio únicamente en loopback; para acceder desde un Windows externo a ese proceso haría falta un túnel autorizado o un cambio de arquitectura. No exponer vLLM a la LAN por defecto.
- El código portable release del 6 de noviembre pasó **53 pruebas unitarias** en un entorno aislado de esta revisión. El preflight de patrones de secretos pasó (revisión limitada, no auditoría exhaustiva).
- Existe código de integración transport WebSocket+HTTP probado frente a **servidor simulado**, sin conexión auténtica a Switch.

## Aún NO confirmado
- No hay evidencia de que Switch Console/Mattermost estén instalados en la computadora del participante ni de una sala Switch real.
- No existe un mensaje auténtico en Switch que invoque RalphiIA/MCP y regrese al chat. El código actual usa contratos sintéticos y opcionalmente un modelo local compatible con API OpenAI; no invoca automáticamente las herramientas reales de InnerOS.
- FieldOps todavía es el nombre del comprobador/regla sintética, **no un segundo agente registrado en Switch**.
- No hay video ni recibo de presentación del proyecto verificados.
- La rama de hackatón está en el repositorio principal; el repo independiente no se ha creado con la conexión GitHub disponible.

## Topología prioritaria: no tocar red doméstica
Windows con Wi-Fi celular para descargas/Internet y Wi-Fi casa para LAN. Ejecutar Switch Console + Mattermost y el cliente Python en el propio Windows. La demo **no depende de AMD ni Intel**: su escenario se ejecuta como fixture sintético. Como extensión, conectar inferencia AMD con túnel SSH local a loopback, sin cambiar UniFi ni publicar modelos/secretos.

## Primer hito E2E exigido
1. Instalar Switch Console y crear servidor local, un usuario humano y sala Mattermost.
2. Registrar cliente personalizado con clave de registro generada por el usuario desde Switch Gateway. Conservar token en el perfil local Windows, no en Git.
3. Ejecutar los scripts del repo para descubrir room ID e identidad del operador, levantar el cliente y comprobar una mención real de humano en sala.
4. Denegar y aprobar un incidente sintético en el chat; exigir respuestas y recibo en la misma sala. Grabar el evento real.
5. Solo tras prueba exitosa publicar repositorio de entrega y completar envío personal en WeMakeDevs.

**No declarar integración E2E ni despliegue real hasta tener evidencia de servidor, evento y retorno.**

## Documentación oficial
- https://docs.switchagents.ai/switch-rooms/getting-started
- https://docs.switchagents.ai/switch-rooms/internals/agent-protocol
- https://www.wemakedevs.org/hackathons/switch/rules
- https://www.wemakedevs.org/hackathons/switch/schedule