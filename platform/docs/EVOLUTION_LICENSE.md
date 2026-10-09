# Evolution Foundation — licencia en Intel (.4) y AMD (.5)

Desde **Evolution API 2.4.0+** hace falta activación **community (gratuita)** por instalación. Sin activar, la API responde **`503 LICENSE_REQUIRED`** (WhatsApp/MCP no envían).

Imagen fija en producción: **`evoapicloud/evolution-api:2.4.0-rc2`**.

## Qué productos cubre el registro

| Producto | Notas |
|----------|--------|
| Evolution API | Este despliegue (Baileys / instancias) |
| Evolution CRM | Activación aparte si lo instalas |
| Evolution Go | Activación aparte si lo instalas |
| Evo Nexus | Activación aparte si lo instalas |

Cada **servidor** (Intel y AMD) es una **instancia distinta** → **dos activaciones** (mismo email, dos `instance_id`).

## Datos fijos (LAN)

| Nodo | LAN | Manager | `SERVER_URL` |
|------|-----|---------|----------------|
| Intel | `192.168.1.4` | http://192.168.1.4:8082/manager | http://192.168.1.4:8082 |
| AMD | `192.168.1.5` | http://192.168.1.5:8082/manager | http://192.168.1.5:8082 |

**API key global** (login manager + header `apikey`): la de `AUTHENTICATION_API_KEY` / `EVOLUTION_API_KEY` en compose y `platform/.env` (`swarm_os_evolution_key_2026`).

Debes estar en la **misma red LAN** (o VPN que enrute a `192.168.1.x`). No uses Tailscale como URL de activación.

## Paso A — Primera activación (Intel, recomendado)

1. Abre **http://192.168.1.4:8082/manager/login**
2. Inicia sesión con la **API key global**.
3. Si la licencia está `inactive`, el manager te redirige al portal Evolution Foundation.
4. Completa el registro con **tu correo** (magic link u OAuth).
5. Vuelves a `/manager/license/callback` y la instancia queda **`active`**.

Comprobar:

```bash
curl -sS http://192.168.1.4:8082/license/status
# {"status":"active", ...}
```

## Paso B — Segunda activación (AMD)

Opción **manual** (igual que Intel):

1. **http://192.168.1.5:8082/manager/login** → mismo correo → activar.

Opción **auto** (mismo email ya registrado en paso A):

1. En `evolution-amd.docker-compose.yaml` (servicio `evolution-api-amd`) añade:

   ```yaml
   - EVOLUTION_OPERATOR_EMAIL=tu@correo.com
   ```

2. Recrea el contenedor y revisa logs; o usa el script:

   ```bash
   EVOLUTION_OPERATOR_EMAIL=tu@correo.com \
     /home/rlopez/inneros/inneros_core/platform/scripts/evolution_license_auto_amd.sh
   ```

Documentación upstream: [Auto-activation by email](https://docs.evolutionfoundation.com.br/en/licensing/auto-activation).

## Estado e IDs de instancia

```bash
/home/rlopez/inneros/inneros_core/platform/scripts/evolution_license_status.sh both
```

## Volver atrás (solo emergencia)

Pin **`evoapicloud/evolution-api:v2.3.7`** en compose y `docker compose up -d --force-recreate` (sin licencia; pierdes requisitos 2.4).

## Referencias

- [Licensing & activation](https://docs.evolutionfoundation.com.br/en/licensing)
- [Activation flow](https://docs.evolutionfoundation.com.br/en/licensing/activation)
- Upgrade contenedores: `scripts/upgrade_evolution_api.sh both` (respeta `EVOLUTION_IMAGE`).
