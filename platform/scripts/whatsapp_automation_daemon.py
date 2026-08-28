#!/usr/bin/env python3
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT=Path('/home/rlopez/projects/raphiia-openai')
sys.path.insert(0,str(ROOT))
from raphiia_openai.whatsapp_automation import run_due_reminders
from raphiia_openai.codex_whatsapp_jobs import run_next_approved_job
from raphiia_openai.whatsapp_admin_jobs import run_next_approved_job as run_next_admin_job
def main() -> None:
    while True:
        try: run_due_reminders()
        except Exception: pass
        try: run_next_approved_job()
        except Exception: pass
        try: run_next_admin_job()
        except Exception: pass
        time.sleep(15)
if __name__=='__main__': main()
