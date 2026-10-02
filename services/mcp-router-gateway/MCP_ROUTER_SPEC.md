# Especificacion Tecnica: MCP Router & Tool Throttling Gateway

## 1. Objetivo

Interponer un proxy ligero MCP Gateway entre clientes MCP y un servidor MCP monolitico con muchas herramientas. El gateway intercepta `tools/list`, expone solo herramientas permitidas por perfil y valida `tools/call` antes de reenviar al backend.

## 2. Estrategia

- Mantener el servidor MCP actual intacto en su puerto actual.
- Ejecutar este router en un puerto distinto.
- Apuntar ChatGPT/agentes al router.

## 3. Comportamiento

- `initialize`: se reenvia al backend real.
- `tools/list`: se consulta al backend y se retorna solo la lista filtrada.
- `tools/call`: se valida que la herramienta este permitida y luego se reenvia.
- Metodos no interceptados: se reenvian sin modificar.

## 4. Seguridad

- Una tool no permitida devuelve error JSON-RPC `ToolNotAllowedError`.
- Las tools sensibles pueden pasar por politicas de sandboxing basicas:
  rutas bajo raices permitidas y banderas read-only cuando aplique.

## 5. Futuro

El router puede evolucionar a agregador de micro-MCPs por prefijo, por ejemplo:

- `mcp-gitlab`
- `mcp-infra-docker`

