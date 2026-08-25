"""Shared MCP transport factories (SDK v2).

ONE place for the transport arrangement both MCP surfaces use
(app/mcp_server.py — the project tool surface; app/mcp_world.py — the
world-model ingestion surface), so the reconnect contract is fixed in
one file, never drift-copied.

THE CONTRACT (why the SSE app is hand-rolled): Claude Code
auto-reconnects a dropped SSE stream and adopts the fresh session the
server advertises, but it does NOT re-send the initialize handshake on
what it considers a resumed connection. SDK v2's legacy-era runner
gates every request on `initialize_accepted` (INVALID_PARAMS at the
client, observed as -32602 after backend deploys), exactly like v1's
stateful ServerSession did. v1 was escaped with the private
`Server.run(..., stateless=True)`; v2 removed that parameter, but its
`Connection` model makes the escape a documented state instead of a
flag: `initialize_accepted` is DERIVED ("the handshake completed
outright (born-ready, or a bare notifications/initialized)"), so a
connection whose `initialized` event is pre-set serves tools/list and
tools/call immediately — a fresh initialize handshake on the same
connection still records client params and works. The handler below
builds exactly the loop the SDK's own `serve_dual_era_loop` builds for
the legacy era (same dispatcher recipe, same inline-initialize rule),
with the connection born ready.
"""
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from mcp.server.connection import Connection
from mcp.server.runner import serve_connection
from mcp.server.sse import SseServerTransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher

# Both surfaces sit behind the deployment's own proxy plane; host
# validation happens there. Leaving the SDK default in place would
# auto-enable localhost-only DNS-rebinding protection and reject every
# proxied Host header.
TRANSPORT_SECURITY = TransportSecuritySettings(
    enable_dns_rebinding_protection=False)


def stateless_sse_app(mcp) -> Starlette:
    """The SSE ASGI app for one MCPServer, serving /sse + /messages/ at
    its root (mount at the RAW EXTERNAL path — the advertised message
    endpoint is built from the mount's root_path)."""
    server = mcp._lowlevel_server
    sse = SseServerTransport("/messages/",
                             security_settings=TRANSPORT_SECURITY)

    async def handle_sse(request: Request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            async with server.lifespan(server) as lifespan_state:
                dispatcher = JSONRPCDispatcher(
                    streams[0], streams[1],
                    # The SDK's own legacy-loop recipe: initialize runs
                    # inline so a client that pipelines it with the next
                    # request never races the init gate.
                    inline_methods=frozenset({"initialize"}),
                )
                connection = Connection.for_loop(dispatcher)
                # Born ready — the reconnect contract above.
                connection.initialized.set()
                await serve_connection(
                    server, dispatcher,
                    connection=connection,
                    lifespan_state=lifespan_state,
                    init_options=server.create_initialization_options(),
                )
        return Response()

    return Starlette(routes=[
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse.handle_post_message),
    ])
