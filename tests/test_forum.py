"""Forum tests use real auth JWTs with the shared isolated-database fixtures."""

import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from litemem import Memory

from eduinsight import auth, forum, notifications, sessions
from eduinsight.documents import DocumentChunk, ParsedDocument
from eduinsight.rag import CourseRAG


@pytest.fixture
def client(auth_headers):
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(forum.router)
    app.include_router(notifications.router)
    for student_id in (1001, 1002):
        sessions.create_session(student_id, "ds101")
    sessions.create_session(1003, "mk201")
    with TestClient(app) as test_client:
        yield test_client


def thread(client, auth_headers, username="student1001", course_id="ds101"):
    response = client.post(f"/courses/{course_id}/forum/threads",
                           headers=auth_headers(username),
                           json={"title": "Study question", "body": "How does sorting work?"})
    assert response.status_code == 201, response.text
    return response.json()


ROUTES = [
    ("GET", "/courses/ds101/forum/threads", None),
    ("POST", "/courses/ds101/forum/threads", {"title": "Q", "body": "B"}),
    ("GET", "/forum/threads/missing", None),
    ("POST", "/forum/threads/missing/posts", {"body": "B"}),
    ("PATCH", "/forum/threads/missing", {"title": "Q"}),
    ("DELETE", "/forum/threads/missing", None),
    ("PATCH", "/forum/posts/missing", {"body": "B"}),
    ("DELETE", "/forum/posts/missing", None),
    ("POST", "/forum/threads/missing/pin", None),
    ("GET", "/courses/ds101/forum/subscription", None),
    ("PUT", "/courses/ds101/forum/subscription", None),
    ("DELETE", "/courses/ds101/forum/subscription", None),
    ("PUT", "/forum/threads/missing/subscription", None),
    ("DELETE", "/forum/threads/missing/subscription", None),
    ("GET", "/forum/stats/me", None),
    ("GET", "/courses/ds101/materials/download-all", None),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_all_routes_require_auth(client, method, path, body):
    assert client.request(method, path, json=body).status_code == 401
    assert client.request(method, path, json=body,
                          headers={"Authorization": "Bearer bad"}).status_code == 401


@pytest.mark.parametrize("username", ["student1003", "teacher_huang", "unmapped_teacher"])
def test_course_scoping(client, auth_headers, username):
    if username == "unmapped_teacher":
        auth.create_user(auth.RegisterRequest(username=username, password="testpass",
                                             display_name="Teacher", role="teacher"))
    headers = auth_headers(username)
    own = thread(client, auth_headers)
    post = client.post(f"/forum/threads/{own['id']}/posts", json={"body": "Reply"},
                       headers=auth_headers("student1002")).json()
    for method, path, body in ROUTES:
        if path == "/forum/stats/me":
            continue
        resource = post["id"] if "/forum/posts/" in path else own["id"]
        response = client.request(method, path.replace("missing", resource),
                                  headers=headers, json=body)
        assert response.status_code == 403, (method, path, response.text)
    assert client.get("/forum/stats/me", headers=headers).json() == {"threads": 0, "posts": 0}


def test_enrollment_uses_moodle_id_and_admin_access(client, auth_headers):
    student = auth.get_user_by_username("student1001")
    assert student["id"] != student["moodle_user_id"]
    assert client.get("/courses/ds101/forum/threads", headers=auth_headers("student1001")).status_code == 200
    assert client.get("/courses/mk201/forum/threads", headers=auth_headers("student1001")).status_code == 403
    assert client.get("/courses/mk201/forum/threads", headers=auth_headers()).status_code == 200
    assert client.get("/courses/unknown/forum/threads", headers=auth_headers()).status_code == 404
    with sessions._db() as conn:
        conn.execute("DELETE FROM chat_sessions WHERE moodle_user_id=1001")
        conn.commit()
    assert client.get("/courses/ds101/forum/threads", headers=auth_headers("student1001")).status_code == 403


def notices(client, headers):
    return client.get("/notifications", headers=headers).json()["notifications"]


def test_subscriptions_and_notifications(client, auth_headers):
    owner, other = auth_headers("student1001"), auth_headers("student1002")
    course_url = "/courses/ds101/forum/subscription"
    assert client.get(course_url, headers=other).json()["subscribed"] is False
    for _ in range(2):
        assert client.put(course_url, headers=other).json()["subscribed"] is True
    client.put(course_url, headers=owner)
    item = thread(client, auth_headers)
    assert item["subscribed"] is True
    assert len(notices(client, other)) == 1
    assert notices(client, other)[0]["kind"] == "forum_thread"
    assert notices(client, owner) == []
    tid = item["id"]
    subscription = f"/forum/threads/{tid}/subscription"
    assert client.get(f"/forum/threads/{tid}", headers=other).json()["thread"]["subscribed"] is False
    for _ in range(2):
        assert client.put(subscription, headers=other).json()["subscribed"] is True
    # A subscriber replying receives no self-notification; the author does.
    client.post(f"/forum/threads/{tid}/posts", headers=other, json={"body": "Answer"})
    assert len(notices(client, other)) == 1
    assert len(notices(client, owner)) == 1
    assert notices(client, owner)[0]["link"] == f"/forum/threads/{tid}"
    client.post(f"/forum/threads/{tid}/posts", headers=owner, json={"body": "Thanks"})
    assert len(notices(client, other)) == 2
    assert notices(client, other)[0]["kind"] == "forum_post"
    assert len(notices(client, owner)) == 1
    assert client.delete(subscription, headers=other).json()["subscribed"] is False
    client.post(f"/forum/threads/{tid}/posts", headers=owner, json={"body": "More"})
    assert len(notices(client, other)) == 2
    assert client.delete(course_url, headers=other).json()["subscribed"] is False
    thread(client, auth_headers)
    assert len(notices(client, other)) == 2


def test_stale_subscriptions_do_not_leak(client, auth_headers):
    other = auth_headers("student1002")
    client.put("/courses/ds101/forum/subscription", headers=other)
    item = thread(client, auth_headers)
    client.put(f"/forum/threads/{item['id']}/subscription", headers=other)
    with sessions._db() as conn:
        conn.execute("DELETE FROM chat_sessions WHERE moodle_user_id=1002")
        conn.commit()
    thread(client, auth_headers)
    client.post(f"/forum/threads/{item['id']}/posts", headers=auth_headers("student1001"),
                json={"body": "Private course update"})
    assert len(notices(client, other)) == 1


def test_views_stats_edit_delete_and_pin(client, auth_headers):
    owner, other, teacher, admin = (auth_headers(name) for name in
                                    ("student1001", "student1002", "teacher", "admin"))
    item = thread(client, auth_headers)
    tid = item["id"]
    url = f"/forum/threads/{tid}"
    reply = client.post(url + "/posts", headers=other, json={"body": "Reply"}).json()
    post_url = f"/forum/posts/{reply['id']}"
    data = client.get(url, headers=owner).json()
    assert data["posts"][0]["author_role"] == "student"
    assert data["thread"]["author_name"] == auth.get_user_by_username("student1001")["display_name"]
    assert data["thread"]["post_count"] == 1
    assert data["thread"]["last_activity"] >= reply["created_at"]
    assert client.get("/forum/stats/me", headers=owner).json() == {"threads": 1, "posts": 0}
    assert client.get("/forum/stats/me", headers=other).json() == {"threads": 0, "posts": 1}
    for headers in (other, teacher, admin):
        assert client.patch(url, headers=headers, json={"title": "Changed"}).status_code == 403
    assert client.patch(url, headers=owner, json={"title": "Updated", "body": "New body"}).json()["title"] == "Updated"
    for headers in (owner, teacher, admin):
        assert client.patch(post_url, headers=headers, json={"body": "Changed"}).status_code == 403
    assert client.patch(post_url, headers=other, json={"body": "Updated reply"}).json()["body"] == "Updated reply"
    assert client.delete(url, headers=other).status_code == 403
    assert client.delete(post_url, headers=owner).status_code == 403
    assert client.post(url + "/pin", headers=owner).status_code == 403
    assert client.post(url + "/pin", headers=teacher).json()["pinned"] is True
    thread(client, auth_headers)
    assert client.get("/courses/ds101/forum/threads", headers=owner).json()[0]["id"] == tid
    assert client.post(url + "/pin", headers=admin, json={"pinned": False}).json()["pinned"] is False
    assert client.delete(post_url, headers=teacher).status_code == 204
    assert client.get(url, headers=owner).json()["thread"]["post_count"] == 0
    reply = client.post(url + "/posts", headers=other, json={"body": "Again"}).json()
    assert client.delete(url, headers=admin).status_code == 204
    assert client.get(url, headers=owner).status_code == 404
    assert client.delete(f"/forum/posts/{reply['id']}", headers=other).status_code == 404
    with forum._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM forum_thread_subscriptions WHERE thread_id=?", (tid,)).fetchone()[0] == 0


def test_own_deletes_and_teacher_thread_delete(client, auth_headers):
    item = thread(client, auth_headers)
    url = f"/forum/threads/{item['id']}"
    reply = client.post(url + "/posts", headers=auth_headers("student1002"), json={"body": "R"}).json()
    assert client.delete(f"/forum/posts/{reply['id']}", headers=auth_headers("student1002")).status_code == 204
    assert client.delete(url, headers=auth_headers("student1001")).status_code == 204
    item = thread(client, auth_headers)
    assert client.delete(f"/forum/threads/{item['id']}", headers=auth_headers("teacher")).status_code == 204


@pytest.mark.parametrize("payload", [{"title": " ", "body": "B"}, {"title": "T", "body": " "},
                                     {"title": "T", "body": "B", "author_id": 1}])
def test_invalid_input(client, auth_headers, payload):
    assert client.post("/courses/ds101/forum/threads", headers=auth_headers(), json=payload).status_code == 422
    item = thread(client, auth_headers)
    for body in ({"title": None}, {"body": " "}, {"pinned": True}):
        assert client.patch(f"/forum/threads/{item['id']}", headers=auth_headers("student1001"), json=body).status_code == 422


def test_zip_cached_markdown_and_indexed_fallback(client, auth_headers, monkeypatch, tmp_path):
    from eduinsight import app as app_module

    monkeypatch.chdir(tmp_path)
    mem = Memory(":memory:", embedder=None)
    rag = CourseRAG(mem)
    monkeypatch.setattr(app_module, "_rag", rag)
    try:
        for filename, text in (("notes.pdf", "Indexed PDF text"), ("slides.pptx", "Indexed slide text")):
            rag.index_document("ds101", ParsedDocument(filename=filename, total_pages=1,
                chunks=[DocumentChunk(text=text, source=filename, page=1, chunk_index=0)]))
        rag.index_document("mk201", ParsedDocument(filename="secret.pdf", total_pages=1,
            chunks=[DocumentChunk(text="Other course secret", source="secret.pdf", page=1, chunk_index=0)]))
        path = app_module._material_markdown_path("ds101", "notes.pdf")
        path.parent.mkdir(parents=True)
        path.write_text("# Cached notes\nFull converted PDF", encoding="utf-8")
        # An unindexed leftover cache must not be exported.
        (path.parent / "leftover.pdf.md").write_text("Do not export", encoding="utf-8")
        response = client.get("/courses/ds101/materials/download-all", headers=auth_headers("student1001"))
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert "ds101-materials.zip" in response.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert set(archive.namelist()) == {"001-notes.pdf.md", "002-slides.pptx.md", "README.txt"}
            assert archive.read("001-notes.pdf.md").decode() == "# Cached notes\nFull converted PDF"
            assert "Indexed slide text" in archive.read("002-slides.pptx.md").decode()
            readme = archive.read("README.txt").decode()
            assert "Original uploads are not retained" in readme
            assert "notes.pdf" in readme and "slides.pptx" in readme
        assert client.get("/courses/ds101/materials/download-all", headers=auth_headers("student1003")).status_code == 403
        assert client.get("/courses/ds101/materials/download-all", headers=auth_headers("teacher_huang")).status_code == 403
        assert client.get("/courses/eng201/materials/download-all", headers=auth_headers()).status_code == 404
        monkeypatch.setattr(app_module, "_rag", None)
        assert client.get("/courses/ds101/materials/download-all", headers=auth_headers()).status_code == 404
    finally:
        mem.close()


def test_seed_idempotent_preserves_edits_and_subscription_choices(client, auth_headers):
    count = len(set(auth.TEACHER_COURSE_MAP.values())) * 2
    assert forum.seed_demo_forum() == {"threads_created": count, "posts_created": count}
    items = client.get("/courses/ds101/forum/threads", headers=auth_headers("teacher")).json()
    assert len(items) == 2
    assert all(item["post_count"] == 1 and item["subscribed"] for item in items)
    tid = items[0]["id"]
    teacher = auth_headers("teacher")
    client.patch(f"/forum/threads/{tid}", headers=teacher, json={"title": "Keep this edit"})
    client.delete(f"/forum/threads/{tid}/subscription", headers=teacher)
    client.post(f"/forum/threads/{tid}/pin", headers=teacher, json={"pinned": False})
    assert forum.seed_demo_forum() == {"threads_created": 0, "posts_created": 0}
    result = client.get(f"/forum/threads/{tid}", headers=teacher).json()
    assert result["thread"]["title"] == "Keep this edit"
    assert result["thread"]["subscribed"] is False
    assert result["thread"]["pinned"] is False
    assert len(result["posts"]) == 1
    assert notices(client, teacher) == []
    with forum._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM forum_threads").fetchone()[0] == count
