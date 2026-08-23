# vero_commercial_orchestrator (AG-38)

**Vero** — orquestadora comercial PC Doctor.

## Aliases
`vero`, `facturador`, `facturadora`, `comercial`

## Delegación
| Intención | Agente | Rol |
|-----------|--------|-----|
| Cotización | AG-16 | COT `PCD-COT-*` |
| Facturación | AG-17 | FAC Contifico/SRI |
| Firma SRI | AG-10 | XML XAdES-BES |
| Cobros | AG-18 | Post-factura |
| Informe técnico | AG-13 | Inspección / supervisor |
| CRM | AG-14 | Clientes |

## Ejemplos
```
dile a Vero que cotice a FEMAR
dile a Vero que facture a Cafecom PCD-COT-2026-08-002
dile a Vero que haga informe técnico de Bellini
```

MCP: `vero_dispatch`, `quote_client`, `invoice_client`, `technical_report_client`
