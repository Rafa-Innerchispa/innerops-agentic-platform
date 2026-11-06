# Wispr Flow + Switch + InnerOS: segundo premio opcional

Estado: 6 Nov 2026. Esta integracion de dictado por voz es opcional y no reemplaza la necesidad de demostrar un mensaje real en Switch, el control real de Home Assistant y la verificacion.

## Que es cada cosa

- Wispr Flow: convierte voz a texto en cualquier campo editable de Windows. Requiere Internet para transcribir. No es un agente ni una API de domotica. No instala componentes en AMD o Intel.
- Switch: sala Mattermost + transporte de mensajes a un agente de IA.
- RalphiIA / InnerOS: capa de IA y coordinacion, conectada por adaptador; debe comprobarse de verdad, no declararse solo por disponer del codigo.
- Home Assistant: API local que permite consultar y, tras autorizacion exacta, cambiar una entidad `light.*` especifica.

## Como entrar en Code with Wispr ($500)

La web oficial indica que el premio es para el mejor proyecto desarrollado usando Wispr Flow para dictar prompts, instrucciones de agentes y documentacion. La captura de Insights/Your usage se entrega al presentar el proyecto. Usarlo solo en una demostracion de voz no demuestra que el proyecto fue construido mediante dictado.

1. Abrir https://www.wemakedevs.org/hackathons/switch y reclamar 1 mes Pro mediante el enlace de Code with Wispr.
2. Instalar Wispr Flow en Windows. Iniciar sesion y permitir microfono. Configurar espanol (y, si conviene, ingles) como idiomas.
3. En Switch Console, enfocar la entrada del chat. Presionar y mantener el atajo de Wispr (en Windows suele ser Ctrl + Win; verificar en Settings), hablar y soltar. Revisar el texto antes de enviarlo.
4. Dictar con Wispr Flow instrucciones de sala, prompts a Codex/agent y texto del README. No atribuir a Wispr partes escritas de otra manera.
5. Abrir Wispr Flow > Insights > Your usage; guardar una captura autentica de las estadisticas de uso para el formulario final. No falsificar scorecard.
6. Si el Internet del telefono falla, detener el uso de Wispr; el proyecto de Home Assistant puede seguir funcionando localmente con instrucciones tipeadas.

## Frases habladas compatibles en el modo real de HA

Cuando el agente propio este registrado en una sala Switch y se haya autorizado una entidad real:

- `Que luces hay` => `!lights` (lectura)
- `Estado de light.luz_estudio` => `!state light.luz_estudio` (lectura)
- `Consulta InnerOS` => `!inneros` (lectura MCP, solo si existe token autorizado)
- `Propongo encender light.luz_estudio` => `!propose light.luz_estudio on` (solo propuesta)
- `Propongo apagar light.luz_estudio` => `!propose light.luz_estudio off` (solo propuesta)

`light.luz_estudio` es un EJEMPLO: sustituir por el ID exacto hallado con `scripts/discover_ha_lights.py`. Nunca inventar entidades. La frase `enciende todas las luces` NO se traduce en ninguna accion.

Por seguridad, pronunciar `aprobado` NO aprueba nada. La aprobacion exige que el operador humano copie o escriba `!approve HA-ID-EXACTO` en la misma sala, antes de que caduque. La cuenta, sala y entidad deben coincidir.

## Demostracion y grabacion

1. Comenzar grabando Switch real y la luz fisica.
2. Dictar con Wispr `Que luces hay` y mostrar resultado leido de HA, no inventario viejo.
3. Dictar `Propongo encender light.ENTIDAD_REAL`. Mostrar la solicitud de aprobacion.
4. Negar y mostrar que la luz sigue igual. Repetir propuesta, aprobar con ID exacto y mostrar cambio real mas readback.
5. Grabar un breve segmento dictando por Wispr un prompt y una seccion real del README; mostrar la captura de Insights al enviar la candidatura.

No grabar tokens, direcciones privadas, credenciales, ni datos de camaras o clientes. Una respuesta `HA LIVE VERIFIED` significa readback de HA; no sustituye verificar visualmente la lampara.

Fuentes: https://www.wemakedevs.org/hackathons/switch ; https://docs.wisprflow.ai/articles/2772472373-what-is-flow ; https://docs.wisprflow.ai/articles/8760230576-your-usage-tab-track-your-dictation-stats-in-wispr-flow