"""Optional local OpenAI-compatible inference for SYNTHETIC incident triage.

The language model never authorizes operations or touches devices. If offline,
triage continues deterministically and explicitly reports unavailable inference.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from urllib.parse import urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class LocalReasoner:
    endpoint: str
    model: str
    timeout: float = 4.0

    def __post_init__(self) -> None:
        url = urlparse(self.endpoint)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("LOCAL_MODEL_URL must be an HTTP(S) endpoint without embedded credentials")
        if not self.model.strip():
            raise ValueError("LOCAL_MODEL_NAME required")

    @classmethod
    def from_env(cls) -> "LocalReasoner | None":
        endpoint = os.getenv("LOCAL_MODEL_URL", "").strip()
        if not endpoint:
            return None
        return cls(endpoint.rstrip("/"), os.getenv("LOCAL_MODEL_NAME", "local-qwen"))

    def diagnose(self, incident_id: str) -> str:
        """Send only fabricated fixture facts; failures are clearly labelled."""
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 160,
            "messages": [
                {"role": "system", "content": "You are an operations triage assistant. Reply with ONE concise sentence. All data are SYNTHETIC. Explain what is known and unknown; do not claim a physical repair or request tools."},
                {"role": "user", "content": (
                    f"Synthetic incident {incident_id}: a camera monitoring service reports its camera OFFLINE; "
                    "a separate fabricated ethernet-port sensor says LINK UP; no RTSP, PoE voltage, or NVR logs are available. "
                    "What can and cannot be concluded?"
                )},
            ],
        }
        req = Request(self.endpoint.rstrip("/") + "/chat/completions",
                      data=json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=self.timeout) as response:
                raw = json.load(response)
            value = raw["choices"][0]["message"]["content"].strip()
            if not value:
                raise ValueError("Empty model answer")
            return "Local AI reasoning (non-authoritative): " + value[:500].replace("\n", " ")
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return "Local model unavailable; deterministic synthetic triage remains active."