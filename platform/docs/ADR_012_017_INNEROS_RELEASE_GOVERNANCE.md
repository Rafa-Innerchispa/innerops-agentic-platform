# ADR-012–017 | InnerOS: entrega confiable y Last Known Good

**Aprobado por owner:** 2026-10-10  
**Estado:** política aprobada; despliegue de control de versiones y Golden Flow pendiente de certificar.  
**Fuente de decisiones:** [Ledger de InnerOS](https://app.notion.com/p/eb8bb67ca63b4dfba5c34e35b92ae173).  
**Correlación:** `inneros-last-known-good-release-20261010`.

## D-012 · Promoción única a producción

Desarrollar en ramas/worktrees aislados y usar `origin/main` como referencia. Exigir CI satisfactoria, contratos, pruebas reproducibles, versión inmutable por SHA, staging, respaldo, healthchecks en vivo y rollback antes de aceptar producción. **La fusión de Git no es despliegue.** Reutilizar el módulo existente `runtime_file_promotion.py`, sin sobreescritura indiscriminada de configuración, secretos o datos.

## D-013 · Freeze selectivo y preservación

No iniciar características no críticas hasta certificar Golden Flow. Inventariar ramas y recuperar trabajo útil por evidencias, pruebas y SHA; no fusionar todas las ramas ni borrar el trabajo sin clasificación. Preservar lo que funciona en un registro Last Known Good.

## D-014 · Supervisor fuera del orquestador

Un controlador de host independiente de MCP/Temporal debe verificar procesos, dependencias y recuperación. No depender de un worker o MCP averiado para repararlos. Permisos mínimos y acciones reversibles con auditoría.

## D-015 · Contrato estricto de finalización

`COMPLETED` requiere ejecución real, correlación, worker, SHA/artefacto, pruebas, estado de servicio, historial Temporal/Mongo y verificación de rollback. Una respuesta de un modelo, una tarea `running` o un PR fusionado no bastan. Sin evidencia: `BLOCKED`/`FAILED`.

## D-016 · Evaluación posterior de K3s y Argo CD

Primero cerrar promoción segura con systemd y servicios existentes. Solo después de Golden Flow evaluar K3s/Argo CD con un componente secundario y medición de rollback/recuperación, sin migración abrupta de vLLM/ROCm, PBX ni Home Assistant.

## D-017 · Local-first y aislamiento por sitio

AMD/Intel locales prioritarios; no gastos externos sin autorización específica. Casa: AG-60 continuo tras certificación; Bellini: diagnósticos bajo demanda. No modificar infraestructura de terceros ni almacenar credenciales en Git, Notion o logs.

## Orden de ejecución P0

1. **Preflight:** inventariar SHA efectivo, servicios, datos, dependencias, copias y configuración de AMD/Intel; capturar una baseline viva.
2. **Quality gate:** proteger main con comprobaciones obligatorias, CI, contratos y revisión; si la integración carece de permisos administrativos, reportar bloqueo exacto.
3. **Versionar y preservar:** generar manifiesto Last Known Good con hashes de código, configuración no secreta y restauración comprobable; mantener releases y respaldos fuera del runtime mutable.
4. **Promoción y canario:** desplegar candidato en staging, verificar MCP/Temporal/Mongo/NATS/worker, publicar con rollback; ejecutar orden → despacho → ejecución → persistencia → cierre.
5. **AG-60:** activar únicamente tras preflight los timers domésticos, verificar dos ciclos y las alertas; Bellini se mantiene bajo demanda.

**Regla final:** separar siempre `DOCUMENTED`, `CODED`, `TESTED`, `MERGED`, `DEPLOYED`, `VERIFIED`. Solo `VERIFIED` certifica producto operativo. Este archivo documenta decisiones, no reclama que el runtime haya sido actualizado.
