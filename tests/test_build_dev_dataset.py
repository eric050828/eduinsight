"""The dev dataset derives its facts from conversations and hides the demo passwords."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest
from litemem import Memory

from eduinsight.analytics import analyze_student
from eduinsight.assistant import LearningAssistant

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_dev_dataset.py"
USERS = """CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL, display_name TEXT NOT NULL, role TEXT NOT NULL,
    moodle_user_id INTEGER, active INTEGER NOT NULL DEFAULT 1,
    token_version INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL)"""
COURSES = """
CREATE TABLE course_catalog (id TEXT PRIMARY KEY, name TEXT, teacher_username TEXT,
    description TEXT, archived INTEGER);
CREATE TABLE course_enrollments (course_id TEXT, moodle_user_id INTEGER, role TEXT,
    source TEXT, created_at REAL);
CREATE TABLE course_open_enrollment (course_id TEXT, opened_by INTEGER, opened_at REAL);
"""


@pytest.fixture(scope="module")
def builder():
    spec = importlib.util.spec_from_file_location("build_dev_dataset", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def _say(memory, uid, session, role, text, at):
    message_id = memory._store.store_message(uid, text, session_id=session, role=role)
    conn = memory._store._get_conn()
    conn.execute("UPDATE messages SET created_at = ? WHERE id = ?", (at, message_id))
    conn.commit()
    return message_id


def _auth_db(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(USERS)
    conn.executescript(COURSES)
    return conn


def test_pairs_questions_with_answers_oldest_first(builder):
    memory = Memory(":memory:", embedder=None)
    _say(memory, "moodle:1", "later", "user", "第二題", 200.0)
    answer = _say(memory, "moodle:1", "later", "assistant", "第二答", 210.0)
    _say(memory, "moodle:1", "first", "user", "第一題", 100.0)
    _say(memory, "moodle:1", "first", "assistant", "第一答", 110.0)
    _say(memory, "moodle:1", "unanswered", "user", "沒有回答", 300.0)

    pairs = builder.conversation_pairs(memory._store)
    assert [pair[3] for pair in pairs] == ["第一題", "第二題"]
    assert pairs[1][:2] == ("moodle:1", "later") and pairs[1][2] == answer


def test_replay_derives_dated_facts_the_dashboard_can_read(builder):
    memory = Memory(":memory:", embedder=None)
    assistant = LearningAssistant(memory)
    _say(memory, "moodle:7", "s", "user", "我完全不懂鏈結串列", 1000.0)
    _say(memory, "moodle:7", "s", "assistant", "我們從節點開始。", 1010.0)

    assert memory.list("moodle:7") == []
    assert builder.replay_conversation_facts(memory, assistant) == 1

    assert "鏈結串列" in analyze_student(memory, 7, session_ids={"s"}).weak_topics
    assert "鏈結串列" not in analyze_student(memory, 7, session_ids={"other"}).weak_topics
    dates = memory._store._get_conn().execute(
        "SELECT created_at, updated_at FROM facts WHERE user_id = 'moodle:7'",
    ).fetchall()
    assert dates and all(tuple(row) == (1000.0, 1000.0) for row in dates)


def test_seeded_accounts_lose_demo_passwords_and_old_sessions(builder):
    conn = _auth_db()
    for name in ("admin", "student1001"):
        conn.execute("INSERT INTO users (username, password_hash, display_name, role, created_at) "
                     "VALUES (?, 'student123', ?, 'student', 0)", (name, name))

    passwords = builder.secure_seeded_accounts(conn, lambda plain: f"hash:{plain}")

    assert list(passwords) == ["student1001"]
    rows = {row["username"]: row for row in conn.execute("SELECT * FROM users")}
    assert rows["student1001"]["password_hash"] == f"hash:{passwords['student1001']}"
    assert len(passwords["student1001"]) == 10
    assert rows["admin"]["password_hash"] != "student123"
    assert rows["admin"]["active"] == 0
    assert {row["token_version"] for row in rows.values()} == {1}


def test_kept_accounts_keep_passwords_and_move_off_seeded_ids(builder, tmp_path):
    previous = tmp_path / "old.db"
    old = _auth_db(previous)
    old.execute("INSERT INTO users (username, password_hash, display_name, role, moodle_user_id, "
                "created_at) VALUES ('teach', 'h1', 'T', 'teacher', NULL, 0), "
                "('trial1', 'h2', 'S', 'student', 1001, 0), "
                "('other', 'h3', 'O', 'student', 1002, 0)")
    old.execute("INSERT INTO course_catalog VALUES ('trial101', '試用課程', 'teach', '', 0)")
    old.execute("INSERT INTO course_enrollments VALUES ('trial101', 1001, 'student', 'x', 0), "
                "('trial101', 1002, 'student', 'x', 0)")
    old.execute("INSERT INTO course_open_enrollment VALUES ('trial101', 1, 5)")
    old.commit()
    old.close()
    conn = _auth_db()
    conn.execute("INSERT INTO users (username, password_hash, display_name, role, moodle_user_id, "
                 "created_at) VALUES ('student1001', 'x', 'A', 'student', 1001, 0)")

    assert builder.carry_over_accounts(conn, previous, ["teach", "trial1"]) == ["trial101"]

    rows = {row["username"]: row for row in conn.execute("SELECT * FROM users")}
    assert set(rows) == {"student1001", "teach", "trial1"}
    assert rows["trial1"]["password_hash"] == "h2"
    assert rows["trial1"]["moodle_user_id"] == 6001
    assert rows["trial1"]["token_version"] == 1
    assert [tuple(row)[:2] for row in conn.execute("SELECT * FROM course_enrollments")] == [
        ("trial101", 6001),
    ]
    opened = conn.execute("SELECT opened_by FROM course_open_enrollment").fetchone()
    assert opened["opened_by"] == rows["teach"]["id"]
