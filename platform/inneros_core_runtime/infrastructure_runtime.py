from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

LOCAL = Path('/home/rlopez/data/ai_coordination/infrastructure/ralphi-ia-ver-10.latest.json')
COLLECTOR = '/home/rlopez/projects/ralphiia-quoteops/work_infrastructure_snapshot.py'


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {'ok': False, 'error': 'snapshot_unavailable'}


def _refresh_remote() -> dict:
    try:
        proc = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', 'rlopez@192.168.1.5',
             f'python3 {COLLECTOR}'],
            capture_output=True, text=True, timeout=12, check=False,
        )
        if proc.returncode != 0:
            return {'ok': False, 'error': 'remote_snapshot_unavailable'}
        return json.loads(proc.stdout)
    except Exception:
        return {'ok': False, 'error': 'remote_snapshot_unavailable'}


def get_infrastructure_status() -> dict:
    servers = [_read(LOCAL), _refresh_remote()]
    return {
        'ok': any('hostname' in item for item in servers),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'servers': servers,
        'partial': any('hostname' not in item for item in servers),
        'secret_policy': 'Saneado: sin credenciales, tokens, claves, variables de entorno ni argumentos de procesos.',
    }
