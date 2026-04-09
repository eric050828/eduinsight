"""Semester-long demo data for a single student's learning journey.

Simulates 18 weeks of interactions for student 2001, showing how
EduInsight's memory accumulates and personalizes over time.

Story arc:
- Weeks 1-3:  Python basics (variables, loops, functions)
- Weeks 4-6:  Data structures (lists, dicts, sets) — first struggles appear
- Weeks 7-9:  OOP concepts — struggles with inheritance
- Weeks 10-12: Algorithms intro — recursion is hard
- Weeks 13-15: File I/O, exceptions, testing — growing confidence
- Weeks 16-18: Final project & review — demonstrates mastery growth
"""

from __future__ import annotations

from dataclasses import dataclass

SEMESTER_STUDENT_ID = "moodle:2001"
SEMESTER_STUDENT_NAME = "Demo Student (林小明)"


@dataclass
class WeekData:
    """One week of student interactions."""

    week: int
    title: str
    facts: list[tuple[str, str]]  # (fact_text, category)


SEMESTER_WEEKS: list[WeekData] = [
    # --- Weeks 1-3: Python Basics ---
    WeekData(
        week=1,
        title="Python 入門：變數與型別",
        facts=[
            ("[Python] Variables and types basics: learned int, float, str, bool; type() to check", "general"),
            ("[Python] Asked about variable naming: What are the rules for naming variables in Python?", "general"),
            ("Learning preference for language: prefers Chinese explanations with English code examples", "preference"),
        ],
    ),
    WeekData(
        week=2,
        title="條件判斷與邏輯",
        facts=[
            ("[Python] If-elif-else structure: conditions evaluated top-down, first True branch executes", "general"),
            ("[Python] Boolean operators: and, or, not; short-circuit evaluation; truthy/falsy values", "general"),
            ("[Python] Asked about nested conditions: How do I avoid deeply nested if statements?", "general"),
        ],
    ),
    WeekData(
        week=3,
        title="迴圈基礎",
        facts=[
            ("[Python] For loop with range: range(start, stop, step), stop is exclusive", "general"),
            ("[Python] While loop patterns: while condition, break to exit early, continue to skip", "general"),
            ("Struggling with loop termination: sometimes writes infinite loops because condition never becomes False", "struggling"),
        ],
    ),
    # --- Weeks 4-6: Data Structures ---
    WeekData(
        week=4,
        title="列表與元組",
        facts=[
            ("[Data Structures] List operations: append, insert, pop, slice notation [start:stop:step]", "general"),
            ("[Data Structures] List comprehension syntax: [expr for item in iterable if condition]", "general"),
            ("[Data Structures] Asked about list vs tuple: When should I use a tuple instead of a list?", "general"),
        ],
    ),
    WeekData(
        week=5,
        title="字典與集合",
        facts=[
            ("[Data Structures] Dictionary methods: get() with default, keys(), values(), items() for iteration", "general"),
            ("[Data Structures] Set operations: union |, intersection &, difference -, symmetric_difference ^", "general"),
            ("Struggling with dictionary iteration: confused about iterating over keys vs values vs items", "struggling"),
        ],
    ),
    WeekData(
        week=6,
        title="巢狀資料結構",
        facts=[
            ("[Data Structures] Nested structures: list of dicts for records, dict of lists for grouping", "general"),
            ("[Data Structures] Asked about JSON parsing: How do I convert between JSON and Python dicts?", "general"),
            ("Struggling with nested access: gets IndexError/KeyError when accessing deeply nested data", "struggling"),
        ],
    ),
    # --- Weeks 7-9: OOP ---
    WeekData(
        week=7,
        title="類別與物件",
        facts=[
            ("[OOP] Class definition: class Name, __init__ constructor, self parameter, instance attributes", "general"),
            ("[OOP] Asked about self: Why do I need self in Python methods?", "general"),
            ("[OOP] Method types: instance methods (self), class methods (@classmethod, cls), static methods (@staticmethod)", "general"),
        ],
    ),
    WeekData(
        week=8,
        title="繼承與多型",
        facts=[
            ("[OOP] Inheritance syntax: class Child(Parent), super().__init__() to call parent constructor", "general"),
            ("[OOP] Polymorphism: same method name, different behavior per class; duck typing in Python", "general"),
            ("Struggling with inheritance chain: confused by MRO (method resolution order) in diamond inheritance", "struggling"),
            ("Struggling with super() calls: forgets to call super().__init__() leading to missing attributes", "struggling"),
        ],
    ),
    WeekData(
        week=9,
        title="特殊方法與封裝",
        facts=[
            ("[OOP] Dunder methods: __str__ for display, __repr__ for debug, __eq__ for comparison, __len__ for len()", "general"),
            ("[OOP] Encapsulation: _private convention, @property for getters, name mangling with __attr", "general"),
            ("[OOP] Asked about abstract classes: How do I enforce that subclasses implement certain methods?", "general"),
        ],
    ),
    # --- Weeks 10-12: Algorithms ---
    WeekData(
        week=10,
        title="遞迴入門",
        facts=[
            ("[Algorithms] Recursion basics: base case + recursive case, call stack, stack overflow risk", "general"),
            ("[Algorithms] Asked about recursion: Can you trace through factorial(5) step by step?", "general"),
            ("Struggling with recursive thinking: can write iterative solutions but can't convert to recursive", "struggling"),
        ],
    ),
    WeekData(
        week=11,
        title="排序與搜尋",
        facts=[
            ("[Algorithms] Sorting comparison: bubble O(n²), merge O(n log n), Python's Timsort is hybrid", "general"),
            ("[Algorithms] Binary search: requires sorted array, O(log n), compare mid then halve search space", "general"),
            ("[Algorithms] Asked about sorting stability: What does it mean for a sort to be stable?", "general"),
        ],
    ),
    WeekData(
        week=12,
        title="時間複雜度分析",
        facts=[
            ("[Algorithms] Big-O rules: drop constants, keep dominant term, nested loops multiply", "general"),
            ("[Algorithms] Common complexities: O(1) hash lookup, O(log n) binary search, O(n) linear scan, O(n²) nested loops", "general"),
            ("Struggling with complexity analysis: can identify O(n) but struggles with O(n log n) and amortized analysis", "struggling"),
        ],
    ),
    # --- Weeks 13-15: Practical Skills ---
    WeekData(
        week=13,
        title="檔案處理與例外",
        facts=[
            ("[Python] File I/O: open() with context manager (with), read/write modes, encoding='utf-8'", "general"),
            ("[Python] Exception handling: try/except/else/finally, raise for custom errors, exception hierarchy", "general"),
            ("[Python] Asked about file encoding: Why do I get UnicodeDecodeError when reading files?", "general"),
        ],
    ),
    WeekData(
        week=14,
        title="模組與套件管理",
        facts=[
            ("[Python] Module system: import, from...import, __name__=='__main__', package __init__.py", "general"),
            ("[Python] Virtual environments: venv/uv for isolation, requirements.txt/pyproject.toml for deps", "general"),
            ("Learning preference update: now comfortable reading English documentation directly", "preference"),
        ],
    ),
    WeekData(
        week=15,
        title="單元測試",
        facts=[
            ("[Testing] Pytest basics: test_ prefix, assert statements, fixtures for setup/teardown", "general"),
            ("[Testing] Test patterns: arrange-act-assert, parametrize for multiple cases, mock for isolation", "general"),
            ("[Testing] Asked about test coverage: How much test coverage is enough for a project?", "general"),
        ],
    ),
    # --- Weeks 16-18: Final Project & Review ---
    WeekData(
        week=16,
        title="期末專題：設計階段",
        facts=[
            ("[Project] Architecture planning: MVC pattern, separate data/logic/presentation layers", "general"),
            ("[Project] Asked about project structure: How should I organize a Python project with multiple modules?", "general"),
            ("[Project] Database choice: SQLite for simplicity, considered PostgreSQL but chose simpler option", "general"),
        ],
    ),
    WeekData(
        week=17,
        title="期末專題：實作階段",
        facts=[
            ("[Project] Debugging session: learned to use pdb, breakpoint(), and VS Code debugger", "general"),
            ("[Project] Git workflow: learned branching, commit messages, resolved first merge conflict", "general"),
            ("[Project] Asked about code review: What should I look for when reviewing my own code?", "general"),
        ],
    ),
    WeekData(
        week=18,
        title="期末回顧與反思",
        facts=[
            ("[Review] Semester reflection: strongest in data structures and file I/O, weakest in recursion", "general"),
            ("[Review] Growth areas: overcame loop termination issues, improved from needing Chinese to reading English docs", "general"),
            ("Learning preference for debugging: values step-by-step debugging walkthroughs for complex problems", "preference"),
        ],
    ),
]
