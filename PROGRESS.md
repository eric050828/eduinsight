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
- [ ] Moodle block plugin or LTI integration
- [ ] Embed chat assistant in Moodle course page
- [ ] Real-time analytics in Moodle teacher view

## Phase 6: Demo & Polish
- [ ] Demo scenario: student uses assistant for a semester
- [ ] Export/import memory (Lite-Mem portable format)
- [ ] InnoServe competition materials

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

## Current State
Phase: 4 (Learning Analytics) — Complete, demo memory issues fixed
Done: demo data fixed (45/45 survival), category labels, dark theme SPA, ClaudeCLI fallback
Next step: Set up LLM (GEMINI_API_KEY or test Claude CLI) → Phase 5 Moodle integration
