"""Tests for semantic search with Lite-Mem embeddings enabled."""

from litemem import Memory

from eduinsight.assistant import LearningAssistant


class TestEmbeddingsEnabled:
    """Verify that LearningAssistant works correctly with embeddings enabled."""

    def setup_method(self) -> None:
        # embedder="stub" uses word-hash vectors (offline, no API key needed)
        self.mem = Memory(embedder="stub")
        self.assistant = LearningAssistant(self.mem)

    def test_record_and_query_with_embeddings(self) -> None:
        """Basic add/query should work with embeddings enabled."""
        self.assistant.record_question(1, "What is polymorphism in Java?")
        result = self.assistant.get_student_context(1, "polymorphism")
        assert len(result) > 0
        assert any("polymorphism" in r.lower() for r in result)

    def test_semantic_similarity_with_synonyms(self) -> None:
        """Hybrid search should retrieve semantically related memories.

        StubEmbedder uses word-hash, so exact word overlap still matters,
        but the hybrid scoring should still rank relevant results higher.
        """
        self.assistant.record_question(1, "How do I handle errors in Python?")
        self.assistant.record_question(1, "What is the weather today?")
        self.assistant.record_struggle(1, "exception handling", details="try/except blocks")

        results = self.assistant.get_student_context(1, "error handling exceptions")
        assert len(results) > 0
        # Error/exception related content should appear in results
        matches = [r for r in results if "error" in r.lower() or "exception" in r.lower()]
        assert len(matches) >= 1

    def test_user_isolation_with_embeddings(self) -> None:
        """Embedding-enabled memory should still isolate users."""
        self.assistant.record_question(1, "What is machine learning?")
        self.assistant.record_question(2, "What is databases?")

        results_1 = self.assistant.get_student_context(1, "machine learning")
        results_2 = self.assistant.get_student_context(2, "machine learning")

        assert any("machine learning" in r.lower() for r in results_1)
        assert not any("machine learning" in r.lower() for r in results_2)

    def test_multiple_memories_ranking(self) -> None:
        """With several memories stored, query should return relevant ones."""
        self.assistant.record_question(1, "What is recursion?")
        self.assistant.record_question(1, "Explain binary search trees")
        self.assistant.record_question(1, "How does quicksort work?")
        self.assistant.record_struggle(1, "recursion", details="base case confusion")
        self.assistant.record_preference(1, "prefers step-by-step examples")

        results = self.assistant.get_student_context(1, "recursion")
        assert len(results) >= 1
        # Recursion-related memories should be present in results
        recursion_hits = [r for r in results if "recursion" in r.lower()]
        assert len(recursion_hits) >= 1

    def test_extract_conversation_with_embeddings(self) -> None:
        """add_conversation (fact extraction) should work with embeddings."""
        mem = Memory(embedder="stub")
        assistant = LearningAssistant(mem, extractor="stub")

        facts = assistant.extract_from_conversation(
            moodle_user_id=10,
            question="I'm a graduate student at NTUST",
            answer="Welcome! How can I help with your studies?",
        )
        # Stub extractor should detect personal info
        assert isinstance(facts, list)
        # If facts were extracted, they should be queryable
        if facts:
            results = assistant.get_student_context(10, "NTUST student")
            assert len(results) >= 1

    def test_get_all_memories_with_embeddings(self) -> None:
        """list() should still return all memories when embeddings are enabled."""
        self.assistant.record_question(1, "What is OOP?")
        self.assistant.record_struggle(1, "inheritance")
        all_mem = self.assistant.get_all_memories(1)
        assert len(all_mem) >= 2
