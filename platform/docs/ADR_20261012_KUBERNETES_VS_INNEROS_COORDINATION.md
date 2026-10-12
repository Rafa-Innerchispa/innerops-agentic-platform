# ADR propuesto: Kubernetes no sustituye la coordinación de InnerOS

**Fecha:** 2026-10-12  
**Estado:** propuesta técnica documentada, pendiente de ratificación por propietario si se decide desplegar K3s.  
**Alcance:** InnerOS, AMD `ralfiia-amd`, Intel `ralphi-ia-ver-10`, futuros nodos.
**Relación:** [Continuidad canónica](INNEROS_COORDINATION_CONTINUITY_20261012.md).

## Decisión inmediata

**Kubernetes NO es una dependencia obligatoria para resolver P0 de InnerOS.** No exigir instalar K3s ni otro cluster como condición nueva para aprobar la reparación, los canarios, la integración a main, la restauración de Dev Swarm o el cierre Temporal/Mongo. No instalarlo en los nodos productivos sin un plan explícito con permisos, pruebas, rollback y evidencia.

**Sí** evaluar K3s en fase posterior por disponibilidad, despliegues reproducibles, autorecuperación y ejecución de contenedores. Es un componente de infraestructura, **no** un sustituto de la semántica de tareas y agentes.

## Evidencia del repositorio a fecha de la decisión

No hay manifests Kubernetes/Helm/K3s versionados detectados en árbol GitHub main (1840 entradas al inspeccionar), aunque esto **no demuestra** ausencia en los hosts.
- `platform/infra/durable-spine/docker-compose.yml`: NATS y Temporal como servicios Docker.
- `platform/systemd/user/inneros-cursor-headless-autopilot.timer`: ejecución periódica systemd.
- `platform/scripts/deploy_platform_mirror_ha.sh`: deploy via ssh/rsync + systemd en AMD e Intel.
- Repositorio incluye lógica de Mongo, Temporal, LangGraph, MCP, scheduler Dev Swarm y binding por agente: no trasladarla a controladores K8s improvisados.

## Deslinde de responsabilidades

| Necesidad | Dueño actual/futuro |
| --- | --- |
| Orden, autorización y política de proveedor (Cursor, Codex, Antigravity, local) | InnerOS execution_binding / Capability Broker |
| Durable workflow, retries, idempotencia, gates y cierre | Temporal + Mongo y recibos verificables de cada executor |
| Ejecutor real + habilidad AMD/Skills + modelo AMD Qwen/Intel Ollama | Runner de cada proveedor, skills/allowlist y local_model_router |
| Liveness, reinicio de servicios, rollout, resources, pod placement | systemd + Docker hoy; posiblemente K3s después |
| Transporte de modelo, health `/v1/models` y fallback | Un único router local y su configuración real por nodo |
| Persistencia HA de Mongo y Temporal (backup/replicación) | Diseño separado de almacenamiento y consistencia |

Kubernetes puede reiniciar un worker atascado **solo si hay sondas adecuadas**. No inventa datos para completar los gates, no detecta por sí mismo que una skill no tiene adaptador, no corrige discrepancias de rutas, ni convierte un commit sin cambios en éxito. Jobs pueden reiniciar y por ello repetir ejecución: cada acción necesita idempotencia, fencing/leases y receipt.

## Por qué no migrar en mitad del P0

- Son dos nodos heterogéneos AMD ROCm/vLLM e Intel Ollama/Mongo; mover workloads sin compatibilidad de imagen/device-plugin/volúmenes podría cortar inferencia.
- Con dos nodos no se obtiene automáticamente quorum HA del control plane con etcd embebido; K3s recomienda al menos **tres** server nodes para control plane HA, o estudiar datastore externo.
- El almacenamiento Mongo actualmente en Intel puede ser un punto único de fallo si no está replicado; Kubernetes por sí solo no replica sus datos.
- Dos servidores Temporal instalados no equivalen necesariamente a **un único backend/historial compartido**; confirmar su topología antes de diseñar resiliencia entre nodos.
- Migrar ahora introduciría red CNI, secretos, almacenamiento y monitorización nuevos mientras hay tareas ya bloqueadas y dos implementaciones del router.

## Criterios para cerrar P0 SIN Kubernetes

1. Reconciliar trabajos previos y procesos huérfanos, sin doble ejecución ni `reset` destructivos.
2. Model route AMD/Qwen y fallback Intel/Ollama probados con endpoint real.
3. Dev Swarm local y Cursor headless AMD/Intel, canarios auténticos con artefactos, tests, receipts y estado Temporal/Mongo **terminal**.
4. Contrato único de ejecución/evidencia para Cursor, Codex, Antigravity, workers locales y read-only, respetando autorizaciones y transportes disponibles.
5. Código aprobado en GitHub main, CI PASS, runtime hashes y versión realmente cargada en ambos hosts; release reversible y sin romper servicios existentes.
6. Supervisor actual (systemd + Docker) recupera fallos de proceso conforme a leases/Temporal; ausencia de K8s **no es blocker**.
7. Reconcilia backlog selectivamente: validación por dependencia/autorización, evitando nuevas ejecuciones duplicadas.

## Evaluación K3s condicionada, sin fecha arbitraria

**Tras P0**, medir necesidad con incidentes reales (tiempo de recuperación de servicios, deriva de despliegues, carga, frecuencia de nuevos nodos y costes de mantenimiento). Si se justifica, probar K3s en sandbox/piloto no destructivo:
- Primero un worker sin estado y un servicio stateless; mantener Temporal/Mongo existentes hasta certificados.
- Readiness/liveness/startup probes reales, CPU/RAM/GPU quotas, node affinity (AMD GPU vs Intel CPU), límites de concurrencia por worker, Rollout/rollback e imágenes versionadas.
- Matriz de fallos: corte de un worker, reinicio de host, pérdida de modelo, red degradada, replay e idempotencia; demostrar que una tarea no se cierra si su evidencia no pasa el gate.
- Diseñar quorum control plane y HA de Mongo/Temporal antes de declarar que el cluster garantiza failover total. Si hay tercer servidor, evaluar su papel y coste; no asumir control plane HA con dos.
- Comparar eficacia y complejidad contra systemd/Docker antes de migrar servicios stateful o GPU.

**Regla contra cambios de objetivo:** ningún desarrollador puede reetiquetar Kubernetes como requisito oculto para cerrar una tarea P0. Si aparece una dependencia concreta, presentar el caso reproducible, por qué no basta con la infraestructura actual, y el cambio de alcance al propietario. No confundir conveniencia operativa con requisito técnico de ejecución.
