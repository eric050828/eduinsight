"""LTI 1.3 integration for FastAPI.

Provides a FastAPI adapter for PyLTI1p3, enabling EduInsight to be
embedded as an External Tool in Moodle (or any LTI 1.3 platform).

Flow:
  1. Moodle POSTs to /lti/login (OIDC initiation)
  2. We redirect back to Moodle's auth endpoint
  3. Moodle POSTs id_token to /lti/launch
  4. We validate JWT, extract user/course, redirect to chat UI
  5. /lti/jwks serves our public key for Moodle to verify
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.parse
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pylti1p3.cookie import CookieService as _CookieService
from pylti1p3.message_launch import MessageLaunch
from pylti1p3.oidc_login import OIDCLogin
from pylti1p3.redirect import Redirect
from pylti1p3.request import Request as LTIRequest
from pylti1p3.session import SessionService
from pylti1p3.tool_config import ToolConfDict

from .auth import (
    RegisterRequest,
    _row_to_user,
    create_access_token,
    create_user,
    get_user_by_username,
)
from .config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory stores (sufficient for single-process demo)
# ---------------------------------------------------------------------------

_sessions: dict[str, dict[str, Any]] = {}
_launch_cache: dict[str, Any] = {}  # launch_id -> jwt_body


# ---------------------------------------------------------------------------
# FastAPI adapters for PyLTI1p3
# ---------------------------------------------------------------------------


class FastAPILTIRequest(LTIRequest):
    """Wraps a FastAPI/Starlette Request for PyLTI1p3."""

    def __init__(
        self,
        request: Request,
        form_data: dict[str, str] | None = None,
    ) -> None:
        self._request = request
        self._form_data = form_data or {}
        self._session_id = self._resolve_session_id()
        if self._session_id not in _sessions:
            _sessions[self._session_id] = {}

    def _resolve_session_id(self) -> str:
        """Get or create a session ID from cookies."""
        sid = self._request.cookies.get("lti_session_id")
        if sid:
            return sid
        # Generate a new session ID from request metadata
        raw = f"{time.time()}-{id(self._request)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def session(self) -> dict[str, Any]:
        return _sessions.setdefault(self._session_id, {})

    def is_secure(self) -> bool:
        return self._request.url.scheme == "https"

    def get_param(self, key: str) -> str | None:
        # Check form data first (POST), then query params (GET)
        if self._form_data and key in self._form_data:
            return self._form_data[key]
        return self._request.query_params.get(key)


class FastAPICookieService(_CookieService):
    """Cookie service for FastAPI responses."""

    def __init__(self, lti_request: FastAPILTIRequest) -> None:
        self._request = lti_request
        self._cookie_data_to_set: dict[str, dict[str, Any]] = {}

    def _get_key(self, name: str) -> str:
        """Build the actual cookie key with the LTI prefix."""
        return f"{self._cookie_prefix}-{name}"

    def get_cookie(self, name: str) -> str | None:
        key = self._get_key(name)
        return self._request._request.cookies.get(key)

    def set_cookie(self, name: str, value: str | int, exp: int | None = 3600) -> None:
        key = self._get_key(name)
        self._cookie_data_to_set[key] = {"value": str(value), "exp": exp}

    def update_response(self, response: Response) -> None:
        """Apply queued cookies to a FastAPI Response."""
        for key, data in self._cookie_data_to_set.items():
            response.set_cookie(
                key=key,
                value=data["value"],
                max_age=data["exp"],
                secure=self._request.is_secure(),
                path="/",
                httponly=True,
                samesite="none" if self._request.is_secure() else "lax",
            )
        # Always set session cookie
        response.set_cookie(
            key="lti_session_id",
            value=self._request.session_id,
            max_age=3600,
            path="/",
            httponly=True,
            samesite="none" if self._request.is_secure() else "lax",
        )


class FastAPIRedirect(Redirect):
    """Redirect response for FastAPI."""

    def __init__(self, location: str, cookie_service: FastAPICookieService | None = None) -> None:
        self._location = location
        self._cookie_service = cookie_service

    def do_redirect(self) -> Response:
        response = RedirectResponse(url=self._location, status_code=302)
        if self._cookie_service:
            self._cookie_service.update_response(response)
        return response

    def do_js_redirect(self) -> Response:
        html = (
            '<html><head><title>Redirecting...</title></head><body>'
            f'<script type="text/javascript">window.location="{self._location}";</script>'
            "</body></html>"
        )
        response = HTMLResponse(content=html)
        if self._cookie_service:
            self._cookie_service.update_response(response)
        return response

    def set_redirect_url(self, location: str) -> None:
        self._location = location

    def get_redirect_url(self) -> str:
        return self._location


class FastAPIOIDCLogin(OIDCLogin):
    """OIDC login handler for FastAPI."""

    def __init__(
        self,
        request: FastAPILTIRequest,
        tool_config: ToolConfDict,
        session_service: SessionService | None = None,
        cookie_service: FastAPICookieService | None = None,
        launch_data_storage: Any = None,
    ) -> None:
        cookie_service = cookie_service or FastAPICookieService(request)
        session_service = session_service or SessionService(request)
        super().__init__(request, tool_config, session_service, cookie_service, launch_data_storage)

    def get_redirect(self, url: str) -> FastAPIRedirect:
        return FastAPIRedirect(url, self._cookie_service)

    def get_response(self, html: str) -> Response:
        return HTMLResponse(content=html)


class FastAPIMessageLaunch(MessageLaunch):
    """Message launch handler for FastAPI."""

    def __init__(
        self,
        request: FastAPILTIRequest,
        tool_config: ToolConfDict,
        session_service: SessionService | None = None,
        cookie_service: FastAPICookieService | None = None,
        launch_data_storage: Any = None,
        requests_session: Any = None,
    ) -> None:
        cookie_service = cookie_service or FastAPICookieService(request)
        session_service = session_service or SessionService(request)
        super().__init__(
            request, tool_config, session_service, cookie_service,
            launch_data_storage, requests_session,
        )

    def _get_request_param(self, key: str) -> str:
        return self._request.get_param(key)


# ---------------------------------------------------------------------------
# LTI configuration helpers
# ---------------------------------------------------------------------------


def _get_tool_config() -> ToolConfDict:
    """Build LTI tool configuration from environment/settings.

    In production, these would come from a config file or database.
    For demo, we use a ToolConfDict that can be populated at runtime.
    """
    import os
    config_path = os.path.join(os.path.dirname(__file__), "lti_config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            config_data = json.load(f)
        tool_conf = ToolConfDict(config_data)

        # Set the RSA private key for each issuer/client_id pair
        private_key = get_private_key()
        for iss, clients in config_data.items():
            if isinstance(clients, list):
                for client in clients:
                    tool_conf.set_private_key(
                        iss, private_key, client_id=client.get("client_id")
                    )
            elif isinstance(clients, dict) and clients.get("client_id"):
                tool_conf.set_private_key(
                    iss, private_key, client_id=clients.get("client_id")
                )
        return tool_conf

    # Default empty config (must be configured before use)
    return ToolConfDict({})


def _get_jwks() -> dict[str, Any]:
    """Get the JWKS (JSON Web Key Set) for this tool.

    Generates an RSA key pair on first call and caches it.
    """
    global _jwks_cache, _private_key_cache
    if "_jwks_cache" not in globals() or _jwks_cache is None:
        _generate_keys()
    return _jwks_cache


_jwks_cache: dict[str, Any] | None = None
_private_key_cache: str | None = None


def _generate_keys() -> None:
    """Generate RSA key pair for LTI JWT signing."""
    global _jwks_cache, _private_key_cache
    from jwcrypto import jwk

    key = jwk.JWK.generate(kty="RSA", size=2048, kid="eduinsight-1", use="sig", alg="RS256")
    _private_key_cache = key.export_to_pem(private_key=True, password=None).decode()
    public_jwk = json.loads(key.export_public())
    _jwks_cache = {"keys": [public_jwk]}
    logger.info("Generated RSA key pair for LTI (kid=%s)", public_jwk.get("kid"))


def get_private_key() -> str:
    """Get the RSA private key PEM for JWT signing."""
    global _private_key_cache
    if _private_key_cache is None:
        _generate_keys()
    return _private_key_cache  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# FastAPI Router with LTI endpoints
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/lti", tags=["lti"])


@router.get("/jwks")
async def jwks_endpoint() -> dict[str, Any]:
    """Serve the public JWKS for Moodle to verify our JWTs."""
    return _get_jwks()


@router.post("/login")
async def lti_login(request: Request) -> Response:
    """Handle OIDC login initiation from Moodle.

    Moodle sends: iss, login_hint, target_link_uri, lti_message_hint
    We redirect back to Moodle's auth endpoint.
    """
    form_data = dict(await request.form())
    lti_request = FastAPILTIRequest(request, form_data)
    tool_config = _get_tool_config()

    try:
        oidc_login = FastAPIOIDCLogin(lti_request, tool_config)
        target_link_uri = form_data.get("target_link_uri", str(request.url_for("lti_launch")))
        # redirect() already returns a Response (calls do_redirect internally)
        return oidc_login.redirect(target_link_uri, js_redirect=True)
    except Exception as e:
        logger.error("LTI login failed: %s", e)
        return HTMLResponse(
            content=f"<h1>LTI Login Error</h1><p>{e}</p>",
            status_code=400,
        )


@router.post("/launch")
async def lti_launch(request: Request) -> Response:
    """Handle LTI 1.3 resource link launch from Moodle.

    Validates the JWT id_token, extracts user/course info,
    and redirects to the EduInsight chat UI with context.
    """
    form_data = dict(await request.form())
    lti_request = FastAPILTIRequest(request, form_data)
    tool_config = _get_tool_config()

    try:
        launch = FastAPIMessageLaunch(lti_request, tool_config)
        launch.validate()

        # Extract user and course information from LTI claims
        launch_data = launch.get_launch_data()
        launch_id = launch.get_launch_id()

        # Store launch data for later API calls
        _launch_cache[launch_id] = launch_data

        # Extract key fields
        user_id = _extract_user_id(launch_data)
        course_info = _extract_course_info(launch_data)
        user_name = _extract_user_name(launch_data)
        instructor = _is_instructor(launch_data)

        logger.info(
            "LTI launch: user=%s course=%s name=%s role=%s",
            user_id, course_info.get("label", "?"), user_name,
            "instructor" if instructor else "learner",
        )

        # Build query params with LTI context
        params = {
            "lti": "1",
            "user_id": str(user_id),
            "launch_id": launch_id,
        }
        if user_name:
            params["name"] = user_name
        if course_info.get("label"):
            params["course"] = course_info["label"]
        if course_info.get("title"):
            params["course_name"] = course_info["title"]
        if instructor:
            params["role"] = "instructor"

        # Bridge LTI identity to a JWT EduInsight session ----------------
        # 1. Find or create local user matching the moodle_user_id.
        moodle_id = int(user_id) if str(user_id).isdigit() else 0
        username = f"lti_{moodle_id}" if moodle_id else f"lti_user_{launch_id[:8]}"
        existing = get_user_by_username(username)
        if existing:
            local_user = _row_to_user(existing)
        else:
            random_pw = hashlib.sha256(f"{username}-{time.time()}".encode()).hexdigest()
            local_user = create_user(
                RegisterRequest(
                    username=username,
                    password=random_pw,
                    display_name=user_name or username,
                    role="teacher" if instructor else "student",
                    moodle_user_id=moodle_id or None,
                )
            )
        token = create_access_token(local_user)

        # 2. Decide where to send the browser. If FRONTEND_URL is set,
        #    drop into the Next.js /lti/return handler with token + context.
        target_path = "/lti/return"
        params["token"] = token
        params["role"] = "instructor" if instructor else "learner"
        params["username"] = local_user.username

        if settings.frontend_url:
            redirect_url = (
                settings.frontend_url.rstrip("/")
                + target_path
                + "?"
                + urllib.parse.urlencode(params)
            )
        else:
            # Fallback: vanilla HTML demo UI
            base_path = "/teacher" if instructor else "/"
            redirect_url = f"{base_path}?{urllib.parse.urlencode(params)}"

        response = RedirectResponse(url=redirect_url, status_code=302)
        return response

    except Exception as e:
        logger.error("LTI launch failed: %s", e)
        return HTMLResponse(
            content=f"<h1>LTI Launch Error</h1><p>{e}</p>",
            status_code=400,
        )


@router.get("/config")
async def lti_config_info() -> dict[str, Any]:
    """Return LTI configuration info for setting up in Moodle.

    Teachers/admins use this to configure EduInsight as an External Tool.
    """
    from .config import settings

    base_url = f"http://{settings.host}:{settings.port}"
    return {
        "tool_name": "EduInsight AI 助教",
        "description": "AI 學習助教 — 記住每位學生的學習狀況，提供個人化輔導",
        "setup_instructions": {
            "tool_url": f"{base_url}/lti/launch",
            "login_url": f"{base_url}/lti/login",
            "jwks_url": f"{base_url}/lti/jwks",
            "redirect_uris": [f"{base_url}/lti/launch"],
            "note": "在 Moodle 管理面板 → 外掛程式 → 活動模組 → 外部工具 → 管理工具 中設定",
        },
        "supported_messages": [
            {"type": "LtiResourceLinkRequest", "target_link_uri": f"{base_url}/lti/launch"}
        ],
    }


# ---------------------------------------------------------------------------
# Helpers to extract LTI claims
# ---------------------------------------------------------------------------


def _extract_user_id(launch_data: dict[str, Any]) -> int:
    """Extract a numeric user ID from LTI launch data.

    Uses the 'sub' claim (platform user ID). Falls back to hashing
    if the value isn't numeric.
    """
    sub = launch_data.get("sub", "0")
    try:
        return int(sub)
    except (ValueError, TypeError):
        # Hash non-numeric IDs to a stable integer
        return int(hashlib.md5(str(sub).encode()).hexdigest()[:8], 16)


def _extract_user_name(launch_data: dict[str, Any]) -> str:
    """Extract user display name from LTI claims."""
    name = launch_data.get("name", "")
    if not name:
        given = launch_data.get("given_name", "")
        family = launch_data.get("family_name", "")
        name = f"{given} {family}".strip()
    return name


def _extract_course_info(launch_data: dict[str, Any]) -> dict[str, str]:
    """Extract course info from LTI context claim."""
    context = launch_data.get(
        "https://purl.imsglobal.org/spec/lti/claim/context", {}
    )
    return {
        "id": context.get("id", ""),
        "label": context.get("label", ""),
        "title": context.get("title", ""),
    }


# Instructor role URI patterns (LTI 1.3 / LIS v2 vocabulary)
_INSTRUCTOR_ROLE_PATTERNS = (
    "#Instructor",
    "#TeachingAssistant",
    "#Administrator",
    "#ContentDeveloper",
    "#Mentor",
)


def _extract_roles(launch_data: dict[str, Any]) -> list[str]:
    """Extract roles from LTI roles claim.

    Returns the raw list of role URIs from the JWT.
    """
    return launch_data.get(
        "https://purl.imsglobal.org/spec/lti/claim/roles", []
    )


def _is_instructor(launch_data: dict[str, Any]) -> bool:
    """Check if the user has an instructor/admin role.

    Matches against standard LIS v2 role URIs:
      http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor
      http://purl.imsglobal.org/vocab/lis/v2/institution/person#Instructor
      etc.
    """
    roles = _extract_roles(launch_data)
    for role in roles:
        for pattern in _INSTRUCTOR_ROLE_PATTERNS:
            if pattern in role:
                return True
    return False
