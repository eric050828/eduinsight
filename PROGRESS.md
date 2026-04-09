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
- [ ] add_conversation integration (use Lite-Mem's fact extraction on chat history)
- [ ] Semantic search with embeddings (enable Lite-Mem embedder="auto")

## Phase 3: Learning Analytics
- [ ] Extract learning patterns from Lite-Mem memory
  - Weak topics per student
  - Common class-wide struggles
  - Learning trajectory over time
- [ ] Teacher dashboard API endpoints
- [ ] Tests

## Phase 4: Moodle Plugin / Integration
- [ ] Moodle block plugin or LTI integration
- [ ] Embed chat assistant in Moodle course page
- [ ] Real-time analytics in Moodle teacher view

## Phase 5: Demo & Polish
- [ ] Demo scenario: student uses assistant for a semester
- [ ] Export/import memory (Lite-Mem portable format)
- [ ] InnoServe competition materials

## Current State
Phase: 2 (Memory Integration)
Next step: Get GEMINI_API_KEY for live testing, then add Lite-Mem add_conversation integration for richer fact extraction from chat history
