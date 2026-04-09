"""Demo student data for seeding the EduInsight database.

Shared between the seed script (scripts/seed_demo.py) and the
/demo/reset API endpoint.

Each fact is a (text, category) tuple. The text is designed so that
each fact has a unique prefix (text before the first colon) to avoid
Lite-Mem's prefix-based deduplication within the same user+category.

Format rules (to work with analytics regex patterns):
- Q&A facts: "[Topic] Unique description: details"
  → _TOPIC_RE extracts topic from [brackets]
  → prefix before ':' is unique per fact
- Struggles: "Struggling with SPECIFIC_TOPIC: details"
  → _STRUGGLE_RE extracts topic and details
  → prefix includes the specific topic (unique per struggle)
- Preferences: "Learning preference: description"
  → _PREFERENCE_RE extracts the preference text
  → one per student, so no dedup collision
"""

from __future__ import annotations

# (fact_text, category)
DemoFact = tuple[str, str]

DEMO_STUDENTS: dict[str, list[DemoFact]] = {
    # Student 1001 - struggling with data structures, many questions
    "moodle:1001": [
        ("[Data Structures] Linked list fundamentals: stores elements in nodes connected by pointers, arrays use contiguous memory, O(1) insertion at known positions but O(n) access", "general"),
        ("[Data Structures] Reversing a linked list: use three pointers (prev, curr, next), iterate through reversing each pointer direction, prev starts as null", "general"),
        ("[Data Structures] Stack vs queue use cases: Stack (LIFO) for undo/function calls/parsing, Queue (FIFO) for scheduling/BFS/buffering", "general"),
        ("[Data Structures] Hash table collision handling: chaining (linked lists at buckets) and open addressing (linear probing, quadratic probing, double hashing)", "general"),
        ("[Data Structures] Asked about linked lists: What is a linked list and how is it different from an array?", "general"),
        ("[Data Structures] Asked about reversing: How do I reverse a linked list step by step?", "general"),
        ("[Data Structures] Asked about stacks and queues: When should I use a stack versus a queue?", "general"),
        ("[Data Structures] Asked about hash collisions: How does a hash table handle collisions?", "general"),
        ("Struggling with linked list pointer manipulation: often confused by next pointer reassignment during insertion and deletion", "struggling"),
        ("Struggling with binary tree traversal: can't distinguish between inorder, preorder, and postorder traversal", "struggling"),
        ("Struggling with time complexity analysis: knows O(n) notation but unsure about amortized analysis", "struggling"),
        ("Learning preference: prefers visual diagrams and step-by-step walkthroughs", "preference"),
    ],
    # Student 1002 - advanced student, algorithm-focused
    "moodle:1002": [
        ("[Algorithms] DP vs divide-and-conquer: both break problems into subproblems, DP stores overlapping solutions via memoization, D&C subproblems are independent", "general"),
        ("[Algorithms] Bellman-Ford shortest path: relaxes all edges V-1 times, handles negative weights unlike Dijkstra, O(VE) time, detects negative cycles", "general"),
        ("[Algorithms] Complexity classes overview: P = poly-time solvable, NP = poly-time verifiable, NP-complete = hardest in NP, P vs NP is open", "general"),
        ("[Algorithms] Greedy algorithm design: prove greedy choice property and optimal substructure, examples include Huffman coding, Kruskal MST, activity selection", "general"),
        ("[Algorithms] Amortized analysis concepts: averages cost over sequence, dynamic array doubling is O(n) per push worst-case but O(1) amortized", "general"),
        ("[Algorithms] Asked about dynamic programming: How does dynamic programming differ from divide and conquer?", "general"),
        ("[Algorithms] Asked about shortest paths: Can you explain the Bellman-Ford algorithm?", "general"),
        ("[Algorithms] Asked about complexity theory: What's the difference between P, NP, and NP-complete?", "general"),
        ("[Algorithms] Asked about greedy approach: How do I approach greedy algorithm design problems?", "general"),
        ("[Algorithms] Asked about amortized analysis: Explain amortized analysis with a concrete example", "general"),
        ("Learning preference: prefers formal proofs and complexity analysis over intuitive explanations", "preference"),
    ],
    # Student 1003 - beginner, basic programming concepts
    "moodle:1003": [
        ("[Python Programming] Lists vs tuples: lists are mutable (can change), tuples are immutable, use tuples for fixed data like coordinates", "general"),
        ("[Python Programming] For loop patterns: for iterates over iterables (list, string, range), range(5) gives 0-4, for item in list gives each element", "general"),
        ("[Python Programming] F-string formatting: f-strings (Python 3.6+) embed expressions in strings like f\"Hello {name}\", support format specs like f\"{price:.2f}\"", "general"),
        ("[Python Programming] Exception handling: use try/except blocks, catch specific exceptions like TypeError, avoid bare except clauses", "general"),
        ("[Python Programming] Asked about data types: What's the difference between a list and a tuple in Python?", "general"),
        ("[Python Programming] Asked about loops: How do for loops work in Python?", "general"),
        ("[Python Programming] Asked about string formatting: What are f-strings and how do I use them?", "general"),
        ("[Python Programming] Asked about error handling: How do I handle errors in Python?", "general"),
        ("Struggling with variable scope: confused why a variable defined inside a function isn't accessible outside", "struggling"),
        ("Struggling with debugging techniques: doesn't know how to read Python tracebacks or use print debugging effectively", "struggling"),
        ("Learning preference: learns best from simple code examples with inline comments", "preference"),
    ],
    # Student 1004 - database and SQL focus
    "moodle:1004": [
        ("[Database Systems] Normalization theory: 1NF atomic values, 2NF no partial deps, 3NF no transitive deps, BCNF every determinant is candidate key", "general"),
        ("[Database Systems] Indexing guidelines: index columns in WHERE/JOIN/ORDER BY, avoid for small tables, low cardinality columns, or heavy-write tables", "general"),
        ("[Database Systems] ACID transaction properties: Atomicity (all-or-nothing), Consistency (valid states), Isolation (no interference), Durability (survives crashes)", "general"),
        ("[Database Systems] SQL vs NoSQL paradigms: SQL is relational with schema and ACID, NoSQL is flexible with horizontal scaling and eventual consistency", "general"),
        ("[Database Systems] Asked about normalization: What is database normalization and what are the normal forms?", "general"),
        ("[Database Systems] Asked about indexing: When should I create a database index and when should I avoid it?", "general"),
        ("[Database Systems] Asked about transactions: Explain the ACID properties of database transactions", "general"),
        ("[Database Systems] Asked about database types: What is the difference between SQL and NoSQL databases?", "general"),
        ("Struggling with JOIN queries: especially confused by LEFT JOIN vs INNER JOIN behavior with NULL values", "struggling"),
        ("Struggling with query optimization: understands EXPLAIN output but can't interpret execution plans effectively", "struggling"),
        ("Learning preference: prefers real-world examples connecting theory to practical database design", "preference"),
    ],
}
