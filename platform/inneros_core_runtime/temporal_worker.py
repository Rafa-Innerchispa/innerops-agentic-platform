"""Temporal Worker Runner for InnerOS Task Queues.

Usage:
  python3 -m inneros_core_runtime.temporal_worker [queue_name_or_comma_separated]
  python3 -m inneros_core_runtime.temporal_worker --queues queue1,queue2
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import List

from temporalio.client import Client
from temporalio.worker import Worker

from inneros_core_runtime.temporal_workflows import OpsTaskWorkflow
from inneros_core_runtime.temporal_activities import (
    activity_validate_envelope,
    activity_hydrate_worktree,
    activity_execute_agent_graph,
    activity_sync_mongo_mirror,
)

logger = logging.getLogger("temporal_worker")

TASK_QUEUE_GENERAL = "inneros-general-ops"
TASK_QUEUE_INTEL = "inneros-intel-ops"
TASK_QUEUE_AMD_GPU = "inneros-amd-gpu-ops"

TEMPORAL_HOST = os.environ.get("TEMPORAL_HOST", "127.0.0.1:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")


def parse_queues() -> List[str]:
    parser = argparse.ArgumentParser(description="InnerOS Temporal Worker")
    parser.add_argument("positional_queues", nargs="?", default="", help="Queue name or comma-separated queues")
    parser.add_argument("--queues", default="", help="Comma-separated queue list")
    args, _ = parser.parse_known_args()

    raw = args.queues or args.positional_queues or TASK_QUEUE_GENERAL
    queues = [q.strip() for q in raw.split(",") if q.strip() and not q.strip().startswith("-")]
    return queues or [TASK_QUEUE_GENERAL]


async def main():
    queues = parse_queues()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    logger.info(f"Connecting to Temporal Server at {TEMPORAL_HOST} (namespace: {TEMPORAL_NAMESPACE})...")
    client = await Client.connect(TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE)
    logger.info("Connected to Temporal Server successfully.")

    workers = []
    for queue in queues:
        worker = Worker(
            client,
            task_queue=queue,
            workflows=[OpsTaskWorkflow],
            activities=[
                activity_validate_envelope,
                activity_hydrate_worktree,
                activity_execute_agent_graph,
                activity_sync_mongo_mirror,
            ],
        )
        workers.append(worker)
        logger.info(f"Initialized worker listening on queue: '{queue}'")

    logger.info(f"InnerOS Temporal Workers started for queues: {queues}")
    await asyncio.gather(*[w.run() for w in workers])


if __name__ == "__main__":
    asyncio.run(main())
