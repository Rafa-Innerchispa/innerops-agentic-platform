# Meta Model API como proveedor GLOBAL de InnerOS
**Auditoría:** 2026-11-01 | **Owner:** InnerChispa LLC | **Estado:** implementado en código, NO desplegado aún.

## Arquitectura: el hackathon es consumidor, no dueño de la API

El repositorio del hackathon `Rafa-Innerchispa/inneros-meta-guardian-2026` no será el propietario de la API key, créditos, adaptadores compartidos ni políticas de inferencia.

El núcleo `innerops-agentic-platform` YA dispone de:
- `platform/inneros_core_runtime/resource_fabric.py`: registro y selección de proveedores.
- `platform/inneros_core_runtime/local_model_router.py`: inferencia local AMD vLLM / Intel Ollama primero.
- `platform/inneros_core_runtime/owner_vault.py`: bóveda cifrada y reusable.
- `platform/inneros_core_runtime/funding_registry.py`: programas, cuentas de crédito, consumos y vínculos de proyectos.
- `platform/inneros_core_runtime/provider_onboarding_plane.py`: contratos genéricos de proveedores.

### Implementación nueva en Core
- `platform/inneros_core_runtime/meta_model_provider.py`.
- `PROVIDER_ID=meta-model-api`, modelo `muse-spark-1.3`, endpoint oficial `https://api.meta.ai/v1/responses`.
- Credencial central y única: `owner_vault:model_api_provider/meta_model_api_key`.
- Registro nativo en `resource_fabric.py` con `resource_provider_document()` y `model_provider_document()`.
- Ruteo preferido: local AMD/Intel. Meta **solo** con capability `frontier_reasoning` o `specialized_external_reasoning` solicitada con `prefer_cloud=true` y permiso separado. La elegibilidad de ruteo nunca constituye autorización para gastar.
- `MetaGrantLedger`: SQLite transaccional con grant único vinculado a proyecto, modelo, presupuesto, hash exacto del prompt y referencia de aprobación verificada. Consumo atómico antes de red, persistente entre procesos, rechazo de replay y cero retries.
- `invoke_with_grant`: API Python interna para cualquier proyecto. Recibo con estado, proveedor, tokens reportados, latencia, HTTP, IDs reales, huellas SHA-256. No persiste secreto, prompt o texto completo en el ledger. No inventa costos.
- Al inicio se permite **solo** input `SYNTHETIC` que comienza por `FICTIONAL LAB DATA ONLY:`. Datos reales requieren implementar un data-release gate que verifique autorización y minimización. No hay endpoint web/MCP público para gastar; no añadirlo sin autenticación.
- Modelo SAM 3.1: todavía no está implementado realmente en el proveedor central, y el código visual del hackathon sigue etiquetado como fixture.

### Patrón de consumo compartido

```python
from inneros_core_runtime import resource_fabric, meta_model_provider

# Consulta de catálogo, sin gasto:
catalog = resource_fabric.bootstrap_global_resource_fabric(dry_run=True)
meta = meta_model_provider.resource_provider_document()
models = meta_model_provider.model_provider_document()

# La emisión real exige prueba HA validada.
# ledger = meta_model_provider.MetaGrantLedger()
# grant = ledger.issue(..., verifier=verificador_real_ha)
# result = meta_model_provider.invoke_with_grant(
#     ledger=ledger, grant_id=grant["grant_id"],
#     project_id="inneros-meta-guardian-2026", prompt=prompt_sintetico)
```

No usar un `verifier=lambda True` en producción. El nuevo proveedor es un motor compartido que se conecta al verificador real de Home Assistant antes de uso productivo.

## Créditos, alcance de la promoción y privacidad

Captura Billing del propietario (1-nov): US$150 de créditos GRATUITOS ACTIVO, cuenta corriente adeudada US$0, falta método de pago. El owner dice haber creado una API key, pero no aparece recibo auténtico de la llamada de prueba en GitHub.

**No asumir** que los US$150 completos siguen disponibles o que los términos del programa autorizan gastarlos fuera del hackathon. Los créditos se asignan a la cuenta Meta y su uso depende de condiciones y restricciones promocionales verificables. Registrar en `funding_registry` UNA cuenta de proveedor Meta y enlazar proyectos; no crear una billetera por hackathon. No inventar balance restante: recuperar saldo/uso real del panel.

Cuando se usan créditos gratuitos, Meta advierte que el contenido puede emplearse para mejorar productos: no enviar datos privados, IP, memorias completas, incidentes de clientes ni topologías a este proveedor. La clasificación `SYNTHETIC` es la única habilitada en el código nuevo.

## Aceptación necesaria antes de decir que funciona para toda la empresa

| Requisito | Estado |
| --- | --- |
| Proveedor Meta en núcleo Resource Fabric | Código commit preparado |
| Tests de seguridad del ledger | Añadidos; CI pendiente de revisión |
| API key guardada solo en owner_vault | No confirmado en servidor |
| Verificador real HA y permisos por proyecto | Falta conectar |
| Prueba real de Meta desde Antigravity | Sin recibo visible en GitHub |
| Cuenta Meta en funding_registry y Usage | Sin registro confirmado |
| Gateway MCP/REST autenticado para consumidores | No expuesto todavía |
| Producción AMD/Intel | No modificada |

## Siguiente entrega inmediata para Antigravity

1. En IDE, recuperar el resultado de `docs/META_API_FIRST_RUN_20261101.md` del repo privado del hackathon: código HTTP, model/response ID real, input/output/total tokens, latencia, error 402 si ocurrió, archivos privados, cero secretos. No marcar COMPLETED solo por cerrar la tarea.
2. Revisar `meta_model_provider.py` y CI offline, luego registrar el proveedor mediante bootstrap dry_run. No reiniciar ni modificar servicios de producción.
3. Importar la clave Meta al owner_vault mediante entrada segura local, sin guardarla en el repo ni en chat.
4. Integrar permisos reales de propietario HA para usar `MetaGrantLedger.issue` y validar replay, scopes, cuotas y error de facturación. No agregar HTTP público para generarlo.
5. Vincular proyecto Meta y otros consumidores al Resource Fabric y el registro de créditos. Usar Meta únicamente donde la licencia/promoción permita el caso.
6. Convertir el demo hackathon en cliente del core, en vez de mantener una copia independiente del proveedor; preservar la API local del demo con rutas Meta anónimas BLOQUEADAS.
7. Preparar video con evidencias reales y entregar Cerebral Valley antes 2026-11-04 21:00 Ecuador.

**Fuentes:** documentación de Meta https://dev.meta.ai/docs/protocols/responses , condiciones https://dev.meta.ai/legal/terms-of-service , Billing https://dev.meta.ai/help/billing/set-up-billing .

No hubo reinicios, cambios de DNS, despliegue ni gasto de créditos por estos commits.