"""MCP server entry point for bdbv-cpi-mcp."""

import json
import os
import secrets
import sys
import time
from urllib.parse import parse_qs, urlparse

from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import AuthSettings, TransportSecuritySettings
from mcp.server.auth.settings import ClientRegistrationOptions

from bdbv_cpi_mcp.auth import (
    AuthorizationCode,
    OpenOAuthProvider,
    _authorization_codes,
)

MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "12009"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://dev-9.bv-brc.org")


def _get_transport() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else "streamable-http"


# ── OAuth provider ───────────────────────────────────────────────────────
_oauth_provider = OpenOAuthProvider() if _get_transport() != "stdio" else None


# ── Consent page HTML ────────────────────────────────────────────────────
CONSENT_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Connect to CEPI Bioinformatics MCP</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0; background: #f5f5f5;
        }}
        .card {{
            background: white; padding: 2rem; border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1); max-width: 400px;
            text-align: center;
        }}
        h2 {{ margin-top: 0; color: #333; }}
        p {{ color: #666; line-height: 1.5; }}
        .tools {{ text-align: left; margin: 1rem 0; padding: 0.5rem 1rem;
                  background: #f9f9f9; border-radius: 6px; font-size: 0.9em; }}
        button {{
            background: #2563eb; color: white; border: none;
            padding: 12px 32px; border-radius: 8px; font-size: 1rem;
            cursor: pointer; margin-top: 1rem;
        }}
        button:hover {{ background: #1d4ed8; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>CEPI Bioinformatics</h2>
        <p>Grant access to the following tools:</p>
        <div class="tools">
            <strong>BLAST</strong> &mdash; sequence search<br>
            <strong>MAFFT</strong> &mdash; multiple alignment<br>
            <strong>ESMFold2</strong> &mdash; structure prediction<br>
            <strong>ESMC</strong> &mdash; protein embeddings
        </div>
        <form method="POST" action="{consent_url}">
            <input type="hidden" name="client_id" value="{client_id}">
            <input type="hidden" name="redirect_uri" value="{redirect_uri}">
            <input type="hidden" name="code_challenge" value="{code_challenge}">
            <input type="hidden" name="state" value="{state}">
            <input type="hidden" name="scope" value="{scope}">
            <input type="hidden" name="resource" value="{resource}">
            <button type="submit">Connect</button>
        </form>
    </div>
</body>
</html>"""


class AuthInterceptMiddleware:
    """
    ASGI middleware that:
    1. Intercepts GET /authorize → serves an HTML consent page
    2. Intercepts POST /consent → issues auth code and redirects
    3. Logs all requests for debugging
    4. Passes everything else through to the SDK
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")

        # Debug logging
        headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "NONE")
        if auth != "NONE" and len(auth) > 20:
            auth = f"{auth[:20]}...({len(auth)} chars)"
        print(
            f"[DEBUG] {method} {path} | auth={auth} | "
            f"accept={headers.get('accept', 'NONE')}",
            file=sys.stderr,
        )

        # Intercept GET /authorize → show consent page
        if method == "GET" and path == "/authorize":
            qs = scope.get("query_string", b"").decode()
            params = {k: v[0] for k, v in parse_qs(qs).items()}

            html = CONSENT_HTML.format(
                consent_url=f"{PUBLIC_BASE_URL}/consent",
                client_id=params.get("client_id", ""),
                redirect_uri=params.get("redirect_uri", ""),
                code_challenge=params.get("code_challenge", ""),
                state=params.get("state", ""),
                scope=params.get("scope", "openid profile"),
                resource=params.get("resource", ""),
            )
            body = html.encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"text/html; charset=utf-8"),
                        (b"content-length", str(len(body)).encode()),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # Intercept POST /consent → issue auth code and redirect
        if method == "POST" and path == "/consent":
            await self._handle_consent(scope, receive, send)
            return

        # Everything else → pass through to SDK
        await self.app(scope, receive, send)

    async def _handle_consent(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Read form body, issue auth code, redirect to client."""
        # Read the full body
        body_parts = []
        while True:
            msg = await receive()
            if msg["type"] == "http.request":
                body_parts.append(msg.get("body", b""))
                if not msg.get("more_body", False):
                    break

        full_body = b"".join(body_parts).decode()
        params = {k: v[0] for k, v in parse_qs(full_body).items()}

        client_id = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        code_challenge = params.get("code_challenge", "")
        state = params.get("state", "")
        scope_str = params.get("scope", "openid profile")

        # Issue an authorization code
        code = secrets.token_hex(32)
        _authorization_codes[code] = AuthorizationCode(
            code=code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            redirect_uri_provided_explicitly=True,
            code_challenge=code_challenge,
            scopes=scope_str.split(),
            expires_at=time.time() + 300,
        )

        # Build redirect URL
        sep = "&" if "?" in redirect_uri else "?"
        url = f"{redirect_uri}{sep}code={code}"
        if state:
            url += f"&state={state}"

        print(f"[Auth] Consent granted, redirecting to client", file=sys.stderr)

        location = url.encode()
        await send(
            {
                "type": "http.response.start",
                "status": 302,
                "headers": [
                    (b"location", location),
                    (b"cache-control", b"no-store"),
                    (b"content-length", b"0"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})


# ── Server creation ──────────────────────────────────────────────────────


def _create_server() -> FastMCP:
    transport = _get_transport()

    if transport == "stdio":
        return FastMCP("bdbv-cpi-mcp")

    return FastMCP(
        "bdbv-cpi-mcp",
        host=MCP_HOST,
        port=MCP_PORT,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        ),
        auth_server_provider=_oauth_provider,
        auth=AuthSettings(
            issuer_url=PUBLIC_BASE_URL,
            resource_server_url=f"{PUBLIC_BASE_URL}/mcp",
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["openid", "profile"],
                default_scopes=["openid", "profile"],
            ),
            required_scopes=["openid", "profile"],
        ),
    )


mcp = _create_server()

# Import tools so they register with the mcp instance
from bdbv_cpi_mcp.tools import blast, mafft, esm  # noqa: E402, F401


def main():
    transport = _get_transport()
    if transport == "stdio":
        print("Starting bdbv-cpi-mcp server (stdio)...", file=sys.stderr)
    else:
        print(
            f"Starting bdbv-cpi-mcp server on {MCP_HOST}:{MCP_PORT} ...",
            file=sys.stderr,
        )

        # Wrap the app with our auth intercept + debug middleware
        original_app_method = mcp.streamable_http_app

        def patched_app():
            app = original_app_method()
            return AuthInterceptMiddleware(app)

        mcp.streamable_http_app = patched_app

    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
