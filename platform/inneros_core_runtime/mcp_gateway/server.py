"""MCP Gateway Server - Standalone HTTP & Stdio Proxy Service."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .gateway import MCPGateway
from .profiles import ProfileManager
from .throttling import ThrottlingManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [mcp_gateway] %(message)s",
)
logger = logging.getLogger("mcp_gateway_server")


def create_gateway_app(gateway: MCPGateway | None = None) -> Starlette:
    gw = gateway or MCPGateway()

    async def handle_mcp_post(request: Request) -> Response:
        """Handle JSON-RPC MCP POST requests."""
        profile_override = request.query_params.get("profile") or request.headers.get("X-MCP-Profile") or request.headers.get("x-mcp-profile")
        admin_secret = request.query_params.get("admin_secret") or request.headers.get("X-MCP-Admin-Secret") or request.headers.get("x-mcp-admin-secret")

        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "ParseError: Invalid JSON"}},
                status_code=400,
            )

        headers = dict(request.headers)

        if isinstance(body, list):
            responses = []
            for item in body:
                res = await gw.handle_jsonrpc(
                    item,
                    client_profile=profile_override,
                    headers=headers,
                    admin_secret=admin_secret,
                )
                responses.append(res)
            return JSONResponse(responses)
        else:
            res = await gw.handle_jsonrpc(
                body,
                client_profile=profile_override,
                headers=headers,
                admin_secret=admin_secret,
            )
            return JSONResponse(res)

    async def handle_health(request: Request) -> Response:
        return JSONResponse({
            "status": "healthy",
            "service": "mcp-gateway-router",
            "version": "1.1.0",
            "default_profile": gw.profile_mgr.default_profile,
            "profiles_available": list(gw.profile_mgr.profiles.keys()),
            "allow_admin_profile": gw.profile_mgr.allow_admin_profile,
            "throttling": gw.throttling_mgr.get_stats(),
            "catalog_fingerprint": gw._catalog_fingerprint or "not_cached",
        })

    async def handle_profiles(request: Request) -> Response:
        return JSONResponse({
            "default_profile": gw.profile_mgr.default_profile,
            "allow_admin_profile": gw.profile_mgr.allow_admin_profile,
            "profiles": gw.profile_mgr.list_profiles(),
        })

    routes = [
        Route("/mcp", handle_mcp_post, methods=["POST"]),
        Route("/health", handle_health, methods=["GET"]),
        Route("/profiles", handle_profiles, methods=["GET"]),
    ]

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]

    app = Starlette(routes=routes, middleware=middleware)
    return app


async def run_stdio_mode(gateway: MCPGateway, profile: str | None = None, admin_secret: str | None = None) -> None:
    """Run MCP Gateway in Stdio Mode for CLI / Desktop Client Integration."""
    logger.info("Starting MCP Gateway in stdio mode (active profile: %s)", profile or gateway.profile_mgr.default_profile)
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break
        line_str = line.decode("utf-8").strip()
        if not line_str:
            continue
        try:
            req = json.loads(line_str)
            res = await gateway.handle_jsonrpc(req, client_profile=profile, admin_secret=admin_secret)
            sys.stdout.write(json.dumps(res) + "\n")
            sys.stdout.flush()
        except Exception as e:
            err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP Router & Tool Throttling Gateway")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=8001, help="Port to listen on (default: 8001)")
    parser.add_argument("--profile", type=str, default=None, help="Default active profile")
    parser.add_argument("--config", type=str, default=None, help="Path to profiles.json configuration file")
    parser.add_argument("--allow-admin", action="store_true", help="Enable profile_admin access")
    parser.add_argument("--admin-secret", type=str, default=None, help="Admin authorization secret")
    parser.add_argument("--stdio", action="store_true", help="Run in Stdio mode instead of HTTP")

    args = parser.parse_args()

    prof_mgr = ProfileManager(
        config_path=args.config,
        allow_admin_profile=args.allow_admin if args.allow_admin else None,
        admin_secret=args.admin_secret,
    )
    if args.profile:
        prof_mgr.default_profile = args.profile

    gateway = MCPGateway(profile_manager=prof_mgr)

    if args.stdio:
        asyncio.run(run_stdio_mode(gateway, profile=args.profile, admin_secret=args.admin_secret))
    else:
        logger.info(
            "Starting MCP Gateway on http://%s:%d/mcp (default profile: %s, admin_allowed: %s)",
            args.host,
            args.port,
            prof_mgr.default_profile,
            prof_mgr.allow_admin_profile,
        )
        app = create_gateway_app(gateway)
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
