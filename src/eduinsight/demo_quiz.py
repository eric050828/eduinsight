"""Demo quiz session data for live quiz seeding.

Provides pre-built quiz questions based on ds101 course materials so the
demo can showcase the full live quiz flow (teacher creates → students answer
→ real-time stats) without needing a working LLM to generate questions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .live_quiz import QuizSessionQuestion

if TYPE_CHECKING:
    from .live_quiz import QuizSessionManager

# ── ds101 資料結構 Quiz Questions ──

DS101_QUESTIONS: list[QuizSessionQuestion] = [
    QuizSessionQuestion(
        question="下列哪個資料結構的隨機存取（random access）時間複雜度為 O(1)？",
        options={
            "A": "鏈結串列（Linked List）",
            "B": "陣列（Array）",
            "C": "二元搜尋樹（BST）",
            "D": "堆疊（Stack）",
        },
        answer="B",
        explanation=(
            "陣列透過索引直接計算記憶體位址，因此隨機存取為 O(1)。"
            "鏈結串列需從頭走訪，BST 需走訪路徑。"
        ),
        source="ds101_lecture_notes.pdf p.1",
    ),
    QuizSessionQuestion(
        question="在已知節點位置的情況下，鏈結串列的插入操作時間複雜度為何？",
        options={
            "A": "O(n)",
            "B": "O(log n)",
            "C": "O(1)",
            "D": "O(n log n)",
        },
        answer="C",
        explanation="已知位置時只需修改前後節點的指標，為常數時間 O(1)。若需先搜尋位置則為 O(n)。",
        source="ds101_lecture_notes.pdf p.2",
    ),
    QuizSessionQuestion(
        question="堆疊（Stack）遵循什麼原則？",
        options={
            "A": "先進先出（FIFO）",
            "B": "後進先出（LIFO）",
            "C": "優先權排序",
            "D": "隨機存取",
        },
        answer="B",
        explanation=(
            "堆疊是後進先出（Last In, First Out），"
            "最後放入的元素最先被取出。佇列才是 FIFO。"
        ),
        source="ds101_lecture_notes.pdf p.3",
    ),
    QuizSessionQuestion(
        question="廣度優先搜尋（BFS）使用哪種資料結構來實作？",
        options={
            "A": "堆疊（Stack）",
            "B": "雜湊表（Hash Table）",
            "C": "佇列（Queue）",
            "D": "二元搜尋樹（BST）",
        },
        answer="C",
        explanation="BFS 使用佇列（Queue）以層序方式走訪圖的節點。DFS 才使用堆疊。",
        source="ds101_lecture_notes.pdf p.7",
    ),
    QuizSessionQuestion(
        question="雜湊表（Hash Table）的負載因子（Load Factor）超過多少時通常需要 rehash？",
        options={
            "A": "0.25",
            "B": "0.50",
            "C": "0.75",
            "D": "1.00",
        },
        answer="C",
        explanation="負載因子 = 元素數/桶數，超過 0.75 時碰撞率顯著增加，需要擴容並重新雜湊。",
        source="ds101_lecture_notes.pdf p.6",
    ),
]

# ── Student answers to simulate (partial: 3 of 5 students answered) ──

# (student_id, question_idx, selected_answer)
DS101_STUDENT_ANSWERS: list[tuple[int, int, str]] = [
    # 1001 陳同學 — 答對 4/5
    (1001, 0, "B"),  # correct
    (1001, 1, "C"),  # correct
    (1001, 2, "B"),  # correct
    (1001, 3, "C"),  # correct
    (1001, 4, "D"),  # wrong (should be C)
    # 1002 林同學 — 答對 3/5
    (1002, 0, "B"),  # correct
    (1002, 1, "A"),  # wrong
    (1002, 2, "B"),  # correct
    (1002, 3, "A"),  # wrong
    (1002, 4, "C"),  # correct
    # 1004 李同學 — 答對 2/5 (risk student)
    (1004, 0, "A"),  # wrong
    (1004, 1, "C"),  # correct
    (1004, 2, "A"),  # wrong
    (1004, 3, "C"),  # correct
    (1004, 4, "A"),  # wrong
]

DEMO_QUIZ_COURSE_ID = "ds101"
DEMO_QUIZ_TITLE = "資料結構 第10週隨堂測驗"
DEMO_QUIZ_TEACHER_ID = 9001


def seed_demo_quiz(manager: QuizSessionManager) -> str:
    """Seed a demo quiz session with pre-built questions and student answers.

    Creates an active session, submits student answers, then closes it
    so the teacher dashboard shows realistic quiz statistics.

    Returns the created session_id.
    """
    # Clear any existing sessions
    manager._sessions.clear()

    # Create session
    session = manager.create_session(
        DEMO_QUIZ_COURSE_ID,
        DS101_QUESTIONS,
        teacher_id=DEMO_QUIZ_TEACHER_ID,
        title=DEMO_QUIZ_TITLE,
    )

    # Activate so answers can be submitted
    manager.activate_session(session.session_id)

    # Submit student answers
    for student_id, q_idx, answer in DS101_STUDENT_ANSWERS:
        manager.submit_answer(
            session.session_id,
            student_id=student_id,
            question_idx=q_idx,
            selected=answer,
        )

    # Close session (finished quiz)
    manager.close_session(session.session_id)

    return session.session_id
