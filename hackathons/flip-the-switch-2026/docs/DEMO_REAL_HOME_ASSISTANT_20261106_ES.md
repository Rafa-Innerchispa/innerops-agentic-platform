# DEMO REAL: Switch + InnerOS MCP + Home Assistant + una luz fisica

**Actualizado 6 noviembre 2026. Esto es implementacion real disponible para ejecutar, NO evidencia de que el dispositivo haya cambiado estado.**

## Objetivo del video (2-3 minutos)

1. Un operador real escribe en una sala autentica Switch/Mattermost `!inneros` y ve un inventario del sitio real desde MCP de InnerOS. Si el MCP no esta configurado, NO mostrarlo como conectado.
2. El operador consulta `!lights` y `!state light.ENTIDAD` para leer el estado de una lampara fisica en Home Assistant. Se debe mostrar la misma entidad en la UI de Home Assistant, con una lectura actual.
3. El operador escribe `!propose light.ENTIDAD on` (o `off`, segun el estado actual) y recibe un action ID con expiracion.
4. `!deny HA-ID` demuestra bloqueo real sin enviar ninguna orden a Home Assistant. Aun mejor, mostrar segundo intento con operador incorrecto bloqueado.
5. Se propone de nuevo y se aprueba `!approve HA-ID` desde la cuenta humana autorizada. Una llamada REST a Home Assistant cambia UNA luz de verdad, y una lectura posterior confirma el estado. Mostrar el cambio de la bombilla en camara.
6. El agente devuelve `HA LIVE VERIFIED`, antes/despues, sello de tiempo y hash. Ese hash solo prueba integridad de los datos del recibo, no es firma ni evidencia optica.

## Arquitectura real

```
persona en Switch/Mattermost (Windows)
    -> agente Python Switch WS/HTTP en Windows
      -> !inneros: MCP Small (capability_invoke read_only)
      -> !lights / !state: GET Home Assistant en LAN
      -> !propose / !approve: policy en codigo (sala + operador + ID + plazo)
      -> SOLO luz autorizada: POST Home Assistant /api/services/light/turn_on|off
      -> GET Home Assistant /api/states/light.entidad (readback)
      -> respuesta al mismo room Switch
```

No se toca el router UniFi ni se instala infraestructura adicional en AMD/Intel. El agente solo accede desde Windows al HA accesible por Wi-Fi de casa. La conexion al modelo Qwen AMD es opcional para el video. No hace falta un switch Ethernet.

## Paso 1: identificar Home Assistant sin asumir la IP

En Windows, con la red de casa activa, abre HA en su navegador y confirma la URL. El nodo Intel reporto puerto 8123 escuchando, pero **eso no prueba que ahi exista una instalacion HA autenticada**. No supongas direcciones privadas.

Prepara en PowerShell (elige tu propia URL de HA):

```powershell
$env:HA_URL = "http://DIRECCION_HA:8123"
$sec = Read-Host "Introduce un token Home Assistant de tu cuenta (NO pegar en ChatGPT ni GitHub)" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
try { $env:HA_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
py -m pip install -e ".[switch]"
py scripts\discover_ha_lights.py
```

Usa un token de Home Assistant guardado de forma segura, dedicado a la demo si es posible. El token permite acceso a lo que autorice esa identidad; **no se puede asumir que sea de solo lectura**. Por eso el agente solo acepta una luz elegida explicitamente y protege las mutaciones en codigo.

## Paso 2: elegir una luz real no critica y conectar Switch

Despues de verificar que aparece `light.mi_luz_real` entre los dispositivos que responden (NO uno `unavailable`), configura SOLO esa entidad:

```powershell
$env:HA_ALLOWED_LIGHTS = "light.mi_luz_real"
$env:SWITCH_ROOM_ID = "ID_REAL_SALA"
$env:SWITCH_APPROVER_ID = "ID_REAL_OPERADOR"
# Primero leer y probar conexion sin cambios:
py scripts\run_live_homeassistant.py --doctor
```

Necesitas haber registrado nuestro agente con `scripts/register_agent.py`; las credenciales Switch son independientes y permanecen fuera del repositorio. Nunca publiques la clave de API.

## Paso 3: habilitar UNA accion fisica reversible

Con la luz seleccionada, confirmada y bajo observacion, permite la mutacion real:

```powershell
$env:HA_ENABLE_REAL_ACTIONS = "YES"
py scripts\run_live_homeassistant.py
```

No existe comando para cambiar switches/enchufes, cerraduras, alarmas, NVR, camaras ni control UniFi. La luz real se manipula unicamente con `!approve` de la cuenta Switch configurada. El sistema nunca ejecuta un `toggle` ambiguo.

## Paso 4: integrar InnerOS MCP (opcional, verificacion aparte)

El comando `!inneros` usa el SDK MCP v2 y llama **solo** `network.communication.coverage.v1` con `site_id=home_pcdoctor_lab`. Configura un acceso tokenizado a tu gateway MCP desde un almacen local; no reutilices ni pegues tokens de ChatGPT en el proyecto.

```powershell
py -m pip install -e ".[live]"
$env:INNEROS_MCP_URL = "https://mcp.pcdoctor.ai/router/mcp"
# INNEROS_MCP_TOKEN: obtener por medio del login/credenciales autorizadas de InnerOS.
# NO pegar ni guardar el token en GitHub, .env, consola grabada o video.
```

La verificacion en el chat debe indicar si la telemetria de InnerOS esta desactualizada. Al 6 nov el inventario tenia 90 dispositivos pero las lecturas de conectividad eran 53 STALE y 37 UNKNOWN, no 90 LIVE. Si el token no existe, `!inneros` responde explicitamente NO CONFIGURADO. Puede continuar la demo de Home Assistant real sin fingir MCP.

## Criterio de evidencia para el jurado

- Una sala Switch autentica y mensaje del operador con `addressed=true`.
- Lectura Home Assistant actual verificable, no screenshot de inventario antiguo.
- Luz real seleccionada, accion autorizada, nueva lectura del estado.
- Probar rechazo desde otro remitente y `!deny` sin cambio.
- Grabacion de la lampara o Home Assistant mostrando que paso de off a on (y opcion volver a off bajo nueva autorizacion).
- README/GitHub publico revisado sin tokens/IP privadas de tu hogar.

**Si la luz no cambia o el readback falla, la demo dice UNVERIFIED; nunca VERIFIED.**

## Validacion offline de seguridad

`PYTHONPATH=src python -m unittest discover -s tests -v` prueba la politica de autorizacion y el contrato de HTTP de HA contra un servidor de pruebas; no constituye evidencia de accionar un equipo real.