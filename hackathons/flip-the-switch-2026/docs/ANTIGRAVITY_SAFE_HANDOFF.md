# Narrowly scoped Antigravity helper (optional, not a dependency)

Context: InnerOS Incident Room, Flip the Switch Hackathon 2026. Deadline 7 Nov 13:29 Ecuador.
The assistant has independently authored code, mock transport tests and documentation. **Do not create another DevSwarm/Temporal/agent loop.** Local execution and local models first. Stop at scope boundaries.

If AntiGravity is directly available on the owner's Windows PC, its ONLY permitted work is:
1. Inspect the two Wi-Fi adapters read-only: phone hotspot for internet, home Wi-Fi for authorized access to AMD 1.5 / Intel 1.4 by their **actual full local IPs**. Do not alter routing, Wi-Fi profiles, DNS, DHCP, UniFi, firewall or physical switches.
2. Inspect local Switch Console installation status and `http://127.0.0.1:8000/health` read-only. If absent, assist with official user-guided installation on an isolated Windows host; do not deploy into existing AMD/Intel production containers.
3. Execute `python -m unittest discover -s tests -v` and `scripts/preflight.py` in the project extracted from the archive. Install optional websockets only in a dedicated virtual environment.
4. If the human user has created a Switch Gateway registration key, help register the demo agent with `scripts/register_agent.py`. Never print, paste in chat, or commit tokens. Do not register or submit the competition entry as a bot.
5. Capture evidence as concise statements only: Python test count, Switch server version and `/health`, whether real room response is verified, whether a human saw it, and exact blocking action. No fake completion claims.
6. Send code changes via an isolated feature branch only, with explicit SHA. Do not force-push or alter InnerOS production. Never spend paid external model credits or schedule background retries.

If credentials, Docker permissions, or Switch installation are unavailable, report the single blocker, then stop. **Do not wait for AntiGravity to finish before recording the main submission.**