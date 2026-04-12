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

## Student Risk Assessment (2026-04-10)
- [x] assess_risk() in analytics.py — calculates risk level + persistence score
  - Persistence score (0-100) weighted from: recency (35%), volume (25%), trend (25%), struggle ratio (15%)
  - Risk factors: 零互動, 長期消失, 活動量偏低/嚴重不足, 困難比例偏高/過高, 活動量驟降
  - Class average comparison for volume scoring
  - Supports `now` param for testability
- [x] GET /analytics/student/{id}/risk endpoint
- [x] 9 new tests (122 total)
- [x] Enhanced student.html: 5-student switcher, per-student multi-course demo data, chat history
- [x] Enhanced teacher.html: multi-course switching, AI summaries, student detail modals, care messages

## Conversation History API (2026-04-10)
- [x] GET /student/{id}/conversations — retrieve past chat sessions from messages table
  - Groups messages by session_id, sorted most recent first
  - Uses shared Memory connection (testable with :memory: DB)
- [x] Student dashboard loads real conversation history on page load
  - Shows past conversations with date dividers
  - "新對話從這裡開始" separator before new messages
- [x] 5 new tests (127 total)
- [x] Error handling: conversations endpoint gracefully returns empty on DB errors
- [x] Enhanced /health endpoint with memory DB status (path, user count, fact count)
- [x] Demo conversation seeding (demo_conversations.py)
  - 4 students with realistic Q&A exchanges (linked list, DP, Python, SQL)
  - /demo/reset now seeds messages table alongside facts
  - 1 new test (128 total)

## Hotfix: Conversations API + Student UI (2026-04-10)
- [x] Fix conversations endpoint — use Lite-Mem get_messages() API instead of raw SQLite
  - Old code opened separate DB connection, broke in-memory tests (3 failures)
  - Now shares Memory instance connection, all 128 tests pass
- [x] Student chat UI enhancements
  - Markdown rendering via marked.js in chat messages
  - KaTeX math formula support (LaTeX rendering)
  - Embedded HTML iframe with fullscreen toggle for interactive content

## Hotfix: Supervisor Bug Reports Round 3 (2026-04-10)
- [x] Fix student.html LLM label — fetch /health to display actual llm_provider dynamically
  - Was always showing "AI Engine", now fetches /health on init and updates #llmLabel
- [x] Add SVG favicon (🎓) to all 6 HTML pages
  - landing.html, student.html, teacher.html, index.html, demo.html, semester.html
  - Eliminates favicon.ico 404 console errors on all pages
- [x] 128 tests still passing

## Demo UX Polish (2026-04-10)
- [x] Student stats cards fetch from real API (`/analytics/student/{id}`)
  - 累計記憶、已知弱項、涵蓋主題 now reflect actual Lite-Mem data
  - Hardcoded values serve as instant fallback while API loads
  - Stats auto-refresh after each chat message (real-time feedback)
- [x] Landing page one-click Demo button
  - "🚀 一鍵載入 Demo 資料" button calls POST /demo/reset
  - Shows loading state → success count → auto-redirect to /student
  - Error handling with retry capability
- [x] Navigation consistency across all pages
  - SPA (index.html): added links to new student/teacher dashboards + demo walkthrough
  - Landing page: added quick links to SPA prototype, demo walkthrough, semester simulation
  - All pages now mutually reachable without manual URL entry
- [x] 128 tests still passing

## Teacher Dashboard Live Data (2026-04-10)
- [x] Add 「📡 即時數據」section to teacher.html — connects to real API
  - Nav sidebar: new "即時數據" link scrolls to live data section
  - Stats cards: Demo 學生數、累計記憶、常見困難、風險學生（from /teacher/students + /analytics/class + /analytics/student/{id}/risk）
  - Student table: real students with fact count, categories, risk level, persistence score
  - Click student → modal shows actual memories + weak topics + preferences from API
  - Class difficulty ranking from /analytics/class common_struggles
  - Topic distribution doughnut chart (filters out week-based noise)
  - Refresh button for real-time updates
  - Fixes demo flow disconnect: Landing → Demo Reset → Student chat → Teacher sees SAME students
- [x] 128 tests still passing

## Bugfix: Supervisor Review Round 8 (2026-04-11)
- [x] Fix /health memory_db — DetailedStats is dataclass, not dict; use stats.total_users/total_facts
- [x] Fix demo.html navigation — 2 links pointing to `/` changed to `/student`
- [x] Filter analytics topic_distribution — exclude `^W\d+` week-noise keys (13 items removed)
- [x] Unify seed_rich_demo.py categories — achievement→general, question→general, struggle→struggling
- [x] 128 tests still passing

## Fix: Chat Messages Stored in History (2026-04-11)
- [x] /chat endpoint now stores user+assistant messages to Lite-Mem messages table
  - Each chat round gets a unique session_id (chat_{timestamp_ms})
  - Both LLM and fallback paths store messages
  - Conversations API (/student/{id}/conversations) now returns real chat history
  - Previously only demo-seeded conversations appeared in history
- [x] 1 new test (129 total)

## Fix: Bug 5 — 1005 Data Flow Integration (2026-04-11)
- [x] Add 1005 (E 張同學) to demo_data.py DEMO_STUDENTS (15 facts: DB-focused, general/struggling/preference)
- [x] Add 1005 conversations to demo_conversations.py (2 sessions: multi-table JOIN, EXPLAIN interpretation)
- [x] /demo/reset now seeds all 5 students with consistent categories
  - Previously: 1005 had stale data from old seed script with wrong categories (achievement/question/struggle)
  - Now: 1005 uses same category scheme as 1001-1004 (general/struggling/preference)
- [x] Updated tests: 4→5 students, 45→60 total memories
- [x] 129 tests passing

## Cleanup & Demo Script (2026-04-11)
- [x] Update DEMO_REQUIREMENTS.md — mark chat history persistence (item 3) as done
- [x] Clean up orphaned DB files (test_demo.db, test_ts.db, eduinsight.db)
- [x] Add *.db-shm, *.db-wal to .gitignore
- [x] Rewrite Demo 影片腳本 to match current UI (landing→student→teacher flow)
  - Updated to reflect: one-click demo, real-time stats, risk assessment, conversation history
  - Follows Supervisor's recommended 3-minute demo route
  - Added detailed recording preparation notes and anonymization checklist
- [x] 129 tests still passing

## Fix: Bug 6 — demo.html 文案同步 (2026-04-11)
- [x] "4 students" → "5 students"（兩處文案）
- [x] 新增 Student 1005 profile card（mid-level DB learner）
- [x] 129 tests still passing

## Demo 影片試錄預檢 (2026-04-11)
- [x] Playwright 完整 Demo 路線走查（7 步驟全 PASS）
  - Landing → 一鍵 Demo → Student A/E/D → Teacher 預警 → Teacher 即時數據
  - 所有頁面 0 console errors，切換流暢無延遲
  - 截圖存於 `demo-walkthrough/`（9 張）
- [x] 試錄注意事項確認
  - ClaudeCLIClient 回覆 ~30-90 秒，需後製剪接
  - 建議 Chrome Zoom 125% 讓文字清晰
  - 匿名要求：localhost URL、代號姓名（已內建）、無學校 Logo
- [x] 129 tests still passing

## Demo 影片試錄預檢 Round 2 (2026-04-11)
- [x] 完整 Demo 路線 Playwright 走查（8 步驟全 PASS）
  - Step 1: Landing page — 學生端/教師端入口、Tech Stack 動態顯示 ✅
  - Step 2: 一鍵 Demo — POST /demo/reset → 60 memories → 自動跳轉 /student ✅
  - Step 3: Student A 陳同學 — 12 記憶、3 弱項、雷達圖、軌跡圖、2 段歷史對話 ✅
  - Step 4: AI 問答 — 問 preorder vs inorder → AI 回覆含記憶引用（1 條）→ 統計即時更新 12→14 ✅
  - Step 5: 切換 D 李同學 — 11 記憶、2 弱項、雷達圖不均衡 ✅
  - Step 6: Teacher 儀表板 — 班級總覽、散佈圖、熱力圖 ✅
  - Step 7: 預警中心 — D 李 12%、C 王 28%、A 陳 61%、困難排行 4 項 ✅
  - Step 8: 即時數據 — 5 學生、62 記憶、學生 1005 modal 含弱項+偏好+15 筆記憶 ✅
- [x] 截圖存於 `demo-trial/`（12 張）
- [x] 所有頁面 0 console errors
- [x] 129 tests passing (2.53s)
- 試錄觀察：
  - ClaudeCLIClient AI 回覆等待約 30 秒，錄影時需剪接加速
  - 頁面切換流暢無延遲
  - 1080p 下文字清晰，建議 Zoom 125% 更佳
  - AI 回覆品質良好：preorder/inorder 差異 + 記憶引用 + 個人化追問

## Competition Doc Sync (2026-04-11)
- [x] Update 系統概述文件 to reflect current state
  - Test count: 110 → 129, expanded test scope description
  - Added: conversation history persistence (student feature)
  - Added: student risk assessment (teacher feature)
  - Removed "學習預警" from future plans (already implemented)
  - Added push notification as new future plan item
- [x] 129 tests still passing

## Code Quality Cleanup (2026-04-12)
- [x] Fix all ruff lint warnings (15 errors → 0)
  - Removed unused imports in app.py and test files (os, JSONResponse, ClassAnalytics, etc.)
  - Modernized type annotations: `timezone.utc` → `UTC`, `Optional[X]` → `X | None`
  - Fixed line-too-long in source and test files
  - Added per-file E501 ignore for demo data files with long content strings
  - Sorted imports across test files
- [x] Added .env.example documenting all supported environment variables
- [x] 129 tests still passing, ruff fully clean

## RAG: Course Material Q&A (2026-04-12)
- [x] Document parsing module (documents.py)
  - PDF text extraction via PyMuPDF (page-level, with page metadata)
  - PPTX text extraction via python-pptx (slide-level, with slide metadata)
  - Text chunking with overlap (paragraph-aware splitting)
  - Auto-detect file type from extension
- [x] RAG engine (rag.py)
  - CourseRAG class using Lite-Mem as vector store
  - Course namespace: user_id = "course:{course_id}", category = "course_material"
  - Reuses Lite-Mem's FTS5 + cosine hybrid search — zero modification to Lite-Mem
  - Tagged text format: "[filename p.N] chunk text" for source tracking
  - index_document / search / list_documents / remove_document / get_context_for_prompt
- [x] API endpoints
  - POST /courses/{id}/materials — upload PDF/PPTX, parse+chunk+index
  - GET /courses/{id}/materials — list indexed documents
  - DELETE /courses/{id}/materials/{filename} — remove document chunks
- [x] Chat integration
  - ChatRequest accepts optional course_id field
  - When provided, searches course materials and injects RAG context into prompt
  - ChatResponse includes material_context with source citations
  - System prompt updated to cite source (filename + page) in answers
- [x] 48 new tests (177 total), ruff clean

## Frontend: RAG Material Upload & Chat Integration (2026-04-12)
- [x] Teacher dashboard: 教材管理 UI
  - Sidebar nav: 📚 教材管理 section
  - Upload: drag-and-drop + file picker (PDF/PPTX), course ID input
  - Upload progress with per-file status (chunks indexed, page count)
  - Material list: auto-load indexed documents, delete with confirmation
  - Toast notification on delete
- [x] Student chat: course_id RAG integration
  - Each course now has `courseId` field (ds101, py101, db101)
  - Chat requests include `course_id` for RAG context retrieval
  - Material citations displayed as collapsible "📚 引用了 N 段教材" toggle
  - Consistent with existing memory context toggle pattern
- [x] 177 tests passing, ruff clean

## AI Quiz Generation (2026-04-12)
- [x] Quiz generation module (quiz.py)
  - QuizGenerator: uses RAG to retrieve material chunks → prompts LLM to generate MCQ
  - QuizQuestion dataclass: question, options (A-D), answer, explanation, source
  - Robust JSON parsing: handles markdown fences, trailing commas, surrounding text
  - Fallback search when default query doesn't match FTS5 content
  - Configurable: topic focus, num_questions (1-20), top_k chunks
- [x] API endpoint: POST /courses/{course_id}/quiz/generate
  - Request: { topic, num_questions }
  - Response: { course_id, topic, questions[], chunks_used }
  - 404 if no materials indexed, 503 if no LLM configured
- [x] Teacher dashboard: AI 出題 UI
  - Sidebar nav: 🎯 AI 出題 section
  - Generator: course ID, topic (optional), question count inputs
  - Preview: rendered MCQ with correct answer highlight + explanation
  - Export: copy all questions as plain text to clipboard
- [x] 22 new tests (199 total), ruff clean

## Live Quiz Sessions — Real-time Classroom Quiz (2026-04-12)
- [x] QuizSessionManager (live_quiz.py)
  - Session lifecycle: create → activate → close
  - Student answer submission with duplicate replacement
  - Real-time stats: per-question correct rate, option distribution, overall rate
  - In-memory store (single-process demo)
- [x] API endpoints (9 new routes)
  - POST /quiz/sessions — create session from questions
  - POST /quiz/sessions/{id}/activate — open for student answers
  - POST /quiz/sessions/{id}/close — stop accepting answers
  - GET /quiz/sessions/{id} — session info
  - GET /quiz/sessions/{id}/questions — questions without answers (student view)
  - POST /quiz/sessions/{id}/answer — submit answer (immediate feedback)
  - GET /quiz/sessions/{id}/stats — real-time class statistics
  - GET /quiz/sessions — list all sessions
- [x] 29 new tests (228 total), ruff clean

## Live Quiz UI — Teacher Management + Student Participation (2026-04-12)
- [x] Teacher dashboard: 即時測驗管理 UI
  - Sidebar nav: 📡 即時測驗 section
  - "🚀 建立即時測驗" button in quiz preview (creates session from AI-generated questions)
  - Session list with status indicators (waiting/active/closed)
  - Session control panel: activate (▶), close (⏹), copy session ID
  - Real-time per-question stats: correct rate + option distribution bars (A/B/C/D)
  - Auto-polling every 3s during active sessions for live updates
- [x] Student dashboard: 課堂測驗參與 UI
  - Quiz join banner with session ID input
  - Question display with click-to-answer interaction
  - Immediate feedback per question (correct ✓ / incorrect ✗ with correct answer shown)
  - Score summary after completing all questions
- [x] 2 new tests (230 total), ruff clean

## Classroom Interaction — Polls, Anonymous Questions, Danmaku (2026-04-12)
- [x] InteractionManager (interaction.py)
  - **Polls**: create → activate → vote → close lifecycle, real-time stats (distribution per option)
  - **Anonymous Questions**: post (student identity hidden in API response), upvote (idempotent), resolve (teacher action), sorted by upvotes
  - **Danmaku (Text Wall)**: post (max 100 chars), get recent (newest-first, with limit + since filter), per-course isolation
  - In-memory store (single-process demo, same pattern as live_quiz.py)
- [x] API endpoints (14 new routes under /interaction/)
  - Polls: POST /interaction/polls, POST .../activate, POST .../close, POST .../vote, GET .../stats, GET /interaction/polls
  - Questions: POST /interaction/questions, POST .../upvote, POST .../resolve, GET /interaction/questions
  - Danmaku: POST /interaction/danmaku, GET /interaction/danmaku
- [x] 42 new tests (272 total), ruff clean

## Classroom Interaction UI — Teacher + Student (2026-04-12)
- [x] Teacher dashboard: 課堂互動管理 UI
  - Sidebar nav: 🙋 課堂互動 section
  - **投票管理**: create poll (title + options), poll list with status indicators, select → stats panel
  - Poll stats: real-time bar chart (per-option votes + percentage), activate/close controls
  - Auto-polling every 3s during active polls for live vote updates
  - **匿名提問**: question feed sorted by upvotes, resolve button per question, show/hide resolved toggle
  - **彈幕文字牆**: colorful bubble display, course selector, refresh button
- [x] Student dashboard: 課堂互動參與 UI
  - Tabbed interface (📊 投票 / ❓ 提問 / 💬 彈幕) in interaction panel
  - **投票**: shows active polls with live results, click to vote, visual percentage bars
  - **匿名提問**: input + send, question feed with upvote buttons (👍), resolved status
  - **彈幕**: input + send (max 100 chars), colorful bubble stream display
  - Enter key support for question and danmaku inputs
- [x] 272 tests passing, ruff clean

## Attendance / Check-in System (2026-04-12)
- [x] AttendanceManager (attendance.py)
  - Session lifecycle: create (open) → close, with auto-generated 6-digit check-in code
  - Student check-in with code validation + duplicate prevention
  - Late detection: configurable threshold (default 10 min)
  - GPS proximity check: haversine distance validation within configurable radius
  - Session stats: present/late counts, student list
  - Student attendance history across sessions (filterable by course)
  - Find session by code (case-insensitive, open sessions only)
- [x] API endpoints (10 new routes under /attendance/)
  - POST /attendance/sessions — create & open session
  - POST /attendance/sessions/{id}/close — close session
  - GET /attendance/sessions/{id} — session details
  - GET /attendance/sessions — list sessions (optional course filter)
  - POST /attendance/sessions/{id}/checkin — student check-in
  - GET /attendance/sessions/{id}/records — all check-in records
  - GET /attendance/sessions/{id}/stats — attendance statistics
  - GET /attendance/student/{id}/history — student attendance history
  - POST /attendance/checkin-by-code — check-in using code only (finds matching session)
- [x] Teacher dashboard: 點名簽到管理 UI
  - Sidebar nav: 📋 點名簽到 section
  - Create session: course selector, title, late threshold, optional GPS (auto-detect location)
  - Active session display: large check-in code, copy button, close button
  - Session list: history with status indicators, click → stats panel
  - Real-time stats: present/late counts with progress bar, auto-polling every 3s
- [x] Student dashboard: 簽到 UI
  - Check-in banner: 6-digit code input with uppercase formatting
  - Auto GPS detection on check-in (optional)
  - Immediate feedback: present/late status with timestamp
  - Enter key support
- [x] 44 new tests (316 total), ruff clean

## Grade Management System (2026-04-12)
- [x] GradeManager (grades.py)
  - Course grade categories with configurable weights (must sum to 100%)
  - Score recording per student/category/item with duplicate-update support
  - Weighted total calculation: category average × weight → sum
  - Student summary: per-category breakdown, average %, weighted contribution
  - Class overview: mean, median, std_dev, min/max, A-F distribution bands
  - Rankings with proper tie handling
  - Score deletion, filtered queries (by student/category)
- [x] API endpoints (10 new routes under /grades/)
  - POST /grades/{course_id}/categories — set grade weights
  - GET /grades/{course_id}/categories — get categories
  - POST /grades/{course_id}/scores — record a score
  - GET /grades/{course_id}/scores — list scores (filterable)
  - DELETE /grades/{course_id}/scores — delete a score
  - GET /grades/{course_id}/student/{student_id} — weighted summary with rank
  - GET /grades/{course_id}/overview — class statistics + rankings + distribution
  - GET /grades/courses — list courses with grades configured
- [x] Renamed old Moodle grades proxy: /grades/ → /moodle/grades/ (route conflict fix)
- [x] 42 new tests (358 total), ruff clean

## Teacher Dashboard: Grade Management UI (2026-04-12)
- [x] Teacher dashboard: 成績管理 UI
  - Sidebar nav: 📝 成績管理 section
  - **評分項目設定**: course selector, dynamic category rows (name + weight%), save/load categories
  - Weight validation (must sum to 100%)
  - **成績登錄**: student ID, category dropdown (auto-populated), item name, score/total input
  - **成績分布**: Chart.js bar chart (A/B/C/D/F bands), stats cards (mean, std_dev, range)
  - **排名表**: medal icons for top 3, grade letter coloring, weighted total display
  - **成績記錄**: full score records table with delete action per entry
  - Refresh button, course change auto-reload
- [x] Demo grade data seeding (demo_grades.py)
  - ds101 course: 3 categories (作業 30%, 期中考 30%, 期末考 40%)
  - 5 students × 4 scores each (HW1-3 + midterm), realistic performance spread
  - /demo/reset now seeds grades alongside memories and conversations
- [x] 1 new test (359 total), ruff clean

## Student Grade View UI (2026-04-12)
- [x] Student dashboard: 我的成績 section
  - Grade card shows weighted total with letter grade (A/B/C/D/F color coding)
  - Class rank display (e.g. "第 2 / 5 名")
  - Per-category breakdown: name, weight, average %, weighted contribution
  - Progress bars with color coding (green ≥80%, amber ≥60%, red <60%)
  - Individual score items (e.g. "HW1: 82/100")
  - Auto-loads from `/grades/{courseId}/student/{moodleId}` API
  - Hidden when no grade data exists for current course
  - Updates on course switch
- [x] 1 new test (360 total), ruff clean

## Teaching Analytics Report (2026-04-12)
- [x] Report generation module (report.py)
  - ReportGenerator: aggregates Memory, Grades, Attendance, Interaction, Quiz data
  - WeeklyReport: comprehensive metrics (students, facts, struggles, grades, attendance, polls, quiz)
  - AIGradeCorrelation: Pearson correlation between AI engagement (fact count, persistence score) and weighted grades
  - Per-student metrics: fact count, struggle count, risk level, persistence score, weighted grade, attendance rate
  - Built-in Pearson correlation (no scipy dependency)
  - Human-readable correlation insight (強正/弱負/無相關)
- [x] API endpoints
  - GET /reports/weekly/{course_id} — comprehensive weekly teaching report
  - GET /reports/correlation/{course_id} — AI engagement vs grade correlation analysis
  - GET /reports/export/excel/{course_id} — download Excel report (.xlsx with 4 sheets)
- [x] Excel export (openpyxl)
  - Sheet 1: 教學總覽 (overview metrics)
  - Sheet 2: 學生明細 (per-student details with risk, grades, attendance)
  - Sheet 3: 常見困難 (ranked struggle topics)
  - Sheet 4: AI互動-成績相關 (correlation data + insight)
  - Formatted headers, auto-width columns
- [x] Teacher dashboard: 教學分析報表 UI
  - Sidebar nav: 📋 教學分析報表 section
  - Overview stats: 6 cards (students, AI facts, grade mean, attendance, high risk, quiz avg)
  - Scatter chart: AI interaction count vs weighted grade (Chart.js)
  - Correlation insight display (Pearson r value + interpretation)
  - Struggles ranking: horizontal bar chart sorted by frequency
  - Student detail table: comprehensive multi-metric view (ID, facts, struggles, risk, persistence, grade, attendance)
  - Interaction summary: polls, questions, danmaku, quiz, attendance counts
  - One-click Excel export button
- [x] 30 new tests (390 total), ruff clean

## Lecture Recording System — Phase 3 Start (2026-04-12)
- [x] Transcription module (transcribe.py)
  - Groq Whisper API backend (whisper-large-v3-turbo, 25MB limit)
  - OpenAI Whisper API backend
  - StubTranscriber for testing (returns placeholder segments)
  - auto_transcriber() factory: selects backend from GROQ_API_KEY / OPENAI_API_KEY
  - TranscriptResult with segments (start, end, text) and full_text
- [x] Lecture manager (lectures.py)
  - LectureManager: full pipeline (transcribe → summarize → index to RAG)
  - Lecture dataclass: id, course_id, title, filename, transcript, summary, chunks_indexed
  - Transcript segments indexed into CourseRAG for student search
  - CRUD: process_lecture, list, get, delete (with RAG cleanup)
  - In-memory store (single-process demo)
- [x] API endpoints (4 routes)
  - POST /lectures/{course_id}/upload — upload audio file, transcribe + summarize + index
  - GET /lectures/{course_id} — list lectures for course
  - GET /lectures/{course_id}/{lecture_id}/transcript — full transcript with segments
  - DELETE /lectures/{course_id}/{lecture_id} — remove lecture + RAG chunks
- [x] Teacher dashboard: 課堂錄音管理 UI
  - Sidebar nav: 🎙️ 課堂錄音 section
  - Upload: file picker (audio), course ID + title input
  - Lecture list: shows title, filename, chunk count, created date
  - Transcript viewer: click lecture → view full transcript + summary
  - Delete with confirmation
- [x] Student dashboard: lecture browsing
  - Lectures card showing available recordings per course
  - Lecture content indexed into RAG — students can ask questions about lecture content in chat
- [x] 40 new tests (430 total), ruff clean

## AI Classroom Assistant — Real-time Teaching Insights (2026-04-12)
- [x] ClassroomAssistant engine (classroom_assistant.py)
  - Aggregates live data: quiz results, polls, anonymous questions, danmaku, attendance
  - Alert system: warning + critical levels from 5 data sources
  - Quiz analysis: per-question correct rate, low participation detection
  - Poll analysis: confusion keyword detection (懂/不懂), confusion ratio calculation
  - Question analysis: unresolved question surge, high-upvote individual alerts
  - Attendance analysis: late ratio monitoring
  - Danmaku analysis: confusion keyword burst in 5-min window, message rate
  - Suggestion engine: rule-based actionable teaching advice from alerts
  - Configurable thresholds: correct rate, confusion ratio, question surge, late ratio
- [x] API endpoint
  - GET /classroom/{course_id}/snapshot — real-time snapshot with alerts, suggestions, metrics
  - Query param: expected_students (default 30)
- [x] Teacher dashboard: 🤖 AI 課堂助理 UI
  - Sidebar nav: AI 課堂助理 section
  - 6 metric cards: quiz correct rate, participation, poll confusion, active questions, attendance, danmaku rate
  - Color-coded metrics (green/amber/red based on thresholds)
  - Alert feed: critical (🚨) and warning (⚠️) with source icons
  - Suggestion cards with priority levels
  - Course ID + expected students input
  - Auto-refresh toggle (5s interval) for live monitoring
- [x] 30 new tests (460 total), ruff clean

## Office Hour Integration (2026-04-12)
- [x] OfficeHourManager (office_hours.py) — already existed with full business logic
  - Slot lifecycle: create → book → cancel, with time validation
  - Booking lifecycle: pending → in_progress → completed/cancelled/no_show
  - Student learning summary: pulls struggles, weak topics, preferences from Lite-Mem
  - Resolution notes recorded to student memory via Lite-Mem
  - 33 unit tests already passing
- [x] API endpoints (13 new routes under /office-hours/)
  - POST /office-hours/slots — create available time slot
  - GET /office-hours/slots — list slots (optional course_id, status filter)
  - GET /office-hours/slots/{id} — get slot details
  - POST /office-hours/slots/{id}/cancel — cancel available slot
  - POST /office-hours/slots/{id}/book — student books a slot
  - GET /office-hours/bookings — list bookings (filter by course/student/teacher/status)
  - GET /office-hours/bookings/{id} — get booking details
  - POST /office-hours/bookings/{id}/start — mark meeting started
  - POST /office-hours/bookings/{id}/resolve — complete with notes (updates memory)
  - POST /office-hours/bookings/{id}/cancel — cancel booking
  - POST /office-hours/bookings/{id}/no-show — mark student no-show
  - GET /office-hours/students/{id}/summary — AI learning summary (pre-meeting brief)
- [x] Teacher dashboard: Office Hour 管理 UI
  - Sidebar nav: 🕐 Office Hour section
  - Create slot: course, datetime picker, location input
  - Slot list: table with status, time, course, cancel action
  - Booking list: table with student, topic, status, action buttons
  - Actions: start meeting, resolve (prompt for notes), cancel, mark no-show
  - Student summary panel: stats cards (facts/struggles/topics), detail breakdown
- [x] Student dashboard: Office Hour 預約 UI
  - Available slots display with one-click booking
  - Topic input on booking (optional)
  - My bookings list with cancel action
  - Auto-loads on page init
- [x] 14 new API tests (47 in test_office_hours.py), 507 total, ruff clean

## ROADMAP Completion Summary (2026-04-12)
- [x] ROADMAP.md checkboxes updated — all 3 phases marked complete
- All Phase 1 (Moodle + AI), Phase 2 (Zuvio features), Phase 3 (虛實整合) items done
- 507 tests passing, ruff clean

## Bugfix: Supervisor Review Round 9 (2026-04-12)
- [x] Fix Bug 1 [Critical] — app.py:93 global 宣告加入 `_rag, _quiz`
  - RAG 和 Quiz 引擎在 lifespan 中正確初始化為 global
  - 修復 7 個 API endpoint 503 錯誤 (materials CRUD, quiz generate, RAG chat context)
  - 更新 test fixtures (test_rag_api.py, test_quiz.py) 以適配 lifespan global 覆蓋
- [x] Fix Bug 2 — student.html `?sid=` URL 參數解析
  - 頁面初始化時解析 `?sid=` 參數，映射 moodle ID → student key
  - 自動更新 student button active state 和 user badge
- [x] Fix Bug 3 — demo grades 擴展至 3 課程 (ds101, py101, db101)
  - E 張同學切換到 db101 不再 404
  - 新增 py101 (Lab/期中/期末專題) 和 db101 (作業/期中/專題) 成績資料
- [x] Fix attendance UI auto-load — 教師端頁面載入時自動偵測 open session
  - loadAttSessions() 發現 open session 時自動 showActiveSession + startAttPolling
- [x] Add test_app_init.py — 6 個 regression tests 防止 global 宣告遺漏
  - 驗證 _memory, _assistant, _rag, _quiz, _lectures 在 lifespan 後正確初始化
  - 驗證 GET /courses/*/materials 不回 503
- [x] .gitignore 加入 .playwright-mcp/, *.png, *-snapshot.md, demo-walkthrough/, demo-trial/
- [x] 513 tests passing, ruff clean

## Bugfix: Supervisor Review Round 10 (2026-04-12)
- [x] Fix Bug 4 — office-hours/bookings student_id type mismatch
  - student.html sent string ID ("B11209001") via `.id`, but API expects int
  - Changed to use `.moodle` numeric ID (1001) for both loadStudentOH() and bookOHSlot()
  - Office-hours booking query and booking creation now work correctly
- [x] Commit untracked project files
  - docker-compose.moodle.yml (Moodle dev environment)
  - docs/ (competition pitch materials: PDF + markdown)
  - src/eduinsight/lti_config.json (LTI 1.3 configuration)
- [x] End-to-end RAG → AI Quiz → Live Quiz integration test
  - Full pipeline: upload PDF → parse+chunk+index → AI generate MCQ → create live session → student answer → real-time stats → close
  - Also tests: chat with RAG context, material deletion cleanup, session listing
  - 4 new tests (517 total), ruff clean

## Demo RAG Material Seeding (2026-04-12)
- [x] Demo course material seed data (demo_materials.py)
  - ds101 lecture notes: 9 chunks covering arrays, linked lists, stacks, queues, trees, hash tables, graphs, sorting
  - Pre-built ParsedDocument objects — no real PDF needed
  - seed_demo_materials() clears existing + indexes fresh chunks into CourseRAG
- [x] /demo/reset now seeds course materials for RAG
  - Rebuilds _rag and _quiz globals after Memory recreation
  - Enables full RAG → AI Quiz → Live Quiz demo flow from single click
- [x] 1 new test (518 total), ruff clean

## Teacher AI Interaction Summaries — Real Data (2026-04-12)
- [x] AI interaction summary generator (analytics.py)
  - generate_student_summary(): rule-based text from real analytics data (no LLM needed)
  - Aggregates: fact count, struggles, weak topics, preferences, risk factors, trajectory
  - generate_class_summaries(): batch summaries for all students, sorted by risk level
  - AIInteractionSummary dataclass with moodle_user_id, name, risk, text
- [x] GET /teacher/summaries API endpoint
  - Returns all student summaries with risk level and display names
  - Demo name map for known students (1001-1005)
- [x] Teacher dashboard: AI 互動摘要 section now fetches from real API
  - Shows "📡 即時分析" label when real data loaded, "模擬資料" as fallback
  - Graceful degradation: falls back to hardcoded mockup data if API unavailable
- [x] 10 new tests (528 total), ruff clean

## Current State
Phase: ROADMAP 三階段全部完成 ✅
Done: 所有計畫功能已實作（AI 助教、RAG、測驗、互動、點名、成績、報表、錄音、課堂助理、Office Hour）
Tests: 528 passing
Bugs fixed: Supervisor 報告的 4 個 bug 全部修復（global 宣告、sid 參數、grades 404、office-hours student_id）
Demo: 一鍵 Demo 現在包含 RAG 教材 seed，可完整走通 RAG→AI 出題→即時測驗流程
AI 摘要: 教師端 AI 互動摘要改為從即時 API 取得真實分析結果
Next step: 競賽準備（組隊、文件、影片）或新功能開發
