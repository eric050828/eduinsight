"""Concurrent requests that read Lite-Mem must never produce a 500.

Lite-Mem shares one SQLite connection; sync handlers run in a thread pool, so
without the global memory lock simultaneous reads race on the cursor.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

import eduinsight.app as app_module
from eduinsight.memory_lock import LockedMemory

# Lite-Mem readers across diagnostics, analytics, assistant history and reports.
TEACHER_PATHS = [
    "/diagnostics/ds101/overview",
    "/diagnostics/ds101/hard-topics",
    "/diagnostics/ds101/clusters",
    "/analytics/student/1001",
    "/analytics/student/1002/trajectory",
    "/analytics/student/1004/risk",
    "/analytics/class?course_id=ds101",
    "/analytics-extra/student/1001/weekly-hours",
    "/analytics-extra/student/1003/skills",
    "/class-analytics/ds101/skills",
    "/class-analytics/ds101/weekly-hours",
    "/teacher/students",
    "/teacher/students/1001/memories",
    "/reports/weekly/ds101",
]
STUDENT_PATHS = [
    "/me/profile-stats",
    "/me/achievements",
]
ROUNDS = 5
CONCURRENCY = 10


@pytest.fixture
async def seeded(tmp_path, auth_headers):
    from litemem import Memory

    app_module._memory = Memory(str(tmp_path / "seed.db"))
    app_module._assistant = app_module.LearningAssistant(app_module._memory)
    transport = ASGITransport(app=app_module.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/demo/reset", headers=auth_headers("admin"))
        assert resp.status_code == 200, resp.text
        yield client


def test_application_memory_is_locked_after_reset(seeded) -> None:
    assert isinstance(app_module._memory, LockedMemory)
    assert isinstance(app_module.get_assistant().memory, LockedMemory)


async def test_concurrent_memory_reads_never_500(seeded, auth_headers) -> None:
    teacher = auth_headers("teacher")
    student = auth_headers("student1001")
    requests = [(p, teacher) for p in TEACHER_PATHS] + [(p, student) for p in STUDENT_PATHS]

    for _ in range(ROUNDS):
        batch = [requests[i % len(requests)] for i in range(len(requests) * 2)]
        sem = asyncio.Semaphore(CONCURRENCY)

        async def hit(path, headers):
            async with sem:
                return path, await seeded.get(path, headers=headers)

        results = await asyncio.gather(*(hit(p, h) for p, h in batch))
        failures = [(p, r.status_code, r.text[:200]) for p, r in results if r.status_code >= 500]
        assert not failures, failures
        # The paths must actually be served (not silently 404/403).
        assert all(r.status_code == 200 for _, r in results), [
            (p, r.status_code) for p, r in results if r.status_code != 200
        ]
