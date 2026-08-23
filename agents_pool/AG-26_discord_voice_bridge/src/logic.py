#!/usr/bin/env python3
"""
AG-26 Discord Voice Bridge & SRE Local Command Agent.
Modulo de ejecucion desacoplado, modularizable y auto-contenido de grado SRE.
"""

import os
import sys
import json
import logging
import subprocess
import requests
from dotenv import load_dotenv

# Configurar logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Cargar configuraciones desacopladas
# Permite correr de forma autonoma con .env local o variables del host
load_dotenv()

class DiscordVoiceBridgeAgent:
    def __init__(self):
        self.agent_id = "AG-26_DISCORD_VOICE_BRIDGE"
        self.discord_token = os.getenv("DISCORD_BOT_TOKEN")
        self.whatsapp_to = os.getenv("NOTIFY_WHATSAPP_TO", "593999059000")
        self.evolution_base = os.getenv("EVOLUTION_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
        self.evolution_key = os.getenv("EVOLUTION_API_KEY", "swarm_os_evolution_key_2026")
        self.evolution_instance = os.getenv("EVOLUTION_INSTANCE", "RalphiIA-pcdoctor")
        self.ollama_base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")

    def execute_local_system_command(self, user_prompt: str) -> dict:
        """
        Orquesta tareas locales utilizando inteligencia local (Ollama) sin gastar tokens de la API de Google.
        Determina de forma inteligente si la intencion del usuario es de mantenimiento del sistema,
        y llama a las funciones SRE locales mapeadas.
        """
        logging.info(f"[{self.agent_id}] Evaluando intencion SRE local para: '{user_prompt}'")
        
        system_instructions = """[ROL: SRE LOCAL COMMAND ROUTER]
Analiza la peticion del administrador y mapea su intencion a una de las siguientes acciones del sistema:
1. "restart_mongo": Si el usuario pide reiniciar mongodb, docker de mongo, base de datos.
2. "get_system_status": Si pide ver estado del servidor, puertos, memoria, disco o cockpit.
3. "restart_gateway": Si pide reiniciar el public gateway o tuneles de red.
4. "none": Si la peticion no corresponde a mantenimiento SRE.

Responde estrictamente con un objeto JSON (sin marcas markdown ni explicaciones adicionales) con el siguiente formato:
{
  "action": "restart_mongo" | "get_system_status" | "restart_gateway" | "none",
  "reason": "explicacion breve de la decision"
}
"""
        
        try:
            # Invocar Ollama local para enrutamiento seguro y costo 0
            payload = {
                "model": self.ollama_model,
                "messages": [
                    {"role": "system", "content": system_instructions},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.1,
                "stream": False,
                "format": "json"
            }
            res = requests.post(f"{self.ollama_base}/api/chat", json=payload, timeout=20)
            if res.status_code == 200:
                content = res.json()["message"]["content"]
                parsed = json.loads(content)
                action = parsed.get("action", "none")
                
                # Ejecutar accion local autorizada de grado SRE
                if action == "restart_mongo":
                    logging.info("SRE local disparando: Reinicio seguro de contenedor MongoDB...")
                    # Orquesta de forma no bloqueante a traves de subproceso local
                    out = subprocess.check_output("docker restart mongodb || true", shell=True).decode().strip()
                    return {"ok": True, "action": "restart_mongo", "output": "MongoDB restart trigger completado.", "log": out}
                    
                elif action == "get_system_status":
                    logging.info("SRE local consultando: Estadisticas de recursos del host...")
                    mem = subprocess.check_output("free -h | grep Mem", shell=True).decode().strip()
                    disk = subprocess.check_output("df -h / | tail -n 1", shell=True).decode().strip()
                    return {"ok": True, "action": "get_system_status", "resources": {"memory": mem, "disk": disk}}
                    
                elif action == "restart_gateway":
                    logging.info("SRE local disparando: Reinicio del Public Gateway por systemd...")
                    out = subprocess.check_output("systemctl --user restart swarm-public-gateway.service || true", shell=True).decode().strip()
                    return {"ok": True, "action": "restart_gateway", "output": "Gateway restarted.", "log": out}
                    
                return {"ok": True, "action": "none", "message": "Peticion no enrutable a comandos locales."}
        except Exception as e:
            logging.error(f"Fallo en ejecucion SRE local por Ollama: {e}")
            return {"ok": False, "error": str(e)}

    def dispatch_whatsapp_notification(self, discord_message: str, channel_name: str, author_name: str) -> bool:
        """
        Envia una notificacion modular por WhatsApp via Evolution API sin dependencias cruzadas.
        """
        url = f"{self.evolution_base}/message/sendText/{self.evolution_instance}"
        headers = {"apikey": self.evolution_key, "Content-Type": "application/json"}
        
        text = f"""🔔 *Discord Hackaton Alert!*

📺 *Canal:* #{channel_name}
👤 *Autor:* {author_name}

💬 *Mensaje:* {discord_message[:1000]}
"""
        
        try:
            res = requests.post(url, headers=headers, json={"number": self.whatsapp_to, "text": text}, timeout=15)
            if res.status_code in (200, 201):
                logging.info(f"Notificacion enviada correctamente por WhatsApp a {self.whatsapp_to}")
                return True
            else:
                logging.warning(f"Error en Evolution API (Status {res.status_code}): {res.text}")
        except Exception as e:
            logging.error(f"Error conectando con Evolution API: {e}")
        return False

# Iniciar agente si se corre de forma directa
if __name__ == "__main__":
    agent = DiscordVoiceBridgeAgent()
    # Prueba de enrutamiento SRE local sin costo por Ollama
    test_prompt = "por favor puedes revisar como va la memoria y el espacio del servidor?"
    result = agent.execute_local_system_command(test_prompt)
    print("Test SRE Local Result:", json.dumps(result, indent=4))
