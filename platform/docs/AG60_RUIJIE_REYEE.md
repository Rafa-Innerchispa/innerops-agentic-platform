# AG-60 Ruijie / Reyee (Ruijie Cloud)

Reyee (marca SMB) se gestiona con **Ruijie Cloud** — misma API northbound que Ruijie enterprise.

## MCP

| Tool | Uso |
|------|-----|
| `ruijie_reyee_full_snapshot` | APs, switches, gateways, clientes online, puertos switch/gateway |
| `ruijie_reyee_network_ops` | Diagnóstico + probe LAN (Bellini: `192.168.3.172` Easy-Smart) |
| `ruijie_reyee_api_capabilities` | Qué lee InnerOS y qué credenciales faltan |

## Credenciales

1. Solicitar **appid + secret** a `service_rj@ruijienetworks.com` (cuenta cloud, país, propósito API).
2. Configurar:

```bash
RUIJIE_CLOUD_BASE_URL=https://cloud.ruijienetworks.com
RUIJIE_CLOUD_APP_ID=...
RUIJIE_CLOUD_SECRET=...
RUIJIE_CLOUD_ACCOUNT=...    # email cloud
RUIJIE_CLOUD_PASSWORD=...
RUIJIE_CLOUD_GROUP_ID_BELLINI=...   # buildingId del sitio (opcional)
```

O **owner_vault** categoría `ruijie_reyee`: `app_id`, `secret_key`, `account`, `password`.

Documentación oficial: [Ruijie Cloud API Help](https://cloud.ruijienetworks.com/help/#/ArticleList?id=7e875942927f4e3fb3e5736c8502c03c)

## Bellini

Inventario live previo: switch **Ruijie Easy-Smart** en **192.168.3.172** (web azul Ruijie). Cloud API lista el mismo proyecto de red que uses en la app Reyee/Ruijie.
