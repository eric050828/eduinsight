"""Tests for the LearningAssistant memory layer."""

from litemem import Memory

from eduinsight.assistant import LearningAssistant, _student_uid


class TestStudentUid:
    def test_namespace_prefix(self) -> None:
        assert _student_uid(42) == "moodle:42"

    def test_different_ids_different_uids(self) -> None:
        assert _student_uid(1) != _student_uid(2)


class TestLearningAssistant:
    def setup_method(self) -> None:
        self.mem = Memory()  # in-memory
        self.assistant = LearningAssistant(self.mem)

    def test_record_and_retrieve_question(self) -> None:
        self.assistant.record_question(1, "What is polymorphism?", topic="OOP")
        result = self.assistant.get_student_context(1, "polymorphism")
        assert len(result) > 0
        assert any("polymorphism" in t.lower() for t in result)

    def test_record_struggle(self) -> None:
        self.assistant.record_struggle(1, "recursion", details="keeps getting stack overflow")
        result = self.assistant.get_student_context(1, "recursion")
        assert len(result) > 0
        assert any("recursion" in t.lower() for t in result)

    def test_record_preference(self) -> None:
        self.assistant.record_preference(1, "prefers visual diagrams")
        result = self.assistant.get_student_context(1, "visual")
        assert len(result) > 0

    def test_record_interaction(self) -> None:
        self.assistant.record_interaction(
            moodle_user_id=1,
            question="What is a linked list?",
            answer="A linked list is a data structure...",
            topic="Data Structures",
        )
        result = self.assistant.get_student_context(1, "linked list")
        assert len(result) >= 2  # Both Q and A stored

    def test_user_isolation(self) -> None:
        """Memories for one student should not leak to another."""
        self.assistant.record_question(1, "What is Python?")
        self.assistant.record_question(2, "What is Java?")

        result1 = self.assistant.get_student_context(1, "Python")
        result2 = self.assistant.get_student_context(2, "Python")

        assert any("Python" in t for t in result1)
        # User 2 never asked about Python, should have no results
        assert not any("Python" in t for t in result2)

    def test_memory_property(self) -> None:
        assert self.assistant.memory is self.mem

    def test_get_all_memories(self) -> None:
        self.assistant.record_question(1, "What is OOP?")
        self.assistant.record_struggle(1, "inheritance")
        self.assistant.record_preference(1, "likes code examples")
        result = self.assistant.get_all_memories(1)
        assert len(result) >= 3
