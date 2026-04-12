"""Tests to verify app lifespan properly initializes all global variables.

Prevents regression of Bug 1 (global declaration missing _rag, _quiz).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from eduinsight import app as app_module


class TestAppInit:
    """Verify all critical globals are initialized after lifespan."""

    def test_rag_initialized_after_lifespan(self):
        """RAG engine should be initialized (not None) after app startup."""
        with TestClient(app_module.app) as _:
            assert app_module._rag is not None, (
                "_rag is None after lifespan — check global declaration in lifespan()"
            )

    def test_quiz_requires_llm(self):
        """Quiz generator should be set when LLM is available, None otherwise."""
        with TestClient(app_module.app) as _:
            if app_module._llm is not None:
                assert app_module._quiz is not None
            # If no LLM, _quiz being None is expected

    def test_memory_initialized(self):
        with TestClient(app_module.app) as _:
            assert app_module._memory is not None

    def test_assistant_initialized(self):
        with TestClient(app_module.app) as _:
            assert app_module._assistant is not None

    def test_lectures_initialized(self):
        with TestClient(app_module.app) as _:
            assert app_module._lectures is not None

    def test_rag_materials_api_not_503(self):
        """GET /courses/any/materials should return 200, not 503."""
        with TestClient(app_module.app) as client:
            resp = client.get("/courses/TEST/materials")
            assert resp.status_code == 200
            assert resp.json()["documents"] == [] or isinstance(resp.json()["documents"], list)
