"""Build the teammate-facing dev dataset in a new, empty directory.

The simulated semester (students, courses, conversations, coursework) comes from
the existing seeds. Everything derived from it is recomputed by the current
system instead of being copied from hand-written seeds:

- memory facts: each stored Q/A pair is replayed through the same steps as /chat,
  then backdated to when the conversation happened;
- material chunks: re-indexed by the current RAG pipeline;
- citations on past answers: searched again with the current index.

Analytics, risk and diagnostics read those live, so they need no separate step.

The public URL must never see demo passwords, so every seeded account gets a
random one, the demo admin is disabled, and old sessions stop working. Accounts
named by --keep come from --previous-data with their passwords unchanged.

Usage (run with the backend stopped, then point the deployment at the new data):

    uv run python scripts/build_dev_dataset.py --target DIR --serve-dir DIR \
        --previous-data DIR --accounts-file FILE
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sqlite3
import string
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASSWORD_ALPHABET = string.ascii_letters.translate(str.maketrans("", "", "IOlo")) + "23456789"
# Kept accounts move here: the seeds own moodle ids 1001-1005.
KEPT_STUDENT_ID_OFFSET = 5000
DEMO_ADMIN = "admin"
EMPTY_SESSION_TITLE = "Demo learning session"


def random_password(length: int = 10) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def conversation_pairs(store) -> list[tuple[str, str, int, str, str, float]]:
    """Return (uid, session, answer_id, question, answer, asked_at), oldest first."""
    conn = store._get_conn()  # noqa: SLF001
    rows = conn.execute(
        "SELECT id, user_id, session_id, role, content, created_at FROM messages "
        "WHERE user_id LIKE 'moodle:%' ORDER BY session_id, created_at, id"
    ).fetchall()
    pairs = []
    question = None
    for row in rows:
        if row["role"] == "user":
            question = row
        elif question is not None and question["session_id"] == row["session_id"]:
            pairs.append((row["user_id"], row["session_id"], row["id"], question["content"],
                          row["content"], question["created_at"]))
            question = None
    return sorted(pairs, key=lambda pair: pair[5])


def replay_conversation_facts(memory, assistant) -> int:
    """Derive facts as /chat does (it sends no topic), dated to each conversation."""
    store = memory._store  # noqa: SLF001
    pairs = conversation_pairs(store)
    for uid, session, _answer_id, question, answer, asked_at in pairs:
        started = time.time()
        student_id = int(uid.removeprefix("moodle:"))
        if not assistant.extract_from_conversation(
            student_id, question, answer, session_id=session,
        ):
            assistant.record_interaction(student_id, question, answer, session_id=session)
        conn = store._get_conn()  # noqa: SLF001
        conn.execute(
            "UPDATE facts SET created_at = ?, updated_at = ? WHERE user_id = ? AND created_at >= ?",
            (asked_at, asked_at, uid, started),
        )
        conn.commit()
    return len(pairs)


def replay_citations(memory, rag, course_of: dict[str, str], citation_type, save) -> int:
    """Attach the citations the current index gives for each past question."""
    saved = 0
    for _uid, session, answer_id, question, _answer, _asked in conversation_pairs(memory._store):  # noqa: SLF001
        course_id = course_of.get(session)
        if not course_id:
            continue
        citations = [
            citation_type(
                id=str(index), filename=hit.source,
                heading=hit.heading or (f"p.{hit.page}" if hit.page else ""),
                anchor_id=hit.anchor_id, text=hit.text[:300],
            ).model_dump()
            for index, hit in enumerate(rag.search(course_id, question, top_k=5), 1)
        ]
        save(session, answer_id, material_context=citations)
        saved += 1
    return saved


def secure_seeded_accounts(conn: sqlite3.Connection, hash_password) -> dict[str, str]:
    """Replace every seeded password, disable the demo admin, end older sessions."""
    passwords = {}
    for row in conn.execute("SELECT id, username FROM users ORDER BY id").fetchall():
        password = random_password()
        conn.execute("UPDATE users SET password_hash = ?, token_version = token_version + 1 "
                     "WHERE id = ?", (hash_password(password), row["id"]))
        if row["username"] == DEMO_ADMIN:
            conn.execute("UPDATE users SET active = 0 WHERE id = ?", (row["id"],))
        else:
            passwords[row["username"]] = password
    return passwords


def carry_over_accounts(conn: sqlite3.Connection, previous: Path, keep: list[str]) -> list[str]:
    """Copy accounts with their password hashes, plus their course and enrollment."""
    old = sqlite3.connect(f"file:{previous}?mode=ro", uri=True)
    old.row_factory = sqlite3.Row
    try:
        marks = ",".join("?" * len(keep))
        ids = {}
        moved = {}
        for row in old.execute(f"SELECT * FROM users WHERE username IN ({marks})", keep):  # noqa: S608
            student = row["moodle_user_id"]
            new_student = None if student is None else student + KEPT_STUDENT_ID_OFFSET
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, display_name, role, moodle_user_id, "
                "active, token_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (row["username"], row["password_hash"], row["display_name"], row["role"],
                 new_student, row["active"], row["token_version"] + 1, row["created_at"]),
            )
            ids[row["id"]] = cursor.lastrowid
            if student is not None:
                moved[student] = new_student
        kept_courses = old.execute(
            f"SELECT * FROM course_catalog WHERE teacher_username IN ({marks})", keep,  # noqa: S608
        ).fetchall()
        for course in kept_courses:
            conn.execute(
                "INSERT INTO course_catalog (id, name, teacher_username, description, archived) "
                "VALUES (?, ?, ?, ?, ?)", tuple(course),
            )
            for row in old.execute("SELECT * FROM course_enrollments WHERE course_id = ?",
                                   (course["id"],)):
                if row["moodle_user_id"] in moved:
                    conn.execute(
                        "INSERT INTO course_enrollments "
                        "(course_id, moodle_user_id, role, source, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (row["course_id"], moved[row["moodle_user_id"]], row["role"],
                         row["source"], row["created_at"]),
                    )
            for row in old.execute("SELECT * FROM course_open_enrollment WHERE course_id = ?",
                                   (course["id"],)):
                conn.execute(
                    "INSERT INTO course_open_enrollment (course_id, opened_by, opened_at) "
                    "VALUES (?, ?, ?)",
                    (row["course_id"], ids.get(row["opened_by"]), row["opened_at"]),
                )
        return sorted(row["id"] for row in kept_courses)
    finally:
        old.close()


def _configure_environment(target: Path) -> None:
    """Point settings at the new directory; must run before importing eduinsight."""
    os.environ.update({
        "EDUINSIGHT_ENV": "development",
        "EDUINSIGHT_DEMO_MODE": "true",
        "EDUINSIGHT_LOGIN_THROTTLE_ENABLED": "false",
        "EDUINSIGHT_MEMORY_EMBEDDER": "stub",  # same as scripts/start-local-deploy.ps1
        "EDUINSIGHT_MEMORY_DB_PATH": str(target / "eduinsight.db"),
        "EDUINSIGHT_AUTH_DB_PATH": str(target / "eduinsight_auth.db"),
    })
    sys.path[:0] = [str(REPO / "scripts")]
    os.chdir(target)  # materials cache and uploads are relative to the working directory


def _load_semester(client, app_module) -> dict[str, int]:
    import reindex_materials_md
    import seed_diverse_materials
    import seed_semester_conversations

    from eduinsight import sessions
    from eduinsight.demo_data import DEMO_STUDENTS

    login = client.post("/auth/login", json={"username": DEMO_ADMIN, "password": "admin123"})
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.post("/demo/reset", headers=headers).raise_for_status()

    memory = app_module._memory  # noqa: SLF001
    # Hand-written facts are exactly what the replay below replaces.
    for uid in DEMO_STUDENTS:
        memory.forget(uid)
    seed_semester_conversations.FACT_SEEDS = []
    seed_semester_conversations.main()
    with sessions._db() as conn:  # noqa: SLF001
        conn.execute("DELETE FROM chat_sessions WHERE title = ?", (EMPTY_SESSION_TITLE,))
        course_of = dict(conn.execute("SELECT session_id, course_id FROM chat_sessions").fetchall())
        conn.commit()

    shutil.copytree(REPO / "_sim_materials", "_sim_materials")
    reindex_materials_md.main()
    seed_diverse_materials.main()
    shutil.rmtree("_sim_materials")

    assistant = app_module._assistant  # noqa: SLF001
    return {
        "conversation_pairs": replay_conversation_facts(memory, assistant),
        "citations": replay_citations(memory, app_module._rag, course_of,  # noqa: SLF001
                                      app_module.MaterialCitation, sessions.save_message_metadata),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", type=Path, required=True, help="new, empty data directory")
    parser.add_argument("--serve-dir", type=Path, required=True,
                        help="directory the deployment will read this data from")
    parser.add_argument("--previous-data", type=Path, required=True)
    parser.add_argument("--accounts-file", type=Path, required=True,
                        help="where to write the new passwords; keep outside the repository")
    parser.add_argument("--keep", nargs="*", default=[], help="usernames to carry over")
    args = parser.parse_args()

    target = args.target.resolve()
    if target.exists() and any(target.iterdir()):
        parser.error(f"{target} is not empty")
    if not (REPO / "_sim_materials").is_dir():
        parser.error("_sim_materials is missing; run scripts/gen_semester_materials.py first")
    target.mkdir(parents=True, exist_ok=True)
    _configure_environment(target)

    from fastapi.testclient import TestClient

    from eduinsight import app as app_module
    from eduinsight import auth, sessions

    with TestClient(app_module.app) as client:
        summary = _load_semester(client, app_module)

    with sessions._db() as conn:  # noqa: SLF001
        # Citations are keyed by the memory DB path the server will use.
        conn.execute("UPDATE chat_message_metadata SET memory_db_path = ?",
                     (str(args.serve_dir.resolve() / "eduinsight.db"),))
        conn.row_factory = sqlite3.Row
        passwords = secure_seeded_accounts(conn, auth.hash_password)
        courses = carry_over_accounts(conn, args.previous_data.resolve() / "eduinsight_auth.db",
                                      args.keep)
        conn.commit()

    args.accounts_file.write_text(
        "".join(f"{name}  {password}\n" for name, password in passwords.items()), encoding="utf-8",
    )
    print(json.dumps({**summary, "accounts": len(passwords), "kept_courses": courses},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
