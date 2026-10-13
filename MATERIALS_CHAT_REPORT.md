# Material metadata and chat history changes

Authorization remains as described in AUTH_ISOLATION_REPORT.md. Material writes require teacher/admin, mapped teachers retain their course scope, material reads require authentication, and session/message reads retain session ownership checks. No branches were switched, no commits or pushes were made, and no server was started.

## Routes and compatibility

`POST /courses/{course_id}/materials` saves the upload and its metadata, sends the response, then parses and indexes in a FastAPI background task running in the thread pool:

```json
{"status":"indexing","filename":"notes.md","course_id":"CS101","chunks_indexed":0,"total_pages":0}
```

The existing upload fields remain. Counts/pages are initially zero because parsing has not run yet. `?wait=true` waits for completion and preserves the previous synchronous response, including `status: "indexed"`, `chunks_indexed`, `total_pages`, and HTTP parse errors. Only three existing upload calls asserting synchronous results were changed to request `wait=true`. Starlette TestClient and HTTPX ASGITransport wait for background completion internally even though the HTTP body is sent earlier; the new tests explicitly observe ASGI response messages to verify early delivery.

`GET /courses/{course_id}/materials` keeps `documents` and adds typed metadata `items`. Pending and failed uploads remain listed so clients can show their state:

```json
{
  "course_id": "CS101",
  "documents": ["notes.md"],
  "items": [{
    "course_id": "CS101", "filename": "notes.md", "size_bytes": 45,
    "content_type": "text/markdown", "kind": "md",
    "uploaded_at": "2026-10-09T05:00:00+00:00", "uploaded_by": 1,
    "chunk_count": 1, "status": "done", "error": null
  }]
}
```

`uploaded_by` is the authenticated auth database user ID; `uploaded_at` is a UTC ISO 8601 timestamp. Metadata is stored in `course_material_metadata` in the configured auth SQLite database. Reads backfill previously indexed documents from RAG: actual chunk counts, inferred content type/kind, and null upload timestamp/uploader/size. They never invent upload dates or replace metadata for new uploads.

`GET /courses/{course_id}/materials/{filename}/status` returns:

```json
{"status":"done","chunk_count":1,"error":null}
```

The lifecycle is `indexing` → `done` or `failed`. A failure example is `{"status":"failed","chunk_count":0,"error":"Cannot parse document"}`. Unknown filenames/course combinations return 404. Concurrent upload or deletion of the same indexing filename returns 409. Deletion removes chunks, metadata and cached Markdown, including a failed upload with no chunks. Successful replacement removes old chunks before indexing the replacement. Temporary upload files are removed after success or failure. YouTube creation retains its synchronous response and also persists metadata with `kind: "youtube"`.

`POST /chat` accepts the existing fields plus optional parameters:

```json
{
  "moodle_user_id":1001, "course_id":"CS101", "message":"Explain binary search",
  "material_filenames":["notes.md"], "mention_user_ids":[1002,1003]
}
```

An omitted/null filename list searches all course materials; an empty list disables material retrieval. Supplied filenames must exist in the effective course, including legacy RAG documents; invalid/cross-course names return 400 before messages or a new session are written. A course is required for selection, or is taken from an explicitly supplied, authorized session when omitted. Filtering uses the ranked candidate pool before limiting to five citations, avoiding loss of a selected file outside the original first five results. Prompt context and returned citations use the same retrieval. Mention IDs are stored on the user message, with no notification or other behavior.

`GET /sessions/{session_id}/messages` keeps the existing envelope and message fields, and adds saved citations and mentions:

```json
{
  "messages": [
    {"role":"user","content":"Explain binary search","created_at":1791522000.0,
     "material_context":null,"mention_user_ids":[1002,1003]},
    {"role":"assistant","content":"Use binary search [1]","created_at":1791522000.1,
     "material_context":[{"id":"1","filename":"notes.md","heading":"Search",
       "anchor_id":"search","text":"Binary search uses sorted arrays."}],
     "mention_user_ids":null}
  ]
}
```

The response still includes its existing `session` object (omitted from the example). Old messages have null metadata; newly answered messages with no citations have `material_context: []`. Citations retain exactly the `/chat` shape and excerpt, surviving material deletion and Memory reload. A separate `chat_message_metadata` table in the auth database links them to the memory database path, session ID and Lite-Mem message ID; Lite-Mem's schema is unchanged. Deleting a session also deletes its message metadata.

## Files owned by this change

- `src/eduinsight/app.py`: localized request/response and materials/chat/session handler changes.
- `src/eduinsight/material_metadata.py`: new persistent material metadata table/operations.
- `src/eduinsight/rag.py`: chunk counts, filename filtering, consistent context formatting and thread coordination.
- `src/eduinsight/sessions.py`: persistent citations/mentions and session metadata cleanup.
- `tests/test_materials_meta.py`: new regression coverage.
- `tests/test_rag_api.py`: two upload URLs add `wait=true`.
- `tests/test_e2e_quiz_flow.py`: one upload URL adds `wait=true`.
- `MATERIALS_CHAT_REPORT.md`: this report.

`documents.py` did not require changes. Concurrent agents' files and router registrations were left alone.

## Verification

PowerShell command (a writable cache is necessary because the sandbox rejects the default uv cache):

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$env:TEMP/be-venv"
$env:UV_CACHE_DIR = "$env:TEMP/eduinsight-uv-cache"
uv run --python 3.12 --frozen pytest -q
```

The final full suite passed **902 tests in 140.43 seconds**, with **no failures ignored**, including the other agents' tests present in the working tree. The new material/chat test file passed all 18 tests, including status responsiveness while a concurrent list waits for indexing. Ruff E/F checks passed for both new Python files, and the edited existing files passed `git diff --check`. The earlier full run passed 901 tests before the extra status-responsiveness regression test was added.

## Operational limits

- FastAPI background jobs are in-process, without a durable queue or automatic restart recovery. Abrupt process termination can leave an upload marked `indexing`; recovery currently requires clearing/updating that metadata before retrying. Thread coordination is local to the RAG instance and does not provide distributed worker coordination.
- Failed replacement/indexing removes that filename's indexed chunks and cached Markdown to avoid exposing partial material; other documents are retained. Retry the upload to restore it.
- Filtered retrieval can examine the whole course's ranked chunk pool, which increases work for large courses. RAG writes are serialized within the instance, while material handlers and RAG waits run in worker threads so status polling remains responsive.
- Messages live in the memory database, while citations/material metadata live in the auth database. Back up both; their writes are not a single cross-database transaction.
