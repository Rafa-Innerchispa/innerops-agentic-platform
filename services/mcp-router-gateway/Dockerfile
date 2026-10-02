FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md profiles.json ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV MCP_ROUTER_HOST=0.0.0.0
ENV MCP_ROUTER_PORT=8250
ENV MCP_ROUTER_PROFILE=chatgpt_compact
ENV MCP_ROUTER_PROFILES=/app/profiles.json

EXPOSE 8250
CMD ["mcp-router-gateway"]
