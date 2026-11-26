# Prompt ChatGPT — prueba dual Antigravity Intel + AMD (Alexa + notify)

Pega **todo** el bloque siguiente en ChatGPT (MCP InnerOS conectado). Debe ejecutar **dos** llamadas `create_ops_task` en la misma sesión.

---

## BLOQUE PARA CHATGPT

Eres el coordinador InnerOS de Rafael. Usa **solo** la herramienta MCP `create_ops_task` (nunca simules resultados). Después de cada creación, muestra en chat: `ok`, `task_id`, `correlation_id`, `execution_node`, `execution_node_reason`.

**Reglas obligatorias**

1. `assignee` y `preferred_provider`: `antigravity`
2. `from_agent`: `chatgpt`
3. `execution_lane`: `antigravity_interactive`
4. `task_class`: `coding`
5. `do_not_auto_dispatch`: true (espera autorización owner)
6. `repo`: `Rafa-Innerchispa/innerops-agentic-platform`
7. `base_ref`: `main`
8. Cada tarea lleva **`correlation_id` distinta** (nunca reutilizar una vieja)
9. Tras crear las dos, confirma que Rafael debe recibir **dos pushes ntfy/PWA** y aprobar cada una por separado

### Tarea A — Antigravity en **Intel**

- `execution_node`: **`intel`**
- `correlation_id`: `CHATGPT-AG-INTEL-ALEXA-20261126-A`
- `human_task_id`: mismo valor que `correlation_id`
- `title`: `[Competencia/Externo/ANTIGRAVITY] Alexa · servidor INTEL · agente Antigravity`
- `objective`: Compétition Alexa: tras autorización y claim en Intel, anunciar por Home Assistant/Echo la frase del payload. Sin trabajo de repo; solo anuncio verificable.
- `checklist`:
  - Registrar nodo objetivo intel en respuesta MCP
  - Esperar autorización owner y claim en ralphi-ia-ver-10
  - Ejecutar lane competencia y anuncio Alexa
- `payload` (JSON):
  ```json
  {
    "interaction_mode": "autonomous",
    "competition_announce_phrase": "Hola Rafael. Esta tarea Antigravity se ejecuta en el servidor Intel. El agente es Antigravity.",
    "alexa_announce_phrase": "Hola Rafael. Esta tarea Antigravity se ejecuta en el servidor Intel. El agente es Antigravity."
  }
  ```

### Tarea B — Antigravity en **AMD**

- `execution_node`: **`amd`**
- `correlation_id`: `CHATGPT-AG-AMD-ALEXA-20261126-B`
- `human_task_id`: mismo valor que `correlation_id`
- `title`: `[Competencia/Externo/ANTIGRAVITY] Alexa · servidor AMD · agente Antigravity`
- `objective`: Igual que A pero el claim debe ocurrir en AMD (192.168.1.5), fail-closed; anuncio Alexa con frase del payload.
- `checklist`: igual estructura que A, citando AMD
- `payload`:
  ```json
  {
    "interaction_mode": "autonomous",
    "competition_announce_phrase": "Hola Rafael. Esta tarea Antigravity se ejecuta en el servidor AMD. El agente es Antigravity.",
    "alexa_announce_phrase": "Hola Rafael. Esta tarea Antigravity se ejecuta en el servidor AMD. El agente es Antigravity."
  }
  ```

**Al final**, resume para Rafael:

| Correlación | task_id | Nodo | Siguiente paso |
|-------------|---------|------|----------------|
| …-A | ops_… | intel | Aprobar en PWA/ntfy → escuchar Alexa Intel |
| …-B | ops_… | amd | Aprobar en PWA/ntfy → claim en .5 → escuchar Alexa AMD |

No llames `complete_ops_task` desde ChatGPT.

---

## Rafael — checklist después del prompt

1. Cola e historial owner **ya reseteados** en servidor (bandeja vacía).
2. En el celular: borra notificaciones viejas del topic `ralfia-owner-ops` si quedaron (ntfy: mantener pulsado → borrar).
3. Aprobar **primero una**, esperar Alexa + historial “Terminada”; luego la otra.
4. Si no llega push: pedir a ChatGPT el `task_id`; sin `task_id` la orden no se creó.