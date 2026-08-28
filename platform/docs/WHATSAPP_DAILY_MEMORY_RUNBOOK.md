# WhatsApp natural + Daily Life Memory

Estado técnico: desplegado en `192.168.1.4` y preparado para failover en
`192.168.1.5`. Cambio canónico: `2a33c0a`.

## Qué puede escribir Rafael

La conversación diaria no necesita nomenclatura. Texto, audio y foto entran al
mismo contexto conversacional.

Para delegar programación también se acepta lenguaje natural explícito:

```text
RalfIA, pídele a Codex que revise las pruebas del proyecto de cotizaciones
Necesito que Antigravity revise la documentación del MCP
Cursor, prepara un diagnóstico del webhook
```

La sintaxis compacta anterior continúa funcionando:

```text
codex[quoteops]: revisa las pruebas
cursor: revisa el webhook
```

`[quoteops]` selecciona el repositorio, no el modelo. En Codex la ejecución
sigue siendo de dos pasos: RalfIA crea una vista previa y solo comienza cuando
el mismo remitente autorizado responde `confirmar codex cj_...`.

## Flujo de conversación y memoria

1. Evolution API recibe el mensaje y emite `MESSAGES_UPSERT`.
2. El webhook guarda el evento saneado con `message_id`, `correlation_id`,
   `conversation_ref` y, cuando existe, `media_id`.
3. Un audio se normaliza con ffmpeg y se transcribe localmente. La voz del
   remitente autorizado puede usarse como petición.
4. Una foto se procesa localmente con Tesseract y visión local. OCR y visión se
   entregan únicamente como contexto no confiable; nunca se envían al router de
   comandos ni se ejecutan.
5. RalfIA responde con el modelo local y registra el intercambio en Daily Life
   Memory.
6. `finalize_conversation` ejecuta resumen, entidades, emociones, decisiones,
   pendientes, búsqueda de duplicados, construcción de memorias, Current State
   y Timeline.

Cada conversación de memoria usa un identificador hash por día y compartimento
de privacidad. No guarda el número en el ID. La evidencia multimedia guardada
excluye payload crudo y rutas locales.

## Privacidad

Los chats directos autorizados se guardan por defecto como
`PRIVATE_PERSONAL`. Reglas locales y deterministas separan salud/estado mental,
relaciones, familia y finanzas en sus respectivos `PRIVATE_*`.

El puente nunca selecciona `PUBLIC`, `PROJECT` ni `DEMO`. Los derivados de una
imagen tienen `derived_media_is_executable=false`. Los grupos no se copian a la
memoria personal por este puente.

## Seguridad del trabajo remoto

- Solo remitentes de la allowlist pueden iniciar comandos o trabajos de agente.
- Solo se reconocen Codex, Cursor/VS Code, Antigravity y Gemini.
- Codex solo puede usar proyectos de su allowlist y un worktree aislado.
- No hay shell arbitrario, `sudo`, lectura de credenciales ni despliegue directo.
- La confirmación queda ligada al remitente que creó el trabajo.
- Reinicios administrativos usan su propio flujo de confirmación.
- El OCR o el texto encontrado dentro de una foto jamás cuenta como aprobación.

## Arquitectura de los dos nodos

- `.4`: procesador canónico activo, MCP, portal y worker de trabajos.
- `.5`: Evolution API conectado y código idéntico preparado para failover.
- Ambas instancias Evolution envían al webhook canónico de `.4`.
- No se inicia un segundo worker en `.5`, para impedir doble consumo o doble
  ejecución. En una conmutación se cambia el webhook y se activa un solo worker.

## Pruebas reproducibles

```bash
cd /home/rlopez/projects/raphiia-openai
PYTHONPATH=. venv/bin/python -m unittest discover -q tests
set -a; source .env; set +a
PYTHONPATH=. venv/bin/python scripts/test_whatsapp_dlm_e2e.py
```

La prueba E2E usa exclusivamente `FIXTURE_WHATSAPP_DLM_E2E`, comprueba
idempotencia, pipeline, Current State, Timeline, búsqueda privada, rechazo de un
actor no autorizado y ausencia de promociones públicas. El bloque `finally`
elimina todas las fixtures.

## Prueba física pendiente

Desde el número autorizado de `.4`, enviar en este orden:

1. Texto: `RalfIA, pídele a Codex que revise las pruebas del proyecto de cotizaciones`.
2. Audio ficticio: `Hoy me siento motivado; esto es una prueba y no es un dato real`.
3. Foto sin datos personales, con el texto visible `FOTO FIXTURE RALFIA`.

No confirmar el trabajo Codex si solo se quiere validar enrutamiento. Para probar
la ejecución, responder con el identificador exacto que devuelva RalfIA.

## Rollback

Respaldos:

- `.4`: `/home/rlopez/data/backups/raphiia-openai/whatsapp-dlm-2a33c0a-20260719T0140Z`
- `.5`: `/home/rlopez/data/backups/raphiia-openai/whatsapp-dlm-2a33c0a-20260719T0135Z`

Restaurar los tres archivos existentes desde `raphiia_openai/`, eliminar
`whatsapp_daily_memory.py` porque el respaldo contiene
`NO_PREVIOUS_whatsapp_daily_memory`, y reiniciar los servicios afectados. En
`.4` basta `whatsapp-automation.service`; en `.5`, `ralfia-portal.service` y
`ralfia-mcp.service`.
