# ADR-018 | InnerOS multinodo: alta disponibilidad por capacidad

**Aprobado por owner:** 2026-10-10. **Correlación:** `inneros-ha-dual-node-rollout-20261010`. **Estado:** diseño y código candidato, despliegue y failover real NO certificados.

## Una plataforma, múltiples nodos

AMD e Intel son nodos elegibles del mismo InnerOS. Cada uno puede atender cargas compatibles con sus capacidades certificadas. La tercera máquina futura se incorpora por registro, política, inventario y pruebas, sin clonar a ciegas los servicios de un host.

| Dominio | AMD | Intel | Tercer servidor |
| --- | --- | --- | --- |
| Inferencia | vLLM GPU y Ollama local | Ollama y modelos adaptados | según benchmark |
| MCP stateless | elegible si health/auth | elegible si health/auth | tras preflight |
| Workers | si hay recursos y cola | si hay recursos y cola | tras preflight |
| Mongo, Temporal, NATS | NO declarar HA sin quorum y almacenamiento probado | NO declarar HA sin quorum y almacenamiento probado | candidato para quorum real |
| Servicios físicos/sesiones externas | no trasladar sin capacidad demostrada | no trasladar sin capacidad demostrada | no asumir equivalencia |

## Riesgos y hechos comprobados

- En la preflight 2026-10-10 AMD mostró vLLM, Ollama, procesos MCP y Temporal; puertos Mongo y NATS escuchaban. Es evidencia de procesos, **no** de almacenamiento replicado.
- Intel respondió en red y en una consulta Python. El probe completo de observabilidad devolvió `helper_returncode=126`; el proyecto registrado no mostró venv. No hay todavía demostración de un entorno de aplicación funcional ni de su inferencia en failover.
- El scheduler declaraba AMD primario, Intel secundario y cero workers. Configuración no es ejecución.
- El monitor anterior enviaba alertas y usaba elección de líder no atómica. El router de modelos ofrecía recuperación incompleta; el MCP devolvía URLs estáticas aunque ambos nodos fallaran.
- El conector `chatgpt_compact` actualmente permite lectura y trabajo Git aislado, pero no expone promoción y systemd host con autorización acotada. No sortear esta protección usando ejecución de tests o scripts de propósito general.

## Contratos

1. **Fail-closed:** un fallo de los dos nodos no genera dirección o PASS falso. Con uno sano se anuncia modo degradado y límites de capacidad.
2. **Inferencia local-first bidireccional:** AMD → Intel Ollama cuando sea compatible; Intel → AMD vLLM cuando sea compatible. AMD puede usar su Ollama local como alternativa; elegir el identificador real del modelo servido, sin remapeos inventados. Jamás escalar a LLM externo sin aprobación.
3. **Sin split-brain:** lease atómico en Mongo por dominio, bloqueo si la base o consenso no responde. El lease de alertas **no** sustituye quorum de datos, liderazgo Temporal, autenticación ni fencing de mutaciones.
4. **Mutaciones:** scope explícito a nodo/recurso/acción, idempotencia durable compartida, antes/después y rollback. Un health HTTP no es autorización de escritura.
5. **Independencia:** supervisor systemd fuera de MCP/Temporal, con acciones permitidas y recuperación verificable. Nunca usar la misma herramienta caída como única ruta de reparación.
6. **Una versión conocida:** SHA inmutable, backup por nodo, manifests sin secretos, CI, staging, hashes de runtime, canario real y rollback antes de `VERIFIED`.
7. **Tercer nodo:** evaluar tres miembros de datos para Mongo cuando el hardware lo permita, quorum NATS JetStream y almacenamiento durable HA para Temporal. No improvisar elección de primario en un clúster de dos nodos sin mayoría.
8. **Privacidad:** no abrir Ollama/vLLM a Internet ni incluir credenciales en Notion/GitHub. No usar redes de clientes para pruebas internas.

## Plan de aceptación y despliegue

1. Inventariar AMD/Intel por servicio, volúmenes, configuración no secreta, permisos, SHA y rutas locales/privadas.
2. Confirmar Intel ↔ AMD por salud de **modelo real** y de MCP autenticado; no basta TCP.
3. CI y tests negativos: fallo de Intel, AMD, ambos, Mongo, modelo sin inventario y elecciones simultáneas.
4. Staging en cada nodo, backup verificable, promoción acotada por manifest con autorización del owner, post-hashes y reversión.
5. Simular la caída **del servicio** sin apagar el host; verificar que el nodo superviviente responde con capacidad real, no que solo se manda WhatsApp.
6. Probar persistencia y recuperación de una tarea Temporal/Mongo. Si falla el dato, declarar `DEGRADED/WAITING`, no `COMPLETED`.
7. Validar supervisor independiente, asegurar una sola autoridad por estado y publicar Last Known Good. Medir RTO/RPO de pruebas, no inventar cifras.
8. Solo después planificar quorum con el tercer servidor y entrada pública independiente de un nodo.

**Estados separados:** `DOCUMENTED` / `CODED` / `TESTED` / `MERGED` / `STAGED` / `DEPLOYED` / `VERIFIED`. K3s/Argo CD quedan posteriores al Golden Flow.
