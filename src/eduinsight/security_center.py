"""Admin security overview: configuration checks and privileged accounts.

Checks read the running configuration; secret values are never returned, only
whether they meet the startup rules. The default demo password check verifies
active admin hashes against the published demo passwords (bcrypt, so it is
limited to admins). Results are a snapshot of this process, not an audit of
the host, network or reverse proxy (TLS, firewall and IP rules live there).
"""

from __future__ import annotations

import time
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from . import auth
from .auth import AuthUser, require_role
from .config import demo_enabled, jwt_secret_is_strong, settings
from .platform_admin import record_audit

router = APIRouter(prefix="/platform", tags=["platform"])

Status = Literal["pass", "warn", "fail"]
# Published in the handover document and README; must never protect a real admin.
_DEMO_ADMIN_PASSWORDS = ("admin123",)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class SecurityCheck(BaseModel):
    id: str
    title: str
    status: Status
    detail: str


class AdminAccount(BaseModel):
    id: int
    username: str
    display_name: str
    active: bool


class SecurityReport(BaseModel):
    generated_at: float
    environment: str
    summary: dict[Status, int]
    checks: list[SecurityCheck]
    role_counts: dict[str, int]
    inactive_count: int
    admins: list[AdminAccount]


def _check(id: str, title: str, ok: bool, good: str, bad: str, *, bad_status: Status = "fail"):
    return SecurityCheck(id=id, title=title, status="pass" if ok else bad_status,
                         detail=good if ok else bad)


def _cors_check() -> SecurityCheck:
    origins = settings.cors_origin_list
    if "*" in origins:
        return SecurityCheck(id="cors", title="跨來源存取（CORS）", status="fail",
                             detail="允許任何網站（*）以登入者身分呼叫 API。")
    insecure = [o for o in origins if urlparse(o).scheme == "http"
                and urlparse(o).hostname not in _LOCAL_HOSTS]
    listed = "、".join(origins) or "（無）"
    if insecure:
        detail = f"允許的來源含未加密的 http：{'、'.join(insecure)}。全部來源：{listed}"
        return SecurityCheck(id="cors", title="跨來源存取（CORS）", status="warn", detail=detail)
    return SecurityCheck(id="cors", title="跨來源存取（CORS）", status="pass",
                         detail=f"只允許：{listed}")


def _checks(admins: list[dict]) -> list[SecurityCheck]:
    production = settings.env == "production"
    days = settings.jwt_expire_minutes / 1440
    default_admins = [
        row["username"] for row in admins if row["active"] and any(
            auth.verify_password(password, row["password_hash"])
            for password in _DEMO_ADMIN_PASSWORDS
        )
    ]
    active_admins = [row for row in admins if row["active"]]
    mb = 1024 * 1024
    return [
        _check("environment", "執行模式", production, "production（正式環境）。",
               "development：示範帳號與 /demo/* 可能可用，不應對外公開。", bad_status="warn"),
        _check("jwt_secret", "登入權杖簽章密鑰", jwt_secret_is_strong(settings.jwt_secret),
               "已設定至少 32 字元的隨機密鑰（不顯示內容）。",
               "密鑰太短或仍是範例值；任何人都可能偽造登入。production 會拒絕啟動。",
               bad_status="fail" if production else "warn"),
        _check("demo", "示範功能", not demo_enabled(), "已關閉，/demo/* 回 404。",
               "已開啟：管理員可重設資料並建立示範帳號。",
               bad_status="fail" if production else "warn"),
        _check("default_admin_password", "管理員預設密碼", not default_admins,
               "沒有啟用中的管理員使用公開的示範密碼。",
               f"下列管理員仍使用公開的示範密碼：{'、'.join(default_admins)}。請立即重設。"),
        _check("admin_count", "管理員帳號", 0 < len(active_admins) <= 3,
               f"{len(active_admins)} 個啟用中的管理員。",
               f"{len(active_admins)} 個啟用中的管理員；建議 1–3 個，並停用不再使用的帳號。",
               bad_status="warn"),
        _check("login_throttle", "登入失敗限速", settings.login_throttle_enabled,
               "已開啟：連續登入失敗會暫時鎖定（429）。", "已關閉：密碼可被無限次嘗試。"),
        _check("lti", "Moodle LTI 橋接", not settings.enable_lti_bridge,
               "已關閉（目前未使用）。", "已開啟：請確認 Moodle 端的金鑰與網址設定正確。",
               bad_status="warn"),
        _cors_check(),
        _check("token_lifetime", "登入有效期", days <= 7,
               f"{days:g} 天；登出、改密碼或停用帳號會讓舊權杖失效。",
               f"{days:g} 天，超過建議的 7 天。", bad_status="warn"),
        SecurityCheck(id="upload_limits", title="上傳大小限制", status="pass", detail=(
            f"教材 {settings.max_material_bytes // mb} MB、"
            f"講課錄音 {settings.max_lecture_bytes // mb} MB、"
            f"匯入 {settings.max_import_bytes // mb} MB、"
            f"一般請求 {settings.max_body_bytes // mb} MB。"
        )),
    ]


@router.get("/security", response_model=SecurityReport)
def security_report(user: AuthUser = Depends(require_role("admin"))) -> SecurityReport:
    with auth._db() as conn:  # noqa: SLF001
        admins = [dict(row) for row in conn.execute(
            "SELECT id, username, display_name, active, password_hash FROM users "
            "WHERE role = 'admin' ORDER BY username, id",
        )]
        role_counts = {row["role"]: row["n"] for row in conn.execute(
            "SELECT role, COUNT(*) AS n FROM users WHERE active = 1 GROUP BY role",
        )}
        inactive = conn.execute("SELECT COUNT(*) FROM users WHERE active = 0").fetchone()[0]
    checks = _checks(admins)
    record_audit(user.username, "security.check", "platform")
    return SecurityReport(
        generated_at=time.time(), environment=settings.env,
        summary={s: sum(c.status == s for c in checks) for s in ("pass", "warn", "fail")},
        checks=checks,
        role_counts={role: role_counts.get(role, 0) for role in ("student", "teacher", "admin")},
        inactive_count=inactive,
        admins=[AdminAccount(id=row["id"], username=row["username"],
                             display_name=row["display_name"], active=bool(row["active"]))
                for row in admins],
    )
