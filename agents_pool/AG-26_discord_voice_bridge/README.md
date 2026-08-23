# AG-26 Discord Voice Bridge & SRE Local Command Agent

**Numeración:** AG-26 · **ID:** `AG-26_DISCORD_VOICE_BRIDGE`

Este agente modular y altamente replicable permite a cualquier usuario levantar un bot local de Discord que realice dos tareas críticas de manera desacoplada:

1. **Monitoreo & Puente de Notificaciones:** Escucha canales de Discord (ej. de hackatones, soporte) y despacha de manera segura alertas en tiempo real vía WhatsApp utilizando Evolution API.
2. **SRE Local Command Executor (Control Local por Ollama):** Recibe comandos de texto/voz del usuario administrador desde WhatsApp o Discord y, de forma local (usando un modelo ligero como `qwen2.5-coder:7b` en Ollama), decide qué tareas del sistema correr (ej. `"reinicio el docker de mongo"`, `"dame el estado de red"`). Esto evita consumir créditos externos de la API de Google y respeta la jerarquía local.

## 📁 Estructura del Agente
- Configuración: `config/agent.yaml` y `config/tasks.yaml`
- Lógica de Ejecución: `src/logic.py`
- Entorno de Configuración Segura: `.env.local`

## ⚙️ Configuración Desacoplada (Venta / Réplica Rápida)
Para replicar este agente en cualquier otro servidor o vendérselo a un tercero, solo se requiere configurar un archivo `.env` en la raíz del módulo:

```env
# Discord Settings
DISCORD_BOT_TOKEN=tu_token_de_discord_aqui
DISCORD_GUILD_ID=id_del_servidor
DISCORD_MONITORED_CHANNELS=canal1,canal2

# WhatsApp Notification Bridge
EVOLUTION_BASE_URL=http://localhost:8082
EVOLUTION_API_KEY=tu_api_key_de_evolution
EVOLUTION_INSTANCE=tu_instancia_whatsapp
NOTIFY_WHATSAPP_TO=tu_numero_celular_593...

# SRE Local Intelligence (Ollama)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5-coder:7b
```
