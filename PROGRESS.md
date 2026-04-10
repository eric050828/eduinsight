# EduInsight Progress

## Vision
AI 學習助教平台，接 Moodle LMS，以 Lite-Mem 為記憶層。
Lite-Mem 是套件依賴，不可修改其原始碼。教育只是 Lite-Mem 的一種應用情境。

## Phase 1: Foundation (Current)
- [x] Project setup with Lite-Mem as dependency
- [x] Moodle REST API client (Web Services)
  - Authentication (token-based)
  - Get courses, assignments, grades, forum posts
  - Get user info
- [x] LearningAssistant memory layer (record questions, struggles, preferences)
- [x] FastAPI app skeleton with /chat, /courses, /grades endpoints
- [x] Basic tests (assistant + moodle client)
- [ ] Integration test with real Moodle instance (needs NTUST token)

## Phase 2: Memory Integration
- [x] Connect Lite-Mem to track student interactions
  - Each student = a Lite-Mem user_id (moodle:{id} namespace)
  - Store: questions asked, topics struggled with, learning preferences
- [x] Conversation API (student asks question → AI answers with memory context)
  - LLM provider: async client via OpenAI-compatible API (Gemini/OpenAI/Groq)
  - Memory-augmented prompt: retrieves relevant memories → builds context → LLM generates answer
  - Records Q&A interaction back to memory for future context
- [x] Tests for memory integration (15 new tests, 29 total)
- [x] add_conversation integration (use Lite-Mem's fact extraction on chat history)
  - extract_from_conversation() wraps Lite-Mem add_conversation for automatic fact extraction
  - answer() now uses add_conversation (stub extractor by default) instead of manual Q&A storage
  - Falls back to record_interaction() when no facts are extracted (e.g. pure academic Q&A)
  - AssistantResponse.extracted_facts field exposes what was extracted
  - Configurable extractor: stub (default, offline), auto, gemini, groq, ollama
  - 8 new tests (37 total)
- [x] Semantic search with embeddings (enable Lite-Mem embedder="auto")
  - config.py: added `memory_embedder` setting (default "auto")
  - app.py: passes embedder to Memory() constructor for hybrid search (60% cosine + 40% FTS5)
  - Auto-detects: GeminiEmbedder when GEMINI_API_KEY set, else StubEmbedder (offline)
  - 7 new tests (test_embeddings.py), 43 total

## Phase 3: Frontend (Demo-Ready UI)
- [x] Student chat UI (HTML/CSS/JS served via FastAPI StaticFiles)
  - Modern chat interface at `/` with message bubbles
  - Connects to existing `/chat` API endpoint
  - Collapsible memory context display per response
  - Student ID + topic controls in header
  - Welcome screen with example questions
  - Auto-resize textarea, Enter to send, typing indicator
- [x] Teacher dashboard UI (learning analytics view)
  - Dashboard at `/teacher` with stats overview (students, total memories, avg per student)
  - Student table sorted by recent activity, shows fact count + categories
  - Click student → modal shows all stored memories
  - API: `GET /teacher/students` (list with stats), `GET /teacher/students/{id}/memories`
  - Uses Lite-Mem `detailed_stats()` + `list()` for data — no custom DB queries
  - 5 new tests (48 total)
- [x] Demo scenario walkthrough
  - Demo data module (demo_data.py): 4 students with distinct learning profiles
  - Seed script (scripts/seed_demo.py): CLI tool to populate DB with demo data
  - POST /demo/reset endpoint: seeds demo data on demand from the UI
  - Demo walkthrough page at /demo: 5-step guided tour with clickable actions
  - Navigation links added across all pages (Chat, Teacher, Demo)
  - URL hash params for pre-filling chat from demo links
  - 2 new tests (50 total)

## Phase 4: Learning Analytics (Backend)
- [x] Extract learning patterns from Lite-Mem memory (analytics.py)
  - Weak topics per student (struggles parsed from memory facts)
  - Common class-wide struggles (aggregated across all students)
  - Question topic distribution per student and class-wide
  - Learning preferences extraction
- [x] Analytics API endpoints
  - GET /analytics/student/{id} — per-student struggles, weak topics, preferences
  - GET /analytics/class — class-wide common struggles, topic distribution
- [x] Tests (12 new tests, 62 total)
- [x] Learning trajectory over time (timestamp-based trend analysis)
  - learning_trajectory() uses Memory.export() for timestamped facts
  - Groups facts by week, tracks new struggles/topics per week
  - Cumulative counters show growth over time
  - GET /analytics/student/{id}/trajectory endpoint
  - 9 new tests (71 total)

## Phase 5: Moodle Plugin / Integration
- [x] LTI 1.3 tool provider (FastAPI adapter for PyLTI1p3)
  - FastAPI adapter: Request, CookieService, SessionService, Redirect, OIDCLogin, MessageLaunch
  - OIDC login endpoint: POST /lti/login (handles Moodle OIDC initiation)
  - Resource link launch: POST /lti/launch (validates JWT, extracts user/course, redirects to chat)
  - JWKS endpoint: GET /lti/jwks (RSA key pair auto-generated, serves public key)
  - Config info: GET /lti/config (setup instructions for Moodle admins)
  - In-memory session/launch cache (single-process demo)
  - 11 new tests (82 total)
- [x] Configure & test with Docker Moodle instance
  - Docker Compose: Moodle 4 + MariaDB (docker-compose.moodle.yml)
  - Registered EduInsight as LTI 1.3 External Tool (client_id: HfGbuDZTj36GZgR)
  - Configured: Tool URL, Login URL, JWKS URL, Redirect URI
  - Privacy: shares launcher name + email
  - Created test course "AI 程式設計導論" (CS101-AI) with External Tool activity
  - Fixed 2 bugs: missing CookieService._get_key(), incorrect redirect() return handling
  - End-to-end LTI launch verified: OIDC login → JWT validation → chat UI embedded in iframe
  - LTI claims correctly extracted: user_id=2, name=Admin User, course=CS101-AI
- [x] Embed chat assistant in Moodle course page
  - Chat UI loads inside Moodle iframe via LTI 1.3 resource link launch
  - Full sidebar navigation, student selector, and chat interface visible
- [x] Real-time analytics in Moodle teacher view
  - LTI role detection: parses `roles` claim from JWT (Instructor, TA, Admin, etc.)
  - Role-based redirect: instructors → /teacher dashboard, students → / chat
  - Teacher dashboard fetches real data from analytics API on page load
  - Live stats: student count, total memories, per-student averages from /teacher/students
  - Live difficulty ranking: common struggles from /analytics/class
  - Live student table: per-student weak topics + preferences from /analytics/student/{id}
  - LTI context displayed: course name, instructor name, "LTI 連線中" badge
  - 8 new role detection tests (90 total)

## Phase 6: Demo & Polish
- [x] Demo scenario: student uses assistant for a semester
  - semester_demo.py: 18-week learning journey for student 2001 (林小明)
  - Story arc: Python basics → data structures → OOP → algorithms → practical → final project
  - POST /demo/semester: seeds time-spread data with backdated timestamps
  - GET /semester: timeline UI showing week-by-week progression
  - Trajectory chart: visual bar chart of memory accumulation and struggles per week
  - Stats overview: total weeks, cumulative memories, struggle count, topic coverage
  - Direct links to chat as student 2001, teacher dashboard, and analytics API
  - 11 new tests (101 total)
- [x] Export/import memory (Lite-Mem portable format)
  - GET /export/student/{id} — export single student's memory as MemoryBundle JSON
  - GET /export/all — export all moodle students' memories (list of bundles)
  - POST /import — upload MemoryBundle JSON file to import memories (merge mode)
  - Roundtrip tested: export → clear → import → verify identical
  - 9 new tests (110 total)
- [x] InnoServe competition materials (initial drafts)
  - 系統概述文件草稿 (Markdown, 6 sections matching EDUAI criteria)
  - 3分鐘影片腳本 (6 segments with timing)
  - 競賽準備 checklist (based on 30th competition guidelines)
  - Competition materials in `competition/` directory

## Next Steps for Competition
- [ ] 組隊（找齊隊員+指導老師）
- [ ] 系統概述文件轉 Word 檔（套大會表頭）
- [ ] 錄製 Demo 影片
- [ ] 等第31屆競賽須知公告後調整內容

## Hotfix: Demo Memory Dedup (2026-04-10)
- [x] Fix demo_data.py — unique fact prefixes to prevent Lite-Mem prefix-based dedup
  - Old: 45 seeded → 16 survived (35%); New: 45 seeded → 45 survived (100%)
  - Each fact now has unique text before first colon
- [x] Add category labels to demo data (struggling/preference/general)
  - Teacher dashboard now shows category breakdown per student
- [x] Update /demo/reset to verify actual stored count (not just seeded count)
- [x] Update analytics regex to handle new "Struggling with TOPIC:" format
- [x] Add ClaudeCLIClient — LLM via `claude -p` (no API key needed)
- [x] Redesign index.html as dark theme SPA with sidebar nav
  - Embeds teacher dashboard + analytics views (no separate page needed)
- [x] 71 tests passing

## Hotfix: Supervisor Bug Fixes (2026-04-10)
- [x] Fix _memory.delete() → _memory.forget() in /demo/reset and /demo/semester
  - `delete()` method didn't exist; try/except was silently swallowing errors
  - Now uses `forget(uid)` which properly clears all user data
- [x] Markdown rendering in chat via marked.js + DOMPurify
  - AI responses now render headings, bold, code blocks, tables, blockquotes
  - CSS styling for dark theme code blocks and tables
- [x] Student memory modal in SPA teacher dashboard
  - Click any student row → modal shows all stored memories with category tags
  - Categories auto-detected from memory text (struggling/preference/general)
- [x] Dynamic LLM backend label from /health endpoint
  - No longer hardcoded "Claude Haiku"
  - /health now returns `llm_provider` field
- [x] teacher.html mockup banner
  - Yellow banner clearly labels mock data sections (scatter, heatmap, alerts)
  - Distinguishes real API data (stats) from vision mockups

## UI Redesign: Landing Page + Student Dashboard (2026-04-10)
- [x] Landing page at `/` with portal cards (student/teacher entry points)
  - Animated background blobs, radar chart preview (student), scatter chart preview (teacher)
  - Demo scenario banner (114學年第2學期 第10週)
  - Feature highlights: 記憶式學習、智慧預警、數據→行動
  - Tech stack badges
- [x] Student learning dashboard at `/student`
  - Course cards row with active course highlight
  - Classroom real-time feedback banner (課堂即時回饋)
  - Stats from real API: 累計記憶、已知弱項、涵蓋主題
  - Radar chart: topic distribution from `/analytics/student/{id}`
  - AI suggestions: populated from real struggle data
  - Learning trajectory chart from `/analytics/student/{id}/trajectory`
  - Preferences section from real memory data
  - Embedded AI chat panel (right sidebar) connected to `/chat` API
  - URL param `?sid=` for student switching (default 1001)
  - Dashboard auto-refreshes after each chat message
- [x] Route refactor: `/` → landing.html, `/student` → student.html
- [x] 3 new page route tests (113 total)

## Hotfix: Dynamic LLM Label (2026-04-10)
- [x] Fix hardcoded "Claude Haiku" in landing.html and student.html
  - Both pages now fetch /health API and display actual llm_provider dynamically
  - Consistent with index.html (SPA) behavior
  - Fallback text "AI Engine" shown before API response

## Current State
Phase: 6 (Demo & Polish) — In Progress
Done: Landing page + student dashboard with real API data, 113 tests passing
Next step: 組隊、等第31屆須知公告、錄製 Demo 影片
