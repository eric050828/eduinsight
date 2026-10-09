# Authentication and data isolation audit

All application and module router registrations were audited. Other data modules expose managers, not additional HTTP routers; only auth and LTI routers are included by app.py.

Student ownership uses the authenticated `moodle_user_id`, never the auth database row ID. Other student IDs return 403; unknown resources return 404. Shared quiz/attendance sessions are classroom resources, while `/sessions/*` are private chat sessions. Mapped teachers retain `TEACHER_COURSE_MAP` course scoping; admin and unmapped teachers retain the existing unrestricted policy. Demo reset/semester operations require teacher/admin and operate on the shared demo dataset.

## Route classification

| Method | Path | Class | Guard applied |
| --- | --- | --- | --- |
| GET | `/health` | Public | None (auth/LTI protocol where applicable) |
| POST | `/chat` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; chat session ownership and teacher course; mapped teacher course scope |
| POST | `/record-struggle` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment |
| GET | `/courses/{moodle_user_id}` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment |
| GET | `/moodle/grades/{course_id}/{moodle_user_id}` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment |
| GET | `/teacher/students` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| GET | `/teacher/me/course` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; JWT identity; reject different username |
| GET | `/teacher/students/{moodle_user_id}/memories` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; student ownership / mapped teacher enrollment |
| GET | `/teacher/summaries` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| GET | `/student/{moodle_user_id}/conversations` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; mapped teacher course scope |
| GET | `/student/{moodle_user_id}/courses/{course_id}/sessions` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; mapped teacher course scope |
| GET | `/student/{moodle_user_id}/courses` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; mapped teacher course scope |
| POST | `/student/{moodle_user_id}/courses/{course_id}/sessions` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; mapped teacher course scope |
| GET | `/sessions/{session_id}` | Student own data | `Depends(get_current_user)`; chat session ownership and teacher course |
| GET | `/sessions/{session_id}/messages` | Student own data | `Depends(get_current_user)`; chat session ownership and teacher course |
| PATCH | `/sessions/{session_id}` | Student own data | `Depends(get_current_user)`; chat session ownership and teacher course |
| DELETE | `/sessions/{session_id}` | Student own data | `Depends(get_current_user)`; chat session ownership and teacher course |
| GET | `/analytics/student/{moodle_user_id}` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment |
| GET | `/analytics/student/{moodle_user_id}/trajectory` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment |
| GET | `/analytics/student/{moodle_user_id}/risk` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment |
| GET | `/analytics/class` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| POST | `/courses/{course_id}/materials` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| POST | `/courses/{course_id}/materials/youtube` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| GET | `/courses/{course_id}/materials/{filename}/markdown` | Any logged-in user | `Depends(get_current_user)`; mapped teacher course scope |
| GET | `/courses/{course_id}/materials` | Any logged-in user | `Depends(get_current_user)`; mapped teacher course scope |
| DELETE | `/courses/{course_id}/materials/{filename}` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| POST | `/courses/{course_id}/quiz/generate` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| POST | `/quiz/sessions` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| POST | `/quiz/sessions/{session_id}/activate` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; resource course scope |
| POST | `/quiz/sessions/{session_id}/close` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; resource course scope |
| GET | `/quiz/sessions/{session_id}` | Any logged-in user | `Depends(get_current_user)`; resource course scope |
| GET | `/quiz/sessions/{session_id}/questions` | Any logged-in user | `Depends(get_current_user)`; resource course scope |
| POST | `/quiz/sessions/{session_id}/answer` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; resource course scope |
| GET | `/quiz/sessions/{session_id}/stats` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; resource course scope |
| GET | `/quiz/sessions` | Any logged-in user | `Depends(get_current_user)`; mapped teacher course scope |
| POST | `/interaction/polls` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| POST | `/interaction/polls/{poll_id}/activate` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; resource course scope |
| POST | `/interaction/polls/{poll_id}/close` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; resource course scope |
| POST | `/interaction/polls/{poll_id}/vote` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; resource course scope |
| GET | `/interaction/polls/{poll_id}/stats` | Any logged-in user | `Depends(get_current_user)`; resource course scope |
| GET | `/interaction/polls` | Any logged-in user | `Depends(get_current_user)`; mapped teacher course scope |
| POST | `/interaction/questions` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; mapped teacher course scope |
| POST | `/interaction/questions/{question_id}/upvote` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; resource course scope |
| POST | `/interaction/questions/{question_id}/resolve` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; resource course scope |
| GET | `/interaction/questions` | Any logged-in user | `Depends(get_current_user)`; mapped teacher course scope |
| POST | `/interaction/danmaku` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; mapped teacher course scope |
| GET | `/interaction/danmaku` | Any logged-in user | `Depends(get_current_user)`; mapped teacher course scope |
| POST | `/lectures/{course_id}/upload` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| GET | `/lectures/{course_id}` | Any logged-in user | `Depends(get_current_user)`; mapped teacher course scope |
| GET | `/lectures/{course_id}/{lecture_id}/transcript` | Any logged-in user | `Depends(get_current_user)`; mapped teacher course scope |
| DELETE | `/lectures/{course_id}/{lecture_id}` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| POST | `/demo/reset` | Teacher/admin only | `Depends(require_role("teacher", "admin"))` |
| POST | `/demo/semester` | Teacher/admin only | `Depends(require_role("teacher", "admin"))` |
| GET | `/export/student/{moodle_user_id}` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment |
| GET | `/export/all` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| POST | `/import` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; student ownership / mapped teacher enrollment |
| POST | `/attendance/sessions` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| POST | `/attendance/sessions/{session_id}/close` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; resource course scope |
| GET | `/attendance/sessions/{session_id}` | Any logged-in user | `Depends(get_current_user)`; resource course scope |
| GET | `/attendance/sessions` | Any logged-in user | `Depends(get_current_user)`; mapped teacher course scope |
| POST | `/attendance/sessions/{session_id}/checkin` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; resource course scope |
| GET | `/attendance/sessions/{session_id}/records` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; resource course scope |
| GET | `/attendance/sessions/{session_id}/stats` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; resource course scope |
| GET | `/attendance/student/{student_id}/history` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; mapped teacher course scope |
| POST | `/attendance/checkin-by-code` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; mapped teacher course scope |
| GET | `/grades/courses` | Any logged-in user | `Depends(get_current_user)`; mapped teacher course scope |
| POST | `/grades/{course_id}/categories` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| GET | `/grades/{course_id}/categories` | Any logged-in user | `Depends(get_current_user)`; mapped teacher course scope |
| POST | `/grades/{course_id}/scores` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| GET | `/grades/{course_id}/scores` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; mapped teacher course scope; default student filter to current user |
| DELETE | `/grades/{course_id}/scores` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| GET | `/grades/{course_id}/student/{student_id}` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; mapped teacher course scope |
| GET | `/grades/{course_id}/overview` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| GET | `/reports/weekly/{course_id}` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| GET | `/reports/correlation/{course_id}` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| GET | `/reports/export/excel/{course_id}` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| GET | `/` | Public | None (auth/LTI protocol where applicable) |
| GET | `/student` | Any logged-in user | `Depends(get_current_user)` |
| GET | `/teacher` | Teacher/admin only | `Depends(require_role("teacher", "admin"))` |
| GET | `/demo` | Teacher/admin only | `Depends(require_role("teacher", "admin"))` |
| GET | `/semester` | Teacher/admin only | `Depends(require_role("teacher", "admin"))` |
| GET | `/classroom/{course_id}/snapshot` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| POST | `/office-hours/slots` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; mapped teacher course scope |
| GET | `/office-hours/slots` | Any logged-in user | `Depends(get_current_user)`; mapped teacher course scope |
| GET | `/office-hours/slots/{slot_id}` | Any logged-in user | `Depends(get_current_user)`; resource course scope |
| POST | `/office-hours/slots/{slot_id}/cancel` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; resource course scope |
| POST | `/office-hours/slots/{slot_id}/book` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; resource course scope |
| GET | `/office-hours/bookings` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment; mapped teacher course scope; default student filter to current user |
| GET | `/office-hours/bookings/{booking_id}` | Student own data | `Depends(get_current_user)`; booking ownership and teacher course |
| POST | `/office-hours/bookings/{booking_id}/start` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; booking ownership and teacher course |
| POST | `/office-hours/bookings/{booking_id}/resolve` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; booking ownership and teacher course |
| POST | `/office-hours/bookings/{booking_id}/cancel` | Student own data | `Depends(get_current_user)`; booking ownership and teacher course |
| POST | `/office-hours/bookings/{booking_id}/no-show` | Teacher/admin only | `Depends(require_role("teacher", "admin"))`; booking ownership and teacher course |
| GET | `/office-hours/students/{student_id}/summary` | Student own data | `Depends(get_current_user)`; student ownership / mapped teacher enrollment |
| POST | `/auth/register` | Public | None (auth/LTI protocol where applicable) |
| POST | `/auth/login` | Public | None (auth/LTI protocol where applicable) |
| GET | `/auth/me` | Any logged-in user | `Depends(get_current_user)` |
| POST | `/auth/lti-bridge` | Public | None (auth/LTI protocol where applicable) |
| GET | `/lti/jwks` | Public | None (auth/LTI protocol where applicable) |
| POST | `/lti/login` | Public | None (auth/LTI protocol where applicable) |
| POST | `/lti/launch` | Public | None (auth/LTI protocol where applicable) |
| GET | `/lti/config` | Public | None (auth/LTI protocol where applicable) |
| GET, HEAD | `/static/*` | Public | Static HTML/CSS/JS assets only |
| GET, HEAD | `/docs`, `/docs/oauth2-redirect`, `/redoc`, `/openapi.json` | Public | Framework API documentation/schema only |

## Deliberately public endpoints

- `GET /health`: service health and existing diagnostic metadata.
- `GET /`: landing/login entry page.
- `POST /auth/register`, `POST /auth/login`: establish authentication; existing account provisioning behavior preserved.
- `POST /auth/lti-bridge`: existing development bridge; retained within the requested public auth scope because `tests/test_auth.py` explicitly exercises unauthenticated launches and identity reuse. This bridge can issue tokens for supplied identities/roles; it remains a development trust assumption, not a production-safe identity verification mechanism.
- `GET /lti/jwks`, `POST /lti/login`, `POST /lti/launch`, `GET /lti/config`: public LTI discovery/setup/launch protocol; existing LTI verification retained.
- `/static/*` and framework documentation/schema: static assets and API discovery, without student data handlers.

No `/demo/*` operation was left public. `/demo`, `/semester`, `/teacher` HTML entry routes require teacher/admin; `/student` requires login. Existing public registration still permits teacher accounts and explicit Moodle IDs, as covered by auth tests; this change secures data access for authenticated identities without changing that provisioning model.

## Files changed

- `src/eduinsight/app.py`
- `tests/conftest.py`
- `tests/test_analytics.py`
- `tests/test_app_init.py`
- `tests/test_attendance.py`
- `tests/test_classroom_assistant.py`
- `tests/test_conversations.py`
- `tests/test_course_isolation.py`
- `tests/test_demo.py`
- `tests/test_e2e_quiz_flow.py`
- `tests/test_export_import.py`
- `tests/test_grades.py`
- `tests/test_interaction.py`
- `tests/test_lectures.py`
- `tests/test_live_quiz.py`
- `tests/test_office_hours.py`
- `tests/test_quiz.py`
- `tests/test_rag_api.py`
- `tests/test_report.py`
- `tests/test_semester.py`
- `tests/test_teacher_dashboard.py`
- `tests/test_auth_isolation.py`
- `AUTH_ISOLATION_REPORT.md`

## Verification

Full suite: **645 passed in 51.01s**. This includes 100 authentication/isolation tests: every protected route rejects unauthenticated requests, invalid bearer tokens are rejected, cross-student reads/writes fail, private sessions/messages are isolated, teachers are allowed within their course scope, and students are blocked from teacher routes.

The requested command is run in PowerShell with `UV_PROJECT_ENVIRONMENT=$env:TEMP/be-venv`, Python 3.12 and the frozen lockfile. The sandbox denies the default uv cache and network downloads, and the prebuilt venv lacks pytest. Validation uses a writable temporary uv cache and `UV_NO_SYNC=1` after restoring locally cached pytest 8.0.0 / pytest-asyncio 0.23.0 into that venv. The old asyncio plugin has a temporary environment-only compatibility adjustment for pytest Package collectors; no dependency or lockfile changes are committed.

Legacy API clients now explicitly send admin bearer headers. Authorization tests use real JWTs and an isolated auth database, without overriding get_current_user or require_role. Fixtures use lower bcrypt cost only for authorization test account setup. Existing Windows timestamp assumptions are made deterministic in attendance/interaction/quiz tests; lecture API tests mock external LLM summaries.

No branches were switched, no servers were started, no other repositories were modified, and no push was performed.

## Commit status

The branch remains `fix/auth-data-isolation`. Commit creation was attempted after the full suite passed, but the workspace permission profile grants read-only access to `.git`; Git cannot create `.git/index.lock` (`Permission denied`). Nothing was staged or committed, and nothing was pushed. The intended logical commits are:

1. `fix: enforce authentication and ownership on backend data routes` ? `src/eduinsight/app.py`.
2. `test: cover auth isolation and authenticate existing API fixtures` ? tests and this report.

Both commit messages should end with:

`Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`

## Added after the audit

- `GET /public/settings` is intentionally public. It returns only `site_name` and `maintenance_banner`; every other platform setting is admin-only (`/admin/settings`).
- Routes added later (messaging, forum, submission files, enrollment, class analytics, achievements, admin management, preferences) all require login and follow the same ownership rules; see their tests for the exact 401/403 coverage.

## Security hardening

Completed on `feat/platform-apis`. This section supersedes the historical statements above
about public teacher registration, caller-selected Moodle identities, bridge identity reuse,
and demo seeding in production. No branch switching, staging, commit, push, or server launch
was performed; port 8000 was not used. Another agent edited the shared tree in parallel.
This agent did not edit `app.py` or the other agent's implementation files.

| Finding | Changes and regression coverage |
| --- | --- |
| Deployment mode and demo accounts | Built on the existing config diff. `EDUINSIGHT_ENV` defaults to development and accepts only development/production. Production rejects the default, empty, short (<32 characters), and placeholder JWT secrets at settings construction and through `validate_production_settings()`. `demo_enabled()` permits demos only in development, with an explicit false override; true never bypasses production. Docker defaults to production. `seed_demo_users()` exits before any seed writes when demos are disabled. Tests cover all environment/override combinations and secret validation. |
| Unauthenticated development LTI bridge | Disabled unless demos are enabled AND `EDUINSIGHT_ENABLE_LTI_BRIDGE=true`. Admin is rejected; any existing username or Moodle ID yields 409 without a token, including disabled accounts and accounts with a different username. Creation races are also stopped by database constraints. Tests cover opt-in, production rejection, roles, identity reuse, and normal bearer use for a new account. |
| Public registration and identity collisions | A separate public request model forbids all extra fields, including role and moodle_user_id (422). Trusted backend `RegisterRequest` remains available to admin provisioning. Public accounts are always students. Identity allocation considers all roles and executes in the same immediate transaction as insertion. A partial UNIQUE index protects every non-NULL Moodle ID. Legacy migrations are serialized, idempotent, and preserve accounts; duplicate legacy identities abort before migration changes, with a reconciliation error. Auth initialization inserts the environment-specific `platform_settings.allow_self_register` default before preferences seeding can insert development defaults, preserving explicit settings. Registration enforces the stored flag. Passwords use 8..72 UTF-8 bytes in production, 4..72 in development, with HTTP/Pydantic 422 instead of uncaught bcrypt length errors. Tests include concurrent identity allocation, migration preservation/failure, admin settings, byte boundaries, login and reset validation. |
| JWT validation and revocation | HS256 is pinned; exp, iat, sub, iss and ver are required. Subjects must be positive ASCII integer strings within SQLite's ID range. Bad claims/types/algorithms/issuers/expiry return 401. `users.token_version` is migrated safely and embedded in new tokens; authentication compares it to the database. Old tokens without ver are rejected. `bump_token_version()` is called from admin management on password reset, role changes and disabling, using exactly three added call-site lines. Re-enabling does not restore old tokens. Login and LTI exchange verify the expected version again at issuance, preventing reset races from minting a new valid version. Tests cover each revocation and a reset during bcrypt verification. |
| Login abuse and event loop blocking | Username and actual client IP have independent buckets, with five failures starting a 30-second exponential lockout capped at 900 seconds. Locked attempts return 429 and Retry-After; success clears the two buckets. A lock protects the 10,000-entry store, whose entries expire after 30 minutes. `EDUINSIGHT_LOGIN_THROTTLE_ENABLED` permits isolated tests to disable it. Bcrypt verification runs through the thread pool; unknown users verify a dummy hash. New-account hashing in async routes also runs in the thread pool; synchronous admin endpoints already execute there. Tests cover username/IP isolation, backoff/cap, reset, TTL/capacity, the switch, dummy verification and worker-thread execution. |
| LTI reflected HTML, URL tokens and unbounded state | Errors return generic HTML; JS redirects use HTTP 302 without interpolating URLs into script HTML, and unsafe schemes are rejected. Verified launches redirect with a random 60-second exchange code; `POST /lti/exchange` consumes it atomically once and checks account activity/version before minting a token. All LTI routes, including validation errors, set Cache-Control: no-store; launch redirects additionally set Referrer-Policy: no-referrer. Session IDs use secrets.token_urlsafe(32); unknown/expired client cookies are replaced, and only unexpired server-issued sessions can resume. HTTPS session cookies are Secure and HttpOnly. Session/launch stores expire after one hour; session, launch and exchange stores each cap at 1,000 entries. Tests cover reflected payloads, actual OIDC login/session persistence, single-use/expiry/account checks, atomic consumption, cookies, TTL and capacity. |
| Deployment documentation | `.env.example`, `DEPLOY.md` and README security notes cover strong secrets, clean persistent databases, admin bootstrap, closed registration, revocation, UTF-8 password limits, HTTPS/CORS, throttling and single-worker state. README's unsafe token-in-URL walkthrough was corrected. The current frontend does not use LTI; a future integration must POST the code and remove it from browser history. |

### Files touched by this agent

- `src/eduinsight/auth.py`, `src/eduinsight/config.py`, `src/eduinsight/lti.py`.
- `src/eduinsight/admin_manage.py`: exactly three added lines calling token-version bumps.
- `.env.example`, `DEPLOY.md`, `Dockerfile`, `README.md` (security notes/examples only), and this report.
- New `tests/test_security_auth.py` (95 tests); minimal assumption updates in
  `tests/test_auth.py` and `tests/test_admin_manage.py`. Shared-tree changes to other files
  and enrollment-related changes in existing tests belong to the parallel agent.

### New environment variables

| Variable | Default / behavior |
| --- | --- |
| `EDUINSIGHT_ENV` | `development`; Docker defaults to `production`. |
| `EDUINSIGHT_DEMO_MODE` | Unset derives from environment; false disables development demos, production always disables them. |
| `EDUINSIGHT_ENABLE_LTI_BRIDGE` | false; explicit development demo opt-in only. |
| `EDUINSIGHT_LOGIN_THROTTLE_ENABLED` | true; false is intended for isolated tests. |

`allow_self_register` is a database platform setting, not a new environment variable.
Production JWT signing still uses `EDUINSIGHT_JWT_SECRET`.

### app.py integration required from the other agent

1. At the beginning of lifespan, before DB initialization or any seed writes, call
   `.config.validate_production_settings()`; propagate any validation error.
2. Keep normal auth/session/enrollment DB initialization enabled in production. Gate
   every demo seed behind `.config.demo_enabled()` (startup notifications, structure,
   audit/catalog demo setup, and all demo reset/semester seed calls). The auth user seed
   has its own internal gate as well.
3. Gate demo reset/semester operations and demo HTML entry routes with demo_enabled(),
   returning 404 when disabled while retaining their authorization dependencies.
4. Retain `app.include_router(lti_router)`; it already includes POST /lti/exchange.
   No new app-level exchange router or auth-mode wiring is needed for these fixes.

The parallel agent's current `app.py` diff already contains startup validation, the
startup demo gate, demo-route gates, and the existing LTI router inclusion. This agent
only inspected that integration; it did not edit `app.py`.

### Verification

Requested PowerShell command, with the exact temporary environment/cache and frozen lockfile:

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP 'be-venv'
$env:UV_CACHE_DIR = Join-Path $env:TEMP 'be-uv-cache'
uv run --python 3.12 --frozen pytest -q tests/test_security_auth.py tests/test_auth_isolation.py tests/test_admin_manage.py
```

Final result: **410 passed in 34.75s**, including all **95** new security regressions.
The first run had **402 passed and one failure** in
`tests/test_auth_isolation.py::test_student_score_and_booking_lists_are_filtered`, caused
by the parallel enrollment work enforcing course enrollment; its owner subsequently
updated the enrollment assumptions, and the final requested run passed without exclusions.
Supplemental standalone auth/LTI coverage: **28 passed**. An expanded run before the
last reset-race regression had **437 passed** across all five modules.
Ruff passed for auth.py, config.py, lti.py and test_security_auth.py. Git diff whitespace
checks passed for this agent's touched files.

Production upgrades must inspect existing demo accounts and registration settings;
hardening does not silently delete existing users or override saved admin settings.
Process-local throttling and LTI state require a single worker until shared stores are added.

## Phase 2 hardening

Completed on `feat/platform-apis` with no branch switches, staging, commits or pushes.
The pre-change tree was clean. `AUTH_ISOLATION_REPORT.md` was read before changes;
phase 1 authentication/enrollment policy is preserved. No backend listener was
started, no request was made to port 8000, and no real application DB was opened.
HTTP verification uses in-process ASGI/TestClient and conftest's temporary auth
and memory paths; material files are also isolated in temporary directories.

### 1. Upload/body and parser resource limits

- `security.BodyLimitMiddleware` counts bytes on ASGI receive before Starlette's
  multipart parser buffers/spools the complete body. Known upload paths have
  per-file counters driven by a streaming multipart parser. They abort on the
  first offending chunk with 413 (`payload_too_large`), including requests with
  no Content-Length or an incorrectly small header. Known oversized lengths are
  rejected without reading. Multipart failures use Starlette's cleanup exception
  so already-spooled files are closed; the HTTP handler restores the 413 status.
- Exact defaults: materials 25 MiB, lecture audio 200 MiB, JSON import 50 MiB;
  other bodies 1 MiB. Upload envelopes have a fixed extra 64 KiB allowance, while
  actual file bytes keep the exact configured cap. Multipart Content-Type on a
  normal route never exempts it. CORS headers are retained on early rejections.
- `stage_upload()` copies 64 KiB chunks to disk with its own byte counter and
  closes uploads/removes partial files on failure/cancellation. Material and
  lecture parsers receive file paths. JSON import is parsed only after the
  complete file has passed its streaming limit; JSON decoding itself still
  constructs the bounded JSON object in memory.
- ZIP inspection runs before python-pptx: 200 MiB expanded, 5,000 entries,
  per-entry and aggregate compression ratio <=100, no encrypted entries.
  A bounded central-directory scan precedes `ZipFile` entry allocation and
  validates actual count even if an attacker forges the EOCD count. This uses
  the installed Python 3.12 stdlib EOCD/ZIP64 reader, whose implementation was
  inspected locally. PDF pages/PPTX slides cap at 500 before text extraction;
  PPTX slide/XLSX sheet entries are also counted before Office parser loading.
  DOCX/XLSX receive the same ZIP check if passed to the conversion helper, but
  are still unsupported material formats; no new parser route was introduced.
- Existing attachment limits remain 10 MiB/five files, now with pre-spooling
  protection in the main app as well. Forum body/title limits (20,000/200 chars)
  and messaging text/history limits (2,000 chars/100 records) were inspected and
  retained. Existing legacy conversation/danmaku limits and admin user/audit
  limits now accept 1..200; no new list response shape was introduced.

All configurable settings and numeric defaults are documented in README.md,
DEPLOY.md and `.env.example`: `EDUINSIGHT_MAX_MATERIAL_BYTES`,
`EDUINSIGHT_MAX_LECTURE_BYTES`, `EDUINSIGHT_MAX_IMPORT_BYTES`,
`EDUINSIGHT_MAX_BODY_BYTES`, `EDUINSIGHT_MAX_ZIP_UNCOMPRESSED_BYTES`,
`EDUINSIGHT_MAX_ZIP_ENTRIES`, `EDUINSIGHT_MAX_ZIP_COMPRESSION_RATIO`,
`EDUINSIGHT_MAX_DOCUMENT_PAGES`, `EDUINSIGHT_LLM_CLI_TIMEOUT_SECONDS`,
`EDUINSIGHT_LLM_CLI_MAX_OUTPUT_BYTES`, `EDUINSIGHT_SQLITE_BUSY_TIMEOUT_MS`.

### 2. Claude CLI and provider prompt isolation

Observed locally on 2026-10-09: `claude --version` returned **2.1.295 (Claude Code)**.
`claude --help` was run and the following used flags exist in that output:

| Flag / value | Help-confirmed behavior / invocation |
| --- | --- |
| `--print` | Non-interactive completion; prompt sent through stdin |
| `--model haiku` | Select model; actual remote alias/account availability is not verified |
| `--tools ""` | Help explicitly says empty string disables all built-in tools |
| `--strict-mcp-config` | Use only explicitly supplied MCP configurations |
| `--mcp-config '{"mcpServers":{}}'` | Help accepts JSON strings; invocation supplies zero servers |
| `--no-session-persistence` | Help says sessions are not saved to disk/resumable in print mode |
| `--safe-mode` | Disables customizations, including project instructions/hooks/plugins/MCP; admin-managed policy still applies |
| `--setting-sources ""` | No user/project/local setting sources requested |
| `--disable-slash-commands` | Available flag, included to disable command/skill expansion |
| `--system-prompt ...` | Real system prompt, not a user-message `[System]` label |
| `--output-format text` | Help lists text as a supported print-mode format |

The previous `--max-turns` was not present in this installation's help and is no
longer used. `--bare` exists but was deliberately not used because help says it
skips OAuth/keychain authentication reads; safe mode preserves normal auth.

Every invocation runs in a new empty `TemporaryDirectory`, outside the repo, and
cleans it after the child exits. An allowlist retains OS/runtime/home/config
locations plus only Claude's `ANTHROPIC_API_KEY`/`CLAUDE_CODE_OAUTH_TOKEN`, if set;
unrelated JWT/Moodle/OpenAI/Gemini/Groq/AWS and other secrets are not inherited.
Input uses stdin to avoid OS command-line length limits. Concurrent stdout/stderr
readers count the combined output and cap it at 1 MiB. The 120-second deadline
covers input writing, output draining and process wait. Timeout, cancellation or
output overflow cancels reader tasks, kills the running child and awaits its exit
before directory cleanup. CLI failure returns a stable error, logging stderr only
on the server. Gemini, OpenAI and Groq share an always-present system policy:
retrieved memories/materials/transcripts/citations are untrusted data and embedded
instructions must never be followed. This policy also applies to Claude.

**Verified:** installed version/help availability and described semantics; mocked
subprocess tests assert command arguments, empty tool/MCP/settings values,
allowlisted environment, fresh cwd, stdin, combined output limits and kill/reap
on timeout/cancellation/overflow. Provider payload tests assert the policy even
without a caller-supplied system prompt.

**Assumed / not live-verified:** the installed CLI honors its advertised internal
semantics; subscription/OAuth or API authentication works with the reduced env;
remote `haiku` availability; no CLI-controlled persistence/MCP side effects; and
model adherence to the untrusted-data policy. No live model request or adversarial
model evaluation was made. This is CLI configuration isolation, not an OS sandbox;
admin-managed policy and retained authentication files remain CLI trust boundaries.
Older versions must support these flags; an unsupported invocation fails without
retrying with weaker flags.

### 3. Information disclosure

- Public/non-admin `/health` returns exactly `{status, version}`; a valid admin
  JWT retains prior LLM/memory statistics. Missing/invalid JWTs still permit
  public monitoring and never trigger private statistics.
- Moodle, material, import and other legacy exception responses now use stable
  messages/codes (`moodle_unavailable`, `material_index_failed`,
  `invalid_bundle_json`, `invalid_request`, `resource_not_found`). HTTP statuses
  are retained. Full exceptions remain in logs. Legacy material metadata rows
  with pre-existing exception text are sanitized at read without rewriting DBs.
- Unhandled exceptions return JSON 500 `{ "detail": "internal_server_error" }`.
  Non-contention SQLite operational errors follow the same generic response.

### 4. SQLite robustness and shorter attachment transactions

`db.connect()` supplies a configurable 10-second busy timeout and WAL for every
application-owned writable connection; read-only diagnostics set timeout but do
not change journal mode. The frozen Lite-Mem source already sets WAL and a
5-second busy timeout internally; it is unchanged. HTTP SQLite BUSY/LOCKED,
including extended codes or lock strings, returns JSON 503 `database_busy` and
`Retry-After: 1`. Existing history and LTI broad exception fallbacks propagate
SQLite lock failures to this handler rather than reporting empty history/400.

Serialized `schema_once()` scopes initialization to database file identity and
module, commits before recording success, and bounds its process-local cache.
Assignments, submission_files, notifications, forum, messaging, achievements,
preferences, platform_admin, course_structure, courses and enrollment now skip
DDL/default seeding on subsequent requests. Sessions/profiles and auth platform
defaults receive the same policy. Existing explicit settings and the one-time
legacy enrollment migration are preserved. A caller-owned attachment transaction
never gets committed by the schema cache; missing tables can still be created
inside that transaction and rolled back. Runtime manual table removal requires
a restart; schema changes should occur before serving requests.

Attachments authorize/check editable state and file count, stage bounded bytes
outside the write transaction, then recheck under BEGIN IMMEDIATE before inserting
metadata. Failed inserts remove staged files. Regression tests acquire a second
connection's write lock during every file read, proving staging holds no write
transaction. WAL/timeout tests use real temporary SQLite files and prove readers
still work while a writer is held, writes return 503, and writes recover afterward.

Once a background material response has started, no later failure can change its
HTTP status; the established indexing/status polling behavior is retained. Lock
failures before response start receive 503; inspect status/server logs for jobs
that fail afterward. Disk crash recovery and a durable background retry queue are
outside the requested changes.

### 5. Tests and verification

Baseline before edits: **1404 passed in 223.84s**. The **82** new regressions are in
`tests/test_security_phase2.py`; it uses real JWTs and temporary DBs, bounded
stream generators and mocked provider/subprocess calls. Existing assertions in
LLM/material/quiz tests were updated only for the deliberately hardened behavior.

Intermediate full run: **1482 passed, 1 failed in 300.84s**, due to the old quiz
assertion expecting raw exception text. The assertion now checks the stable
resource-not-found code. Final focused run after that fix and remaining hardening:
**198 passed, 0 failed in 33.73s**.

Final full-suite result: **1486 passed, 0 failed in 295.37s (0:04:55)**, including
all **82** Phase 2 regressions. No tests were skipped or excluded.

Exact requested PowerShell command (no exclusions, no UV_NO_SYNC workaround):

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $env:TEMP 'be-venv'
$env:UV_CACHE_DIR = Join-Path $env:TEMP 'be-uv-cache'
uv run --python 3.12 --frozen pytest -q
```

Ruff passes without exclusions for new db/security/phase-2 tests and changed
llm/config files. Other touched source files pass Ruff with existing line-length
and `datetime.timezone.utc` style findings excluded (`E501`, `UP017`); whole-repo
lint cleanup was not undertaken. Git diff whitespace checks pass.

### 6. Files touched / remaining limitations

- Runtime: `src/eduinsight/db.py` (new), `security.py` (new), `config.py`, `app.py`,
  `documents.py`, `llm.py`, `material_metadata.py`, `auth.py`, `lti.py`,
  `assignments.py`, `submission_files.py`, `notifications.py`, `forum.py`,
  `messaging.py`, `achievements.py`, `preferences.py`, `platform_admin.py`,
  `course_structure.py`, `courses.py`, `enrollment.py`, `sessions.py`, `profiles.py`,
  `admin_manage.py` (all paths after the first are in `src/eduinsight/`).
- Tests: `tests/test_security_phase2.py` (new), `tests/test_llm.py`,
  `tests/test_materials_meta.py`, `tests/test_quiz.py`.
- Documentation: `AUTH_ISOLATION_REPORT.md`, `README.md`, `DEPLOY.md`, `.env.example`.

No implementation item was intentionally deferred. Live CLI/account/model and
runtime CLI-internal side-effect validation could not be established by help and
mocks; the verified/assumed distinction above is explicit. No external provider,
real DB, development listener or other repository was used for verification.
