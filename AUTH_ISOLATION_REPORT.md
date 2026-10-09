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
