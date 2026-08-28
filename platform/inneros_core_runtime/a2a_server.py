"""A2A 1.0 JSON-RPC surface for the InnerOS agent fabric.

The official A2A SDK owns wire parsing, Agent Cards and protocol task events.
InnerOS RACB/Mongo remains the durable execution source of truth. A2A task IDs
are reused as durable bridge IDs so Get Task projects current RACB state instead
of inventing a second lifecycle.
"""

from __future__ import annotations

import hmac
import json
import os
from typing import Any

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks.task_store import TaskStore
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Part,
    Task,
    TaskState,
    TaskStatus,
)
from a2a.types.a2a_pb2 import ListTasksRequest, ListTasksResponse
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from raphiia_openai import a2a_bridge, a2a_oidc
from raphiia_openai.a2a_task_store import MongoProtocolTaskStore
from raphiia_openai.settings import RAPHI_IA_PUBLIC_URL

A2A_PROTOCOL_VERSION = "1.0"
A2A_SDK_MIN_VERSION = "1.1.2"
A2A_AUTH_ENV = "A2A_SHARED_" + "TOKEN"

_A2A_TO_PROTO_STATE = {
    "submitted": TaskState.TASK_STATE_SUBMITTED,
    "working": TaskState.TASK_STATE_WORKING,
    "completed": TaskState.TASK_STATE_COMPLETED,
    "failed": TaskState.TASK_STATE_FAILED,
    "canceled": TaskState.TASK_STATE_CANCELED,
    "input-required": TaskState.TASK_STATE_INPUT_REQUIRED,
    "rejected": TaskState.TASK_STATE_REJECTED,
}


class A2AAuthMiddleware(BaseHTTPMiddleware):
    """Protect task RPC while leaving status and Agent Cards discoverable.

    Auth order: OIDC service JWT (NON-LIVE HS256 harness / LIVE JWKS pending),
    then shared bearer token, then loopback-only when nothing is configured.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        if path.endswith("/status") or path.endswith(AGENT_CARD_WELL_KNOWN_PATH):
            return await call_next(request)

        expected = (os.getenv(A2A_AUTH_ENV) or "").strip()
        oidc_audience = (os.getenv("A2A_OIDC_AUDIENCE") or "").strip()
        client_host = request.client.host if request.client else ""
        authorization = request.headers.get("authorization", "")
        prefix = "Bearer" + " "
        supplied = authorization[len(prefix) :].strip() if authorization.startswith(prefix) else ""
        request.state.traceparent = request.headers.get("traceparent", "")
        request.state.correlation_id = request.headers.get("x-correlation-id", "")

        if oidc_audience and supplied:
            try:
                claims = a2a_oidc.verify_service_token(supplied, audience=oidc_audience)
                request.state.a2a_auth = {"mode": "oidc", "claims": claims, "live_mode": claims.get("live_mode")}
                return await call_next(request)
            except a2a_oidc.A2AOIDCError as exc:
                if not expected:
                    return JSONResponse({"ok": False, "error": exc.code, "detail": str(exc)}, status_code=401)

        if expected:
            if supplied and hmac.compare_digest(supplied, expected):
                request.state.a2a_auth = {"mode": "bearer", "live_mode": "NON-LIVE"}
                return await call_next(request)
            return JSONResponse({"ok": False, "error": "a2a_unauthorized"}, status_code=401)

        if client_host not in {"127.0.0.1", "::1", "localhost"}:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "a2a_auth_not_configured",
                    "required_env": [A2A_AUTH_ENV, "A2A_OIDC_AUDIENCE"],
                },
                status_code=503,
            )
        request.state.a2a_auth = {"mode": "loopback", "live_mode": "NON-LIVE"}
        return await call_next(request)


class RACBProjectedTaskStore(TaskStore):
    """Durable protocol store whose reads project the RACB lifecycle."""

    def __init__(self, bridge: a2a_bridge.A2ABridge | None = None) -> None:
        self._inner = MongoProtocolTaskStore()
        self._bridge = bridge or a2a_bridge.get_bridge()

    def _project(self, task: Task | None) -> Task | None:
        if task is None:
            return None
        projection = self._bridge.task_status(task.id)
        if not projection.get("ok"):
            return task
        state = str((projection.get("status") or {}).get("state") or "working")
        proto_state = _A2A_TO_PROTO_STATE.get(state)
        if proto_state is not None:
            task.status.state = proto_state
        return task

    async def save(self, task: Task, context: ServerCallContext) -> None:
        await self._inner.save(task, context)

    async def get(self, task_id: str, context: ServerCallContext) -> Task | None:
        return self._project(await self._inner.get(task_id, context))

    async def list(self, params: ListTasksRequest, context: ServerCallContext) -> ListTasksResponse:
        response = await self._inner.list(params, context)
        for task in response.tasks:
            self._project(task)
        return response

    async def delete(self, task_id: str, context: ServerCallContext) -> None:
        await self._inner.delete(task_id, context)


class InnerOSA2AExecutor(AgentExecutor):
    """Delegate one official A2A task into one durable InnerOS ops task."""

    def __init__(self, agent_id: str, bridge: a2a_bridge.A2ABridge | None = None) -> None:
        if agent_id not in a2a_bridge.AGENT_CARDS:
            raise ValueError(f"unknown_a2a_agent:{agent_id}")
        self.agent_id = agent_id
        self.bridge = bridge or a2a_bridge.get_bridge()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_message = context.message
        task_id = context.task_id
        context_id = context.context_id
        if not user_message or not task_id or not context_id:
            return

        await event_queue.enqueue_event(
            Task(
                id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
                history=[user_message],
            )
        )
        updater = TaskUpdater(event_queue=event_queue, task_id=task_id, context_id=context_id)
        await updater.start_work(
            message=updater.new_agent_message(parts=[Part(text="Delegating to InnerOS RACB/Mongo.")])
        )

        body = (context.get_user_input() or "").strip()
        if not body:
            await updater.failed(
                message=updater.new_agent_message(parts=[Part(text="A2A request contained no text payload.")])
            )
            return

        title = next((line.strip() for line in body.splitlines() if line.strip()), body)[:160]
        result = self.bridge.dispatch(
            agent_id=self.agent_id,
            title=title,
            body=body,
            context_id=context_id,
            correlation_id=f"a2a:{context_id}:{task_id}",
            protocol_task_id=task_id,
            priority="p0",
            related_project="inneros",
            dry_run=False,
        )
        if not result.get("ok"):
            await updater.failed(
                message=updater.new_agent_message(
                    parts=[Part(text=f"InnerOS delegation failed: {result.get('error', 'unknown_error')}")]
                )
            )
            return

        receipt = {
            "a2a_task_id": result.get("a2a_task_id"),
            "context_id": result.get("contextId"),
            "ops_task_id": result.get("ops_task_id"),
            "agent_id": self.agent_id,
            "state": "working",
            "source_of_truth": "ralfia_ops_tasks/RACB/MongoDB",
        }
        await updater.add_artifact(
            parts=[Part(text=json.dumps(receipt, sort_keys=True))],
            name="inneros-delegation",
            last_chunk=True,
        )
        # Delegation is not completion. Get Task stays WORKING until RACB reaches
        # a terminal state with evidence, projected by RACBProjectedTaskStore.

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError(
            "A2A cancellation is disabled until RACB ownership-safe cancellation is wired end-to-end"
        )


def _public_base() -> str:
    return (os.getenv("A2A_PUBLIC_URL") or RAPHI_IA_PUBLIC_URL or "http://127.0.0.1:8099").rstrip("/")


def build_agent_card(agent_id: str) -> AgentCard:
    raw = a2a_bridge.AGENT_CARDS[agent_id]
    skill = raw["skills"][0]
    return AgentCard(
        name=str(raw["name"]),
        description=str(raw["description"]),
        version=str(raw["version"]),
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text", "application/json"],
        default_output_modes=["application/json", "task-status"],
        skills=[
            AgentSkill(
                id=str(skill["id"]),
                name=str(skill["name"]),
                description=str(skill["description"]),
                tags=["inneros", "a2a", str(raw["metadata"].get("inneros_role") or "agent")],
                examples=[f"Delegate work to {raw['name']}"],
                input_modes=["text", "application/json"],
                output_modes=["application/json", "task-status"],
            )
        ],
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                protocol_version=A2A_PROTOCOL_VERSION,
                url=f"{_public_base()}/a2a/{agent_id}",
            )
        ],
    )


async def _status_endpoint(_request: Request) -> JSONResponse:
    status = a2a_bridge.status()
    oidc = a2a_oidc.auth_status()
    status.update(
        {
            "wire_protocol": "A2A 1.0 JSON-RPC",
            "sdk_min_version": A2A_SDK_MIN_VERSION,
            "base_path": "/a2a",
            "rpc_auth": oidc.get("modes") or ["loopback"],
            "oidc": oidc,
            "traceparent_header": "traceparent",
        }
    )
    return JSONResponse(status)


def build_a2a_app() -> Starlette:
    """Build the multi-agent A2A ASGI app mounted by :8099 at ``/a2a``."""
    routes: list[Any] = [Route("/status", _status_endpoint, methods=["GET"])]
    for agent_id in a2a_bridge.AGENT_CARDS:
        path = f"/{agent_id}"
        card = build_agent_card(agent_id)
        handler = DefaultRequestHandler(
            agent_executor=InnerOSA2AExecutor(agent_id),
            task_store=RACBProjectedTaskStore(),
            agent_card=card,
        )
        routes.extend(
            create_agent_card_routes(
                agent_card=card,
                card_url=f"{path}{AGENT_CARD_WELL_KNOWN_PATH}",
            )
        )
        routes.extend(create_jsonrpc_routes(request_handler=handler, rpc_url=path))

    app = Starlette(routes=routes)
    app.add_middleware(A2AAuthMiddleware)
    return app
