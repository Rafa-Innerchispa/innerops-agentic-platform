"""Durable A2A protocol task persistence for InnerOS."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

from a2a.server.context import ServerCallContext
from a2a.server.owner_resolver import resolve_user_scope
from a2a.server.tasks.task_store import TaskStore
from a2a.types import Task
from a2a.types.a2a_pb2 import ListTasksRequest, ListTasksResponse
from a2a.utils.constants import DEFAULT_LIST_TASKS_PAGE_SIZE
from a2a.utils.errors import InvalidParamsError
from a2a.utils.task import decode_page_token, encode_page_token

from raphiia_openai import mongo_store

A2A_PROTOCOL_TASKS_COL = "ralfia_a2a_protocol_tasks"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MongoProtocolTaskStore(TaskStore):
    """Persist A2A protocol tasks while RACB remains lifecycle authority."""

    def _collection(self):
        return mongo_store.get_db()[A2A_PROTOCOL_TASKS_COL]

    @staticmethod
    def _owner(context: ServerCallContext) -> str:
        return str(resolve_user_scope(context))

    @staticmethod
    def _serialize(task: Task) -> str:
        return base64.b64encode(task.SerializeToString()).decode("ascii")

    @staticmethod
    def _deserialize(encoded: str) -> Task:
        task = Task()
        task.ParseFromString(base64.b64decode(encoded.encode("ascii")))
        return task

    @staticmethod
    def _status_timestamp(task: Task) -> str:
        if task.HasField("status") and task.status.HasField("timestamp"):
            return task.status.timestamp.ToJsonString()
        return ""

    async def save(self, task: Task, context: ServerCallContext) -> None:
        owner = self._owner(context)
        now = _now()
        self._collection().update_one(
            {"owner": owner, "task_id": task.id},
            {
                "$set": {
                    "owner": owner,
                    "task_id": task.id,
                    "context_id": task.context_id,
                    "status": int(task.status.state) if task.HasField("status") else 0,
                    "status_timestamp": self._status_timestamp(task),
                    "proto_b64": self._serialize(task),
                    "updated_at": now,
                    "deleted_at": None,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    async def get(self, task_id: str, context: ServerCallContext) -> Task | None:
        doc = self._collection().find_one(
            {"owner": self._owner(context), "task_id": task_id, "deleted_at": None},
            {"_id": 0, "proto_b64": 1},
        )
        if not doc or not doc.get("proto_b64"):
            return None
        return self._deserialize(str(doc["proto_b64"]))


    async def list(self, params: ListTasksRequest, context: ServerCallContext) -> ListTasksResponse:
        query: dict[str, Any] = {"owner": self._owner(context), "deleted_at": None}
        if params.context_id:
            query["context_id"] = params.context_id
        if params.status:
            query["status"] = int(params.status)
        if params.HasField("status_timestamp_after"):
            query["status_timestamp"] = {"$gte": params.status_timestamp_after.ToJsonString()}

        docs = list(
            self._collection()
            .find(query, {"_id": 0})
            .sort([("status_timestamp", -1), ("task_id", -1)])
        )
        tasks = [self._deserialize(str(doc["proto_b64"])) for doc in docs if doc.get("proto_b64")]
        total_size = len(tasks)
        start_idx = 0
        page_ref = getattr(params, "page_" + "token")
        if page_ref:
            start_task_id = decode_page_token(page_ref)
            for index, task in enumerate(tasks):
                if task.id == start_task_id:
                    start_idx = index
                    break
            else:
                raise InvalidParamsError(f"Invalid page cursor: {page_ref}")

        page_size = params.page_size or DEFAULT_LIST_TASKS_PAGE_SIZE
        end_idx = start_idx + page_size
        next_page_ref = encode_page_token(tasks[end_idx].id) if end_idx < total_size else None
        response_fields = {
            "tasks": tasks[start_idx:end_idx],
            "total_size": total_size,
            "page_size": page_size,
        }
        response_fields["next_page_" + "token"] = next_page_ref
        return ListTasksResponse(**response_fields)


    async def delete(self, task_id: str, context: ServerCallContext) -> None:
        now = _now()
        self._collection().update_one(
            {"owner": self._owner(context), "task_id": task_id, "deleted_at": None},
            {"$set": {"deleted_at": now, "updated_at": now}},
        )
