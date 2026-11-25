# Handoff para ChatGPT — cómo mandar tareas OPS (Antigravity / Codex / Cursor)

**Audiencia:** ChatGPT conectado al MCP InnerOS (RalfIA Small / `ralfia-mcp`).  
**Propietario:** Rafael. **Fecha:** 2026-11-25.  
**Estado:** Vigente con `execution_node` en `create_ops_task` (main, PR #291) y routing estricto Intel/AMD (PR #290).

---

## 1. Regla de oro

1. Crea la orden **solo** con la herramienta MCP **`create_ops_task`** (no simules ACK ni “tarea hecha” sin `task_id` en Mongo).
2. Indica **siempre** en qué máquina debe ejecutarse Antigravity/Codex: **`execution_node`** = `intel`, `amd` o `auto`.
3. Si no pasas `execution_node`, el sistema registra **`intel`** por defecto para Antigravity y Codex.
4. Rafael **debe autorizar** (PWA InnerOS / ntfy, Telegram o Alexa Atlas Control) antes del claim; tú no sustituyes esa aprobación.
5. No declares `completed` con `complete_ops_task` salvo que seas el ejecutor con evidencia real; el cierre lo hace el agente en el nodo correcto.

---

## 2. Nodos de ejecución

| Valor `execution_node` | Dónde corre el claim/ejecutor | Cuándo usarlo |
|------------------------|--------------------------------|---------------|
| `intel` (default) | Servidor Intel `ralphi-ia-ver-10` / 192.168.1.4 | Trabajo habitual Antigravity, repos ya en Intel, canarios push |
| `amd` | Servidor AMD `192.168.1.5`, `INNEROS_NODE_ROLE=amd` | Qwen, GPU, pruebas MSP en repo que debe correr en AMD |
| `auto` | Balanceo por slots libres (Intel vs AMD) | Solo si Rafael acepta que el sistema elija |

Con `intel` o `amd` explícito se activa **fail-closed**: el nodo equivocado **no** puede hacer claim (Intel no roba tareas AMD).

**Campos que quedan en Mongo** (para que reportes a Rafael):

- `target_execution_node`, `owner_execution_node`
- `payload.target_node`, `payload.owner_execution_node`, `payload.fail_closed_on_node_mismatch`

La respuesta de `create_ops_task` incluye `execution_node` y `execution_node_reason`; **léelos en voz alta** tras crear.

---

## 3. Firma MCP `create_ops_task` (campos útiles)

Obligatorios de facto:

- `assignee`: `antigravity` | `codex` | `cursor` | …
- `title`: título claro (incluir proyecto o correlación humana)

Recomendados para órdenes de desarrollo:

| Campo | Uso |
|-------|-----|
| `execution_node` | `intel` \| `amd` \| `auto` |
| `correlation_id` | ID humano único, ej. `msp-qwen-amd-20261125-A1` |
| `repo` | `Rafa-Innerchispa/nombre-repo` |
| `base_ref` | `main` |
| `objective` | Qué debe lograr el agente (1–2 párrafos) |
| `checklist` | Pasos verificables |
| `evidence_required` | ej. `git_commit`, `test_log` |
| `from_agent` | `chatgpt` |
| `preferred_provider` | igual que assignee si es IDE externo |
| `task_class` | `coding` (típico) |
| `execution_lane` | `antigravity_interactive` (Antigravity) |
| `do_not_auto_dispatch` | dejar default (true para IDE = espera autorización owner) |

**Evita** meter solo `target_node` dentro de `payload` si ya existe `execution_node`; usa el parámetro de primer nivel. El `payload` sigue válido para extras (`previous_task_id`, políticas de autonomía, etc.).

---

## 4. Plantillas de invocación

### Antigravity en AMD

```json
{
  "assignee": "antigravity",
  "preferred_provider": "antigravity",
  "title": "[AMD] Descripción corta del trabajo",
  "correlation_id": "TU-CORRELACION-UNICA",
  "repo": "Rafa-Innerchispa/inneros-autonomous-msp",
  "base_ref": "main",
  "execution_node": "amd",
  "execution_lane": "antigravity_interactive",
  "task_class": "coding",
  "from_agent": "chatgpt",
  "objective": "Objetivo concreto y acotado.",
  "checklist": [
    "Paso 1 verificable",
    "Paso 2 verificable"
  ],
  "evidence_required": ["git_commit", "test_log"]
}
```

### Antigravity en Intel (o sin decir nodo = Intel)

```json
{
  "assignee": "antigravity",
  "title": "[INTEL] Descripción",
  "correlation_id": "INTEL-AG-20261125-XXXX",
  "repo": "Rafa-Innerchispa/innerops-agentic-platform",
  "execution_node": "intel",
  "from_agent": "chatgpt"
}
```

O omitir `execution_node` → el sistema fija **intel**.

---

## 5. Qué reportar a Rafael después de crear

Copia este bloque (rellena con la respuesta MCP):

```text
Orden OPS creada
- task_id: ops_xxxxxxxxxxxx
- correlation_id: …
- execution_node (registrado): intel | amd
- execution_node_reason: create:explicit→… | create:default→intel
- assignee / modelo previsto: antigravity
- repo / base_ref: …
- Estado actual: queued → esperará autorización owner (push ntfy / PWA / Telegram / Alexa)
- Próximo paso humano: aprobar en InnerOS Owner; luego claim en el nodo indicado
```

Si `execution_node` en la respuesta **no** coincide con lo pedido, **detente** y no pidas a Rafael que apruebe hasta corregir.

---

## 6. Tarea vieja fallida vs tarea nueva

| Situación | Qué hacer desde ChatGPT |
|-----------|-------------------------|
| Tarea en **`failed`** por nodo incorrecto (ya autorizada una vez) | Preferible: **nueva** `create_ops_task` con `execution_node` correcto y nueva `correlation_id`. Alternativa operativa (agente local, no ChatGPT): reset/reclaim de la misma `task_id` en servidores. |
| Tarea **`completed` / `cancelled`** | Siempre **nueva** orden. |
| Repetir prueba limpia en historial | **Nueva** orden con correlación distinta. |

ChatGPT **no** debe asumir que “reintentar en chat” re-ejecuta Mongo; hace falta nueva admisión o scripts ops en el servidor.

---

## 7. Ciclo de vida que debes describir bien a Rafael

1. **create_ops_task** → `queued`, autorización pendiente.  
2. Rafael **aprueba** → `owner_authorized_at`; si el nodo es el otro servidor → push “esperando otro servidor” / `authorized_pending_peer`.  
3. **Claim** solo en el nodo con `target_execution_node` coincidente.  
4. **in_progress** → trabajo Antigravity/Codex.  
5. **completed** / **failed** + push ntfy “Terminada” o fallo.

Alexa: anuncio inicial + “ask Atlas Control for pending approvals” para la tarea concreta (referencia + sí/no + PIN Amazon). PWA InnerOS sigue siendo el canal más fiable.

---

## 8. Errores comunes (no repetir)

1. Crear tarea AMD sin `execution_node=amd` → default Intel y fallos de worktree.  
2. Aprobar en PWA y asumir ejecución en AMD sin ver `target_execution_node` en Mongo.  
3. Llamar `complete_ops_task` desde ChatGPT sin evidencia de ejecución real.  
4. Duplicar órdenes con el mismo `correlation_id` confuso (usa sufijos `-R1`, `-R2` en reintentos).  
5. Título sin contexto → Rafael no distingue en PWA ni en Alexa.

---

## 9. Consultas de solo lectura útiles

- `list_ops_tasks` (filtro `correlation_id` o `task_id`)  
- `get_coordination_live` al abrir sesión (revisión de coordinación)  
- No inferir despliegue por “CI verde en GitHub”; producción sigue política NOT_CERTIFIED hasta SHA/runtime verificado.

---

## 10. Opinión / criterio para ChatGPT

- **Default conservador:** `execution_node=intel` salvo que Rafael diga explícitamente AMD, Qwen, 192.168.1.5 o “solo GPU”.  
- **Una orden = un objetivo acotado** con checklist; no mezclar MSP + Alexa + deploy en una sola tarea.  
- **Transparencia:** siempre muestra `task_id`, `correlation_id` y `execution_node` devueltos por MCP.  
- **No gastar créditos Antigravity** en canarios enormes sin checklist; modelo pin lo fija el runtime (p. ej. Gemini 3.8 Flash Medium en `.env`), ChatGPT no cambia pin en caliente sin orden explícita de mantenimiento.

---

*Documento canónico en repo: `docs/CHATGPT_OPS_TASK_DISPATCH_20261125.md`. Sincronizar con Rafael si cambian PRs de routing o MCP.*