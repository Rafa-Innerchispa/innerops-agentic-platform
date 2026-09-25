"""Temporal Worker Runner for InnerOS Task Queues.

Usage:
  python3 -m inneros_core_runtime.temporal_worker [queue_name]
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

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


async def main():
    queue = sys.argv[1] if len(sys.argv) > 1 else TASK_QUEUE_GENERAL
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    logger.info(f"Connecting to Temporal Server at {TEMPORAL_HOST} (namespace: {TEMPORAL_NAMESPACE})...")
    client = await Client.connect(TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE)
    logger.info(f"Connected to Temporal Server successfully.")

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

    logger.info(f"InnerOS Temporal Worker started. Listening on queue: '{queue}'...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
