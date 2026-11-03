"""Attachment storage and enrollment use real JWTs, never the production app."""

from eduinsight.courses import enroll

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from eduinsight import assignments, auth, courses, enrollment, notifications, profiles, sessions
from eduinsight import submission_files as files
from eduinsight.config import settings
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(auth_headers, monkeypatch):
    monkeypatch.delenv("EDUINSIGHT_SUBMISSION_UPLOAD_DIR", raising=False)
    for username, moodle_id in (("outsider", 2001), ("other_outsider", 2002)):
        auth.create_user(
            auth.RegisterRequest(
                username=username,
                password="test123",
                display_name=username,
                moodle_user_id=moodle_id,
            )
        )
    for student_id in (1001, 1002):
        enroll("ds101", student_id, source="test")
        sessions.create_session(student_id, "ds101")
    app = FastAPI()
    for router in (
        auth.router,
        courses.router,
        assignments.router,
        files.router,
        enrollment.router,
        notifications.router,
        profiles.router,
    ):
        app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def make_assignment(client, auth_headers, **changes):
    response = await client.post(
        "/assignments",
        headers=auth_headers("teacher"),
        json={
            "course_id": "ds101",
            "title": "Attachment practice",
            "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            **changes,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def upload(
    client,
    auth_headers,
    assignment_id,
    filename="answer.pdf",
    content=b"answer",
    username="student1001",
):
    return await client.post(
        f"/assignments/{assignment_id}/submission/files",
        headers=auth_headers(username),
        files={"file": (filename, content, "application/pdf")},
    )


async def apply(client, auth_headers, username="outsider", course_id="ds101"):
    response = await client.post(
        "/enrollment/requests",
        headers=auth_headers(username),
        json={
            "course_id": course_id,
            "message": "Please let me join.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def invite(client, auth_headers, username="outsider", course_id="ds101"):
    response = await client.post(
        f"/courses/{course_id}/invitations",
        headers=auth_headers("admin"),
        json={"email_or_username": username, "role": "student"},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/assignments/missing/submission/files", None),
        ("GET", "/assignments/missing/submission/files", None),
        ("GET", "/assignments/missing/submission/files/missing", None),
        ("DELETE", "/assignments/missing/submission/files/missing", None),
        ("POST", "/enrollment/requests", {"course_id": "ds101"}),
        ("GET", "/enrollment/requests/mine", None),
        ("DELETE", "/enrollment/requests/1", None),
        ("GET", "/courses/ds101/enrollment/requests", None),
        ("POST", "/enrollment/requests/1/approve", None),
        ("POST", "/enrollment/requests/1/reject", None),
        ("POST", "/courses/ds101/invitations", {"email_or_username": "outsider"}),
        ("GET", "/courses/ds101/invitations", None),
        ("POST", "/invitations/missing/accept", None),
    ],
)
async def test_all_routes_require_auth(client, method, path, body):
    for headers in ({}, {"Authorization": "Bearer invalid"}):
        response = await client.request(method, path, headers=headers, json=body)
        assert response.status_code == 401, response.text


async def test_real_storage_metadata_download_delete(client, auth_headers):
    assignment_id = await make_assignment(client, auth_headers)
    response = await upload(client, auth_headers, assignment_id, "my <answer>.PDF", b"pdf contents")
    assert response.status_code == 201, response.text
    attachment = response.json()
    assert attachment["filename"] == "my _answer_.PDF"
    assert attachment["student_id"] == 1001
    assert attachment["size"] == len(b"pdf contents")
    assert "storage_path" not in attachment
    assert files.list_submission_files(assignment_id, 1001) == [attachment]
    root = Path(settings.auth_db_path).parent / "uploads" / "assignments"
    saved = list((root / assignment_id / "1001").glob("*"))
    assert len(saved) == 1 and saved[0].read_bytes() == b"pdf contents"
    assert saved[0].name == f"{attachment['id']}_{attachment['filename']}"
    for username in ("student1001", "teacher", "admin"):
        response = await client.get(attachment["download_url"], headers=auth_headers(username))
        assert response.status_code == 200
        assert response.content == b"pdf contents"
        assert "attachment" in response.headers["content-disposition"]
        assert response.headers["x-content-type-options"] == "nosniff"
    response = await client.delete(attachment["download_url"], headers=auth_headers("student1001"))
    assert response.status_code == 204
    assert not saved[0].exists()
    assert files.list_submission_files(assignment_id, 1001) == []
    assert (
        await client.get(attachment["download_url"], headers=auth_headers("student1001"))
    ).status_code == 404


async def test_metadata_helper_preserves_caller_transaction(client, auth_headers):
    assignment_id = await make_assignment(client, auth_headers)
    with pytest.raises(RuntimeError, match="rollback"):
        with assignments._db(write=True) as conn:
            conn.execute(
                "UPDATE assignments SET title = 'uncommitted' WHERE id = ?", (assignment_id,)
            )
            assert files.list_submission_files(assignment_id, 1001, connection=conn) == []
            raise RuntimeError("rollback")
    with assignments._db() as conn:
        assert (
            conn.execute("SELECT title FROM assignments WHERE id = ?", (assignment_id,)).fetchone()[
                0
            ]
            == "Attachment practice"
        )
    item = (await upload(client, auth_headers, assignment_id)).json()
    with assignments._db(write=True) as conn:
        assert files.list_submission_files(assignment_id, 1001, connection=conn) == [item]


async def test_file_ownership_enrollment_and_staff_scope(client, auth_headers):
    assignment_id = await make_assignment(client, auth_headers)
    item = (await upload(client, auth_headers, assignment_id)).json()
    base = f"/assignments/{assignment_id}/submission/files"
    for username in ("outsider", "teacher", "admin"):
        assert (
            await upload(client, auth_headers, assignment_id, username=username)
        ).status_code == 403
    for username in ("student1002", "teacher_huang", "outsider"):
        for method in ("GET", "DELETE"):
            response = await client.request(
                method, item["download_url"], headers=auth_headers(username)
            )
            assert response.status_code == 403
    for username in ("teacher", "admin"):
        response = await client.get(
            base, params={"student_id": 1001}, headers=auth_headers(username)
        )
        assert response.json() == [item]
        assert (
            await client.delete(item["download_url"], headers=auth_headers(username))
        ).status_code == 403
    assert (
        await client.get(base, params={"student_id": 1001}, headers=auth_headers("student1002"))
    ).status_code == 403
    assert (await client.get(base, headers=auth_headers("teacher"))).status_code == 422
    assert (await client.get(base, headers=auth_headers("student1002"))).json() == []
    assert (
        await client.get(base + "/missing", headers=auth_headers("student1001"))
    ).status_code == 404
    other_id = await make_assignment(client, auth_headers)
    assert (
        await client.get(
            f"/assignments/{other_id}/submission/files/{item['id']}",
            headers=auth_headers("teacher"),
        )
    ).status_code == 404


@pytest.mark.parametrize(
    "filename",
    [
        "../../escape.txt",
        "..\\escape.txt",
        "/absolute.txt",
        "C:escape.txt",
        "answer.txt:stream",
    ],
)
async def test_filename_traversal_rejected(client, auth_headers, filename):
    assignment_id = await make_assignment(client, auth_headers)
    response = await upload(client, auth_headers, assignment_id, filename)
    assert response.status_code == 400, response.text
    assert files.list_submission_files(assignment_id, 1001) == []
    assert not files.upload_directory().exists()


@pytest.mark.parametrize("filename", ["C:\\temp\\escape.txt", "\\\\server\\share\\escape.txt"])
async def test_windows_absolute_filename_cannot_escape_storage(client, auth_headers, filename):
    assignment_id = await make_assignment(client, auth_headers)
    response = await upload(client, auth_headers, assignment_id, filename)
    # python-multipart strips old IE's full Windows filename to its basename.
    # Either rejection or safe basename storage is valid; no path is trusted.
    assert response.status_code in (400, 201), response.text
    if response.status_code == 201:
        item = response.json()
        assert item["filename"] == "escape.txt"
        stored = list(files.upload_directory().rglob("*.txt"))
        assert len(stored) == 1
        assert stored[0].resolve().is_relative_to(files.upload_directory())
        assert stored[0].parent == files.upload_directory() / assignment_id / "1001"


@pytest.mark.parametrize(
    "filename", ["evil.exe", "answer.html", "photo.jpeg", "noextension", "a.pdf.exe"]
)
async def test_extension_rejected(client, auth_headers, filename):
    assignment_id = await make_assignment(client, auth_headers)
    assert (await upload(client, auth_headers, assignment_id, filename)).status_code == 415
    assert files.list_submission_files(assignment_id, 1001) == []


@pytest.mark.parametrize("extension", sorted(files.ALLOWED_EXTENSIONS))
async def test_allowed_extensions(client, auth_headers, extension):
    assignment_id = await make_assignment(client, auth_headers)
    assert (
        await upload(client, auth_headers, assignment_id, f"answer.{extension}")
    ).status_code == 201


async def test_size_count_limits_and_cleanup(client, auth_headers):
    assignment_id = await make_assignment(client, auth_headers)
    response = await upload(
        client, auth_headers, assignment_id, content=b"x" * (files.MAX_FILE_BYTES + 1)
    )
    assert response.status_code == 413
    assert files.list_submission_files(assignment_id, 1001) == []
    assert not list(files.upload_directory().rglob("*.pdf"))
    response = await upload(
        client, auth_headers, assignment_id, content=b"x" * files.MAX_FILE_BYTES
    )
    assert response.status_code == 201
    assert response.json()["size"] == files.MAX_FILE_BYTES
    for i in range(4):
        assert (await upload(client, auth_headers, assignment_id, f"{i}.pdf")).status_code == 201
    assert (await upload(client, auth_headers, assignment_id)).status_code == 409
    assert len(files.list_submission_files(assignment_id, 1001)) == 5
    assert len(list(files.upload_directory().rglob("*.pdf"))) == 5
    # Removing a file frees a slot, and identical names do not overwrite content.
    first = files.list_submission_files(assignment_id, 1001)[0]
    assert (
        await client.delete(first["download_url"], headers=auth_headers("student1001"))
    ).status_code == 204
    assert (await upload(client, auth_headers, assignment_id)).status_code == 201


async def test_storage_configuration_and_tampered_path(client, auth_headers, monkeypatch, tmp_path):
    root = tmp_path / "custom_uploads"
    monkeypatch.setenv("EDUINSIGHT_SUBMISSION_UPLOAD_DIR", str(root))
    assignment_id = await make_assignment(client, auth_headers)
    item = (await upload(client, auth_headers, assignment_id)).json()
    assert len(list(root.rglob("*.pdf"))) == 1
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    for malicious in ("../secret.txt", str(secret), "..\\secret.txt", "C:secret.txt"):
        with files._db(write=True) as conn:
            conn.execute(
                "UPDATE submission_files SET storage_path = ? WHERE id = ?", (malicious, item["id"])
            )
        for method in ("GET", "DELETE"):
            response = await client.request(
                method, item["download_url"], headers=auth_headers("student1001")
            )
            assert response.status_code == 400
        assert secret.read_text(encoding="utf-8") == "secret"


async def test_symlink_escape_rejected(client, auth_headers, monkeypatch, tmp_path):
    assignment_id = await make_assignment(client, auth_headers)
    item = (await upload(client, auth_headers, assignment_id)).json()
    root = files.upload_directory()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        # Windows sandbox lacks symlink privilege. Emulate junction resolution;
        # the same resolved-path guard must still reject reads and deletes.
        original = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == link / "secret.txt":
                return original(outside / "secret.txt")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve)
    with files._db(write=True) as conn:
        conn.execute(
            "UPDATE submission_files SET storage_path = ? WHERE id = ?",
            ("escape/secret.txt", item["id"]),
        )
    for method in ("GET", "DELETE"):
        response = await client.request(
            method, item["download_url"], headers=auth_headers("student1001")
        )
        assert response.status_code == 400
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "secret"


async def test_submission_state_and_text_preservation(client, auth_headers):
    # As with text drafts, attachment edits are permitted after the deadline.
    assignment_id = await make_assignment(
        client,
        auth_headers,
        due_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        allow_late=True,
    )
    base = f"/assignments/{assignment_id}/submission"
    headers = auth_headers("student1001")
    assert (
        await client.put(base, headers=headers, json={"text": "preserve me", "state": "draft"})
    ).status_code == 200
    item = (await upload(client, auth_headers, assignment_id)).json()
    detail = (await client.get(f"/assignments/{assignment_id}", headers=headers)).json()
    assert detail["submission"]["text"] == "preserve me"
    assert detail["submission"]["state"] == "draft"
    assert (
        await client.put(base, headers=headers, json={"text": "preserve me", "state": "submitted"})
    ).status_code == 200
    assert (await upload(client, auth_headers, assignment_id)).status_code == 409
    assert (await client.delete(item["download_url"], headers=headers)).status_code == 409
    assert (await client.post(base + "/withdraw", headers=headers)).status_code == 200
    assert (await upload(client, auth_headers, assignment_id)).status_code == 201
    assert (await client.delete(item["download_url"], headers=headers)).status_code == 204
    remaining = files.list_submission_files(assignment_id, 1001)[0]
    assert (await client.put(base, headers=headers, json={"state": "submitted"})).status_code == 200
    response = await client.post(
        f"/assignments/{assignment_id}/submissions/1001/grade",
        headers=auth_headers("teacher"),
        json={"score": 85},
    )
    assert response.status_code == 200
    assert (await upload(client, auth_headers, assignment_id)).status_code == 409
    assert (await client.delete(remaining["download_url"], headers=headers)).status_code == 409
    assert (await client.get(remaining["download_url"], headers=headers)).status_code == 200


async def test_request_approve_immediately_enrolls(client, auth_headers):
    headers = auth_headers("outsider")
    assert [c["id"] for c in (await client.get("/courses", headers=headers)).json()] == ["general"]
    assert (await client.get("/courses/ds101/info", headers=headers)).status_code == 403
    request = await apply(client, auth_headers)
    assert request["student_id"] == 2001 and request["status"] == "pending"
    assert (await client.get("/enrollment/requests/mine", headers=headers)).json() == [request]
    assert (
        await client.get("/enrollment/requests/mine", headers=auth_headers("other_outsider"))
    ).json() == []
    assert (
        await client.get("/courses/ds101/enrollment/requests", headers=auth_headers("teacher"))
    ).json() == [request]
    approved = await client.post(
        f"/enrollment/requests/{request['id']}/approve", headers=auth_headers("teacher")
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert [course["id"] for course in (await client.get("/courses", headers=headers)).json()] == [
        "general", "ds101"
    ]
    assert (await client.get("/courses/ds101/info", headers=headers)).status_code == 200
    assignment_id = await make_assignment(client, auth_headers)
    assert (
        await upload(client, auth_headers, assignment_id, username="outsider")
    ).status_code == 201
    assert len(sessions.list_sessions(2001, "ds101")) == 1
    assert (
        await client.post(
            f"/enrollment/requests/{request['id']}/approve", headers=auth_headers("teacher")
        )
    ).status_code == 409
    assert len(sessions.list_sessions(2001, "ds101")) == 1
    notices = (await client.get("/notifications", headers=headers)).json()["notifications"]
    assert len(notices) == 1 and notices[0]["kind"] == "enrollment"
    assert notices[0]["user_id"] == auth.get_user_by_username("outsider")["id"]


async def test_dynamic_catalog_courses_and_archived_course(client, auth_headers):
    if not hasattr(courses, "catalog_entries"):
        pytest.skip("Dynamic catalog is provided by the parallel courses.py owner")
    courses.catalog_entries()
    with sessions._db() as conn:
        conn.execute(
            "INSERT INTO course_catalog (id, name, teacher_username) "
            "VALUES ('new101', 'New catalog course', 'teacher')"
        )
        conn.commit()
    request = await apply(client, auth_headers, course_id="new101")
    response = await client.post(
        f"/enrollment/requests/{request['id']}/approve",
        headers=auth_headers("teacher"),
    )
    assert response.status_code == 200, response.text
    assert (
        await client.get("/courses/new101/info", headers=auth_headers("outsider"))
    ).status_code == 200
    invitation = await invite(client, auth_headers, username="other_outsider", course_id="new101")
    response = await client.post(
        f"/invitations/{invitation['token']}/accept",
        headers=auth_headers("other_outsider"),
    )
    assert response.status_code == 200, response.text
    with sessions._db() as conn:
        conn.execute("UPDATE course_catalog SET archived = 1 WHERE id = 'new101'")
        conn.commit()
    response = await client.post(
        "/enrollment/requests",
        headers=auth_headers("student1001"),
        json={"course_id": "new101"},
    )
    assert response.status_code == 409


async def test_request_duplicates_cancellation_and_rejection(client, auth_headers):
    request = await apply(client, auth_headers)
    path = f"/enrollment/requests/{request['id']}"
    assert (
        await client.post(
            "/enrollment/requests", headers=auth_headers("outsider"), json={"course_id": "ds101"}
        )
    ).status_code == 409
    assert (
        await client.post(
            "/enrollment/requests", headers=auth_headers("student1001"), json={"course_id": "ds101"}
        )
    ).status_code == 409
    assert (
        await client.post(
            "/enrollment/requests", headers=auth_headers("outsider"), json={"course_id": "missing"}
        )
    ).status_code == 404
    assert (await client.delete(path, headers=auth_headers("other_outsider"))).status_code == 403
    assert (await client.delete(path, headers=auth_headers("outsider"))).status_code == 204
    assert (await client.delete(path, headers=auth_headers("outsider"))).status_code == 409
    assert (
        await client.post(path + "/approve", headers=auth_headers("teacher"))
    ).status_code == 409
    request = await apply(client, auth_headers)
    path = f"/enrollment/requests/{request['id']}"
    response = await client.post(path + "/reject", headers=auth_headers("teacher"))
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    assert sessions.list_sessions(2001, "ds101") == []
    assert (await client.post(path + "/reject", headers=auth_headers("teacher"))).status_code == 409
    assert (await client.delete(path, headers=auth_headers("outsider"))).status_code == 409


async def test_enrollment_staff_authorization(client, auth_headers):
    request = await apply(client, auth_headers)
    invitation = await invite(client, auth_headers)
    for username in ("student1001", "outsider", "teacher_huang"):
        for method, path, body in (
            ("GET", "/courses/ds101/enrollment/requests", None),
            ("POST", f"/enrollment/requests/{request['id']}/approve", None),
            ("POST", f"/enrollment/requests/{request['id']}/reject", None),
            ("POST", "/courses/ds101/invitations", {"email_or_username": "other_outsider"}),
            ("GET", "/courses/ds101/invitations", None),
        ):
            response = await client.request(method, path, json=body, headers=auth_headers(username))
            assert response.status_code == 403, response.text
    for username in ("teacher", "admin"):
        for method, path, body in (
            ("POST", "/enrollment/requests", {"course_id": "ds101"}),
            ("GET", "/enrollment/requests/mine", None),
            ("DELETE", f"/enrollment/requests/{request['id']}", None),
            ("POST", f"/invitations/{invitation['token']}/accept", None),
        ):
            assert (
                await client.request(method, path, json=body, headers=auth_headers(username))
            ).status_code == 403


async def test_invitation_recipient_acceptance_notifications(client, auth_headers):
    request = await apply(client, auth_headers)
    invitation = await invite(client, auth_headers)
    assert len(invitation["token"]) >= 40
    assert invitation["expires_at"] - invitation["created_at"] == enrollment.INVITATION_TTL
    assert (
        await client.get("/courses/ds101/invitations", headers=auth_headers("teacher"))
    ).json() == [invitation]
    path = f"/invitations/{invitation['token']}/accept"
    assert (await client.post(path, headers=auth_headers("other_outsider"))).status_code == 403
    response = await client.post(path, headers=auth_headers("outsider"))
    assert response.status_code == 200 and response.json()["status"] == "accepted"
    assert (
        await client.get("/courses/ds101/info", headers=auth_headers("outsider"))
    ).status_code == 200
    assert len(sessions.list_sessions(2001, "ds101")) == 1
    assert (await client.post(path, headers=auth_headers("outsider"))).status_code == 409
    assert len(sessions.list_sessions(2001, "ds101")) == 1
    assert (await client.get("/enrollment/requests/mine", headers=auth_headers("outsider"))).json()[
        0
    ]["status"] == "approved"
    assert (
        await client.post(
            f"/enrollment/requests/{request['id']}/approve", headers=auth_headers("teacher")
        )
    ).status_code == 409
    assert (
        len(
            (await client.get("/notifications", headers=auth_headers("outsider"))).json()[
                "notifications"
            ]
        )
        == 2
    )
    assert (
        len(
            (await client.get("/notifications", headers=auth_headers("admin"))).json()[
                "notifications"
            ]
        )
        == 1
    )


async def test_invitation_expiry_and_validation(client, auth_headers):
    invitation = await invite(client, auth_headers)
    for recipient, role, status in (
        ("outsider", "student", 409),
        ("teacher", "student", 422),
        ("student1001", "student", 409),
        ("other_outsider", "teacher", 422),
        ("  ", "student", 422),
    ):
        assert (
            await client.post(
                "/courses/ds101/invitations",
                headers=auth_headers("teacher"),
                json={"email_or_username": recipient, "role": role},
            )
        ).status_code == status
    with enrollment._db(write=True) as conn:
        conn.execute(
            "UPDATE course_invitations SET expires_at = ? WHERE id = ?",
            (time.time() - 1, invitation["id"]),
        )
    assert (
        await client.post(
            f"/invitations/{invitation['token']}/accept", headers=auth_headers("outsider")
        )
    ).status_code == 410
    assert sessions.list_sessions(2001, "ds101") == []
    assert (await client.get("/courses/ds101/invitations", headers=auth_headers("teacher"))).json()[
        0
    ]["status"] == "expired"
    new = await invite(client, auth_headers)
    assert new["token"] != invitation["token"]
    assert (
        await client.post("/invitations/missing/accept", headers=auth_headers("outsider"))
    ).status_code == 404


async def test_future_username_and_email_invitation(client, auth_headers):
    invitation = await invite(client, auth_headers, username="future_student")
    assert invitation["invited_user_id"] is None
    auth.create_user(
        auth.RegisterRequest(
            username="future_student",
            password="test123",
            display_name="Future",
            moodle_user_id=3001,
        )
    )
    assert (
        await client.post(
            f"/invitations/{invitation['token']}/accept", headers=auth_headers("future_student")
        )
    ).status_code == 200
    # The current auth schema has no email; support the auth owner's future email column.
    with auth._db() as conn:
        if "email" not in {row["name"] for row in conn.execute("PRAGMA table_info(users)")}:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
        conn.execute(
            "UPDATE users SET email = 'invitee@example.test' WHERE username = 'other_outsider'"
        )
        conn.commit()
    invitation = await invite(client, auth_headers, username="INVITEE@example.test")
    assert invitation["invited_user_id"] == auth.get_user_by_username("other_outsider")["id"]
    assert (
        await client.post(
            f"/invitations/{invitation['token']}/accept", headers=auth_headers("outsider")
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/invitations/{invitation['token']}/accept", headers=auth_headers("other_outsider")
        )
    ).status_code == 200


async def test_existing_profile_email_recipient_is_bound_to_user(client, auth_headers):
    response = await client.patch(
        "/profile/me",
        headers=auth_headers("outsider"),
        json={"email": "invitee@example.test"},
    )
    assert response.status_code == 200
    invitation = await invite(client, auth_headers, username="INVITEE@example.test")
    assert invitation["invited_user_id"] == auth.get_user_by_username("outsider")["id"]
    assert (await client.get("/notifications", headers=auth_headers("outsider"))).json()[
        "unread_count"
    ] == 1
    # A second user copying the email cannot redeem an invitation bound to its recipient.
    await client.patch(
        "/profile/me",
        headers=auth_headers("other_outsider"),
        json={"email": "invitee@example.test"},
    )
    path = f"/invitations/{invitation['token']}/accept"
    assert (await client.post(path, headers=auth_headers("other_outsider"))).status_code == 403
    assert (await client.post(path, headers=auth_headers("outsider"))).status_code == 200
    assert len(sessions.list_sessions(2001, "ds101")) == 1
    # Ambiguous emails are rejected when creating a fresh invitation.
    response = await client.post(
        "/courses/mk201/invitations",
        headers=auth_headers("admin"),
        json={"email_or_username": "invitee@example.test"},
    )
    assert response.status_code == 409


async def test_email_invitation_before_profile_exists(client, auth_headers):
    invitation = await invite(client, auth_headers, username="future@example.test")
    assert invitation["invited_user_id"] is None
    path = f"/invitations/{invitation['token']}/accept"
    assert (await client.post(path, headers=auth_headers("outsider"))).status_code == 403
    response = await client.patch(
        "/profile/me",
        headers=auth_headers("outsider"),
        json={"email": "future@example.test"},
    )
    assert response.status_code == 200
    assert (await client.post(path, headers=auth_headers("outsider"))).status_code == 200


async def test_lazy_tables_seed_idempotency_and_state_preservation(client, auth_headers):
    with auth._db() as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'enrollment_requests'"
            ).fetchone()
            is None
        )
    assert enrollment.seed_demo_enrollment() == {"requests_created": 2}
    assert enrollment.seed_demo_enrollment() == {"requests_created": 0}
    requests = (
        await client.get("/courses/py101/enrollment/requests", headers=auth_headers("admin"))
    ).json()
    assert len(requests) == 2 and all(row["status"] == "pending" for row in requests)
    request_id = requests[0]["id"]
    assert (
        await client.post(
            f"/enrollment/requests/{request_id}/reject", headers=auth_headers("admin")
        )
    ).status_code == 200
    assert enrollment.seed_demo_enrollment() == {"requests_created": 0}
    final = (
        await client.get("/courses/py101/enrollment/requests", headers=auth_headers("admin"))
    ).json()
    assert len(final) == 2 and final[0]["status"] == "rejected"
