# Acuerdo de trabajo propuesto: InnerOS Incident Room × Flip the Switch 2026

**Fecha de revisión:** 2026-10-26 (Guayaquil, UTC-5)  
**Estado:** propuesta de alcance operativo; NO equivale a inscripción, contrato firmado ni entrega al concurso.  
**Promotor:** InnerChispa LLC / participante individual autorizado.  
**Categoría objetivo:** Best Business Workflow (USD 2.000).

## 1. Resultado que entregaremos

Una sala real de Switch vinculada a Mattermost donde **una persona y dos agentes InnerOS** colaboren para resolver un incidente de infraestructura **100 % sintético** inspirado en un caso de cámara/red, sin datos de clientes. El relato y los resultados deben ser reproducibles desde un clon limpio. Switch debe ser imprescindible para la coordinación visible entre humano y agentes.

**Secuencia obligatoria:**
1. Un operador publica una alarma sintética en la sala.
2. El agente `ralphiia-triage` recibe un evento dirigido mediante Switch, consulta el contrato de incidente y explica diagnóstico/evidencia.
3. Un agente `fieldops-verifier` verifica independientemente el estado disponible y propone una actuación simulada delimitada.
4. Una persona identificada aprueba o rechaza en la sala; negar o identidad incorrecta bloquea toda mutación.
5. Solo si existe autorización válida, un ejecutor sintético aplica `simulate_restart` sobre un dispositivo fabricado.
6. Verificación independiente comprueba estado posterior y envía a la misma sala un recibo con `incident_id`, `correlation_id`, decisión, resultado, evidencia, hora y hash de integridad.

## 2. Integraciones y límites

- **Switch Rooms (nuevo durante el evento):** mensajes, contexto de sala, identidad, registro de agente, API WebSocket para eventos y HTTP para operaciones. No usar SSE obsoleto en la implementación nueva.
- **Mattermost incluido con Switch (nuevo durante el evento):** sala reproducible sin depender de administradores de Slack ni fallos previos de WhatsApp. Telegram es una mejora opcional y nunca condición del demo.
- **InnerOS / RalphiIA / MCP Small (preexistentes):** lógica y capacidades existentes accedidas solo por un adaptador expresamente permitido; no duplicar ni modificar el núcleo de orquestación para el hackatón.
- **FieldOps (preexistente):** patrón `OBSERVE → ANALYZE → APPROVE → EXECUTE → VERIFY → EVIDENCE`. Reutilización con atribución correcta.
- **Inferencia local preferente:** sin gastos por APIs externas. En ejecución de jueces, utilizar fixture determinista como alternativa reproducible si el modelo local no está disponible.
- **Temporal / Mongo / DevSwarm:** pueden aportar persistencia y trazabilidad cuando se demuestre su salud, pero no serán un prerrequisito de una demo aislada. No generar trabajo redundante en su cola.
- **No producción:** ni Bellini ni sistemas reales, cámaras, cerraduras, PBX, credenciales de proveedores o datos personales; el escenario y las IP serán inventados. Los actos físicos quedan fuera del alcance.

## 3. Estado verificado al 26 de octubre

- Material inicial publicado: `Rafa-Innerchispa/innerops-agentic-platform`, rama `prep/flip-the-switch-2026`, base de 21 archivos con commit `756c44039088dee09ad14313bd2075e457b6258c`.
- El paquete de preparación pasó 12/12 pruebas offline en ambiente aislado, más el preflight limitado de patrones de secretos y las rutas sintéticas de aprobar/rechazar.
- La conexión real Switch, la sala Mattermost, el repositorio independiente y la inscripción/submisión **NO están verificados**.
- `ops_c031b56ae0ec` terminó `failed` el 2026-10-22/23, al generar una prueba que buscó el kit en una referencia/ruta que no contenía la carpeta. No creó el repositorio. No presentar la ejecución fallida como progreso.

## 4. Plan y fechas

**PRE-EVENTO, 26 oct–3 nov antes de 13:31 GYT:** corregir proceso de provisión con fuente explícita `prep/flip-the-switch-2026`; crear repo independiente `Rafa-Innerchispa/inneros-incident-room-switch-2026` inicialmente PRIVADO, copiar exclusivamente los 21 archivos al raíz; ejecutar 12 pruebas y revisión de secretos. Validar capacidad y puertos de máquina aislada, documentación oficial y acceso de inscripción. Preparar contenido/guion y trazabilidad. **No implementar la integración ni el flujo Switch antes de la ventana.**

**EVENTO día 1, desde 3 nov 13:31 GYT:** fijar versión oficial de Switch, iniciar Switch y Mattermost en host aislado, registrar agente personalizado y construir adaptador WS/HTTP; demostrar primera respuesta de un mensaje real dirigido al agente desde la sala.

**Día 2, 4–5 nov:** conectar fixture existente con los dos agentes; identidad humana, aprobación/rechazo y recibo verificable en sala; bloquear duplicados, actor ajeno y acciones no autorizadas.

**Día 3, 5–6 nov:** pruebas E2E de reconexión/cursor, fallo de verificación y reproducibilidad de clon limpio; corregir problemas. Preferir estabilidad antes que funciones extra.

**Día 4, 6–7 nov:** capturar demo real de 2–3 minutos, completar README/arquitectura/log con atribución de código preexistente y nuevo, CI, auditoría de privacidad, y hacer público el repo solo tras revisión. La persona participante registra y envía manualmente antes de **7 nov 13:29 GYT**. El kickoff es **2 nov 10:30 GYT**.

## 5. Criterios para declarar DONE

- URL de repositorio público de entrega y commit final comprobables, sin secretos ni datos de clientes.
- Switch y Mattermost reales; al menos una persona y un agente realizan trabajo útil en la misma sala. Objetivo interno: dos agentes con roles diferentes.
- Adaptador WS/HTTP efectivamente integrado; logs con eventos dirigidos, registro, reconexión y respuestas.
- Negativa humana => sin cambios; aprobación válida => ejecución **solo sintética**, seguida de verificación independiente y recibo en sala.
- Pruebas automatizadas y demo de extremo a extremo desde clon limpio, con capturas y video auténticos.
- Código/reutilización atribuidos, build log con fechas, sin confundir simulación con operaciones reales.
- Presentación manual del participante confirmada por recibo/URL del organizador. **Una tarea en cola o un commit aislado no es evidencia de DONE.**

## 6. Reglas de ejecución y propietarios

- **Participante:** identidad/registro, revisión final de privacidad y envío oficial; aprobaciones de acciones reales fuera del demo si alguna vez se plantearan.
- **Asistente de ingeniería:** diseñar, codificar y probar en entornos aislados con herramientas disponibles, escribir docs, auditar GitHub, informar evidencia y bloqueos de forma explícita.
- **DevSwarm:** opcional, solo para tareas acotadas y con fuente/ref exacta, artefactos exigidos y verificación; no delegar la creación de repo a un test Python.
- **Git:** trabajar en rama o repo dedicado, sin modificar `main` del núcleo ni hacer merges/force-push automáticos.
- **Credenciales:** secretos en almacén externo a Git, cuenta de prueba de Switch separada, mínima autorización y sin reutilizar claves reales.
- **Recursos:** preflight de RAM, swap, disco y puertos (Switch Compose documenta API 8000 y Gateway 3000, potencial colisión con servicios InnerOS). No desplegar en servidor de producción sin aislamiento comprobado.
- **Progreso:** toda tarea cerrada lleva URL/SHA, comandos/tests/resultado de integración y nota de seguridad. Sin dependencia de trabajos en background de ChatGPT.

## 7. Qué NO construiremos para este concurso

Una consola universal de todas las marcas de dispositivos, nuevas integraciones Hikvision/Dahua/Ruijie, control físico de cámaras, reparación general de Temporal/Mongo/DevSwarm, WhatsApp, una web comercial completa, ni un agente nuevo que reemplace InnerOS. Son proyectos de largo plazo separados.

## 8. Referencias y control

- Kit: `hackathons/flip-the-switch-2026` en `prep/flip-the-switch-2026`.
- Repositorio destino planeado: `Rafa-Innerchispa/inneros-incident-room-switch-2026`.
- Issues existentes: #213 repo, #214 host, #215 Switch, #216 aprobaciones, #217 demostración.
- Normativa: https://www.wemakedevs.org/hackathons/switch/rules
- Agenda: https://www.wemakedevs.org/hackathons/switch/schedule
- Protocolo actual: https://docs.switchagents.ai/switch-rooms/internals/agent-protocol

**Regla final:** si una integración no se ha comprobado E2E, se informa como pendiente, no como terminada.
