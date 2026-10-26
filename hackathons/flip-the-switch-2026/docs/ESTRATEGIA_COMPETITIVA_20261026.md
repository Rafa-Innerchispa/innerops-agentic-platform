# Investigación competitiva y nueva estrategia — 26 octubre 2026

Estado: investigación PRE-EVENTO, no implementación Switch ni presentación final.

## Corrección de concepto y hardware
Switch AI es software para agentes en chat, no un conmutador de red. No se compra switch Ethernet, ni se reconfigura router UniFi, ni se requieren cámaras. Se recomienda Switch Console Windows x64 y Docker en equipo aislado, Mattermost incluido. Versión pública de referencia Switch Console 0.40.1 (21 Oct, core 0.31.0); comprobar latest al instalar.

## Concurso
Organizadores: WeMakeDevs y DevTools Academy; tecnología patrocinadora Switch AI. Portal oficial: https://www.wemakedevs.org/hackathons/switch. No es lablab ni Devpost. Requiere repositorio público, README explicativo y video de demo real; el formulario de entrega está dentro de la experiencia de WeMakeDevs y no se verificó URL directo. Participante humano realiza envío (reglas prohíben bots). Inscripción previamente confirmada por correo WeMakeDevs.
Plazo: 3 Nov 2026 13:31 a 7 Nov 2026 13:29, Ecuador UTC-5. Kickoff 2 Nov 10:30 Ecuador. Premio Best Business Workflow USD 2000 anunciado. Ponderación DevTools Academy: Switch esencial 30%, reproducibilidad 25%, creatividad/impacto 25%, presentación 20%.

## Competencia pública, sin afirmaciones inventadas
No existe todavía una galería pública completa y verificable de proyectos finales en la categoría Business Workflow; el evento no ha empezado. En el repositorio oficial de Switch varios participantes están proponiendo conectores: PagerDuty #825, Grafana #826, Sentry #820, Notion #819. Son actividades del track de contribuciones al core; no equivalen a proyectos terminados o rivales confirmados. La propia web promocional y los docs de Switch ya muestran agentes diagnosticando incidentes y aprobaciones humanas, por lo que la idea original de cámara caída y reinicio simulado sería poco diferenciada.

## Posicionamiento ganador propuesto
InnerOS Incident Room — Verified Physical Operations. Un solo incidente de cámara sintético, pero con dos fuentes de evidencia independientes (estado cámara/NVR y observación de red), marcas de origen y frescura, hipótesis de causa y límites de certeza. La sala de Switch/Mattermost contiene al operador y a dos agentes: RalphiIA triage y FieldOps verifier. El primero investiga y propone, el segundo cuestiona/contrasta; la persona identificada aprueba o rechaza. La autorización se impone en código por actor, sala, correlación, expiración y rechazo de replay, no por instrucciones de prompt.
Tras aprobación se ejecuta únicamente un cambio sobre un fixture sintético, se comprueba con readback y se publica Evidence Receipt en el mismo hilo con origen, tiempo, decisión y hash SHA-256 de integridad (no firma criptográfica). Si falta información o readback falla, reportar UNKNOWN / UNVERIFIED, nunca éxito. Si Switch cae, se bloquea el flujo colaborativo; tests offline no suplen demo real.

## UniFi opcional, nunca requisito
Consulta interna al catálogo AG-60: UniFi existe como provider parcial con inventario, estado de puertos y PoE contemplados, pero requiere credenciales y NO se verificó acceso live. Dos capacidades de red disponibles son read-only: network.guardian.scan.v1 y network.communication.coverage.v1. Si hay permiso y la integración auténtica está saludable, usar una lectura real anonimizada como contraste; no tocar administración UniFi, no cambiar puertos, no publicar datos de clientes. Etiquetas obligatorias REAL / CAPTURED REAL / SYNTHETIC / UNKNOWN; nunca fusionar datos de redes distintas como si pertenecieran al mismo incidente real.

## MVP obligatorio para el período oficial
1. WebSocket para eventos y HTTP para operaciones; especificación vigente docs.switchagents.ai/switch-rooms/internals/agent-protocol. La portada del hackatón todavía menciona SSE, pero docs técnicas declaran SSE deprecated.
2. Mensaje real dirigido al agente y respuesta en una sala Switch/Mattermost autenticada.
3. Dos agentes con roles distintos, dos fuentes sintéticas y contexto/correlación compartidos.
4. Denegación, actor erróneo, sala equivocada, replay, caducidad y desconexión siempre bloquean cambios.
5. Solo aprobación correcta permite corrección sintética, readback independiente y recibo verificable en la sala.
6. Video real 2–3 minutos, clon limpio, CI y README. Medir latencia o pasos solo con datos reales del ensayo, no inventar reducción de MTTR.

## Opcionales si MVP funciona
UniFi read-only anonimizado; blog; segunda integración Telegram. No instalar nuevos servicios en AMD productivo ni depender de DevSwarm/Temporal.

## Fuentes
https://www.wemakedevs.org/hackathons/switch
https://www.wemakedevs.org/hackathons/switch/rules
https://www.wemakedevs.org/hackathons/switch/resources
https://www.devtoolsacademy.com/hackathons/flip-the-switch
https://docs.switchagents.ai/switch-rooms/internals/agent-protocol
https://docs.switchagents.ai/switch-rooms/use-cases/incident-response
https://github.com/sandbox-quantum/switch/releases/tag/switch-console-v0.40.1
https://github.com/sandbox-quantum/switch/issues/825
https://github.com/sandbox-quantum/switch/issues/826
https://github.com/sandbox-quantum/switch/issues/820
https://github.com/sandbox-quantum/switch/issues/819

Este documento es investigación, no prueba de que Switch esté desplegado ni de que el proyecto haya sido entregado.