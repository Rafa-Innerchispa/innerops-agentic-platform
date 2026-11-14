"""8 tareas de presentación por voz: 3 externos + Qwen por servidor.

Externos (antigravity, codex, cursor): requieren aprobación del propietario
vía Telegram o Alexa sobre el registro único; la primera decisión gana.
Qwen local: carril interno, sin gate externo.

Despacho: desde un host con Mongo/Temporal vivos (Intel o AMD):
  python3 scripts/dispatch_voice_rollcall.py --dry-run   # vista previa
  python3 scripts/dispatch_voice_rollcall.py             # crea las 8
"""
from __future__ import annotations

ROLLCALL = [
    # (servidor, proveedor, interno)
    ("intel", "antigravity", False),
    ("intel", "codex", False),
    ("intel", "cursor", False),
    ("intel", "qwen", True),
    ("amd", "antigravity", False),
    ("amd", "codex", False),
    ("amd", "cursor", False),
    ("amd", "qwen", True),
]

CORRELATION = "voice-rollcall-2026-11-14"


def build_task(server: str, provider: str, internal: bool) -> dict:
    name = "Qwen local" if internal else provider.capitalize()
    greeting = f"Hola, soy {name} del servidor {server}."
    if internal:
        return {
            "assignee": "dev_swarm",
            "preferred_provider": "dev_swarm",
            "title": f"[Presentación] {greeting}",
            "objective": (
                f"{greeting} Di este saludo por Alexa y registra evidencia. "
                f"Servidor: {server}. Sin gate externo: carril interno."
            ),
            "task_class": "business_ops",
            "execution_lane": "local_dev_swarm",
            "correlation_id": CORRELATION,
            "idempotency_key": f"voice-rollcall-{server}-{provider}",
        }
    return {
        "assignee": provider,
        "preferred_provider": provider,
        "title": f"[Presentación] {greeting}",
        "objective": (
            f"{greeting} Preséntate por Alexa tras la aprobación del propietario. "
            f"Servidor: {server}. Requiere grant de presupuesto vigente."
        ),
        "task_class": "coding",
        "execution_lane": f"{provider}_interactive",
        "preferred_model": "",
        "correlation_id": CORRELATION,
        "idempotency_key": f"voice-rollcall-{server}-{provider}",
        "payload": {"preferred_host": server},
    }


def main(dry_run: bool = False) -> int:
    for server, provider, internal in ROLLCALL:
        spec = build_task(server, provider, internal)
        if dry_run:
            print(f"[dry-run] {server}/{provider}: {spec['title']}")
            continue
    if dry_run:
        return 0
    try:
        from inneros_core_runtime import coordination_live as cl
    except ImportError as exc:
        print(f"Sin runtime InnerOS aquí: {exc}")
        return 2
    ok = True
    for server, provider, internal in ROLLCALL:
        spec = build_task(server, provider, internal)
        out = cl.create_ops_task(**spec)
        print(f"{server}/{provider}: {out.get('task_id', out.get('error'))}")
        ok = ok and bool(out.get("ok"))
    return 0 if ok else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(main(dry_run="--dry-run" in sys.argv))
