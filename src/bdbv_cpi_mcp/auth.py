"""
Minimal OAuth provider for MCP server.

Implements just enough of the OAuth 2.1 flow for Claude and ChatGPT
to complete their handshake. No real user authentication -- all tokens
are auto-approved. This is intentionally open; add real auth if needed.
"""

import secrets
import sys
import time
from dataclasses import dataclass

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


@dataclass
class AuthorizationCode:
    """Authorization code with the fields the MCP SDK token handler expects."""

    code: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    scopes: list[str]
    expires_at: float


# In-memory stores (fine for a single-process server)
_registered_clients: dict[str, OAuthClientInformationFull] = {}
_authorization_codes: dict[str, AuthorizationCode] = {}
_issued_tokens: dict[str, AccessToken] = {}


class OpenOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, str, AccessToken]
):
    """
    An OAuth provider that auto-approves everything.

    - Dynamic client registration: accepts any client
    - Authorization: immediately issues a code (no login page)
    - Token exchange: issues a Bearer token with full scopes
    - Token verification: accepts any token it has issued
    """

    # -- Client registration --------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return _registered_clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            client_info.client_id = f"client_{secrets.token_hex(16)}"
        client_info.client_id_issued_at = int(time.time())
        _registered_clients[client_info.client_id] = client_info

    # -- Authorization ---------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Issue an authorization code immediately (no login page)."""
        code = secrets.token_hex(32)
        _authorization_codes[code] = AuthorizationCode(
            code=code,
            client_id=client.client_id or "unknown",
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            code_challenge=params.code_challenge,
            scopes=params.scopes or ["openid", "profile"],
            expires_at=time.time() + 300,  # 5 minute expiry
        )
        # Return the redirect URI with the code appended
        sep = "&" if "?" in str(params.redirect_uri) else "?"
        redirect = f"{params.redirect_uri}{sep}code={code}"
        if params.state:
            redirect += f"&state={params.state}"
        return redirect

    # -- Authorization code exchange -------------------------------------------

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        return _authorization_codes.get(authorization_code)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        # Remove the used code
        _authorization_codes.pop(authorization_code.code, None)

        access_token = secrets.token_hex(32)
        scopes = authorization_code.scopes

        _issued_tokens[access_token] = AccessToken(
            token=access_token,
            client_id=client.client_id or "unknown",
            scopes=scopes,
            expires_at=int(time.time()) + 86400,  # 24 hours
        )

        print(
            f"[Auth] Issued token: {access_token[:8]}... scopes={scopes}",
            file=sys.stderr,
        )

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=86400,
            scope=" ".join(scopes),
        )

    # -- Token verification ----------------------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        result = _issued_tokens.get(token)
        print(
            f"[Auth] load_access_token: token={token[:8]}... "
            f"found={result is not None} "
            f"stored_keys={[k[:8] for k in _issued_tokens.keys()]}",
            file=sys.stderr,
        )
        return result

    # -- Refresh tokens (not used, but required by interface) ------------------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> str | None:
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
        scopes: list[str],
    ) -> OAuthToken:
        raise NotImplementedError("Refresh tokens not supported")

    # -- Revocation (no-op) ----------------------------------------------------

    async def revoke_token(self, token: AccessToken | str) -> None:
        if isinstance(token, AccessToken):
            _issued_tokens.pop(token.token, None)
        elif isinstance(token, str):
            _issued_tokens.pop(token, None)
