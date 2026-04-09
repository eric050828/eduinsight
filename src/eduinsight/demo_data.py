"""Demo student data for seeding the EduInsight database.

Shared between the seed script (scripts/seed_demo.py) and the
/demo/reset API endpoint.
"""

from __future__ import annotations

DEMO_STUDENTS: dict[str, list[str]] = {
    # Student 1001 - struggling with data structures, many questions
    "moodle:1001": [
        "[Data Structures] Q: What is a linked list and how is it different from an array?",
        "[Data Structures] A: A linked list stores elements in nodes connected by pointers, while arrays use contiguous memory. Linked lists allow O(1) insertion/deletion at known positions but O(n) access.",
        "Struggling with: linked list pointer manipulation — often confused by next pointer reassignment during insertion",
        "[Data Structures] Q: How do I reverse a linked list?",
        "[Data Structures] A: Use three pointers (prev, curr, next). Iterate through the list, reversing each pointer direction. prev starts as null, curr starts at head.",
        "Struggling with: binary tree traversal — can't distinguish between inorder, preorder, and postorder",
        "[Data Structures] Q: When should I use a stack vs a queue?",
        "[Data Structures] A: Stack (LIFO) for undo operations, function calls, expression parsing. Queue (FIFO) for scheduling, BFS, buffering.",
        "Learning preference: prefers visual diagrams and step-by-step walkthroughs",
        "[Data Structures] Q: How does a hash table handle collisions?",
        "[Data Structures] A: Common methods: chaining (linked lists at each bucket) and open addressing (linear probing, quadratic probing, double hashing).",
        "Struggling with: time complexity analysis — knows O(n) but unsure about amortized analysis",
    ],
    # Student 1002 - advanced student, algorithm-focused
    "moodle:1002": [
        "[Algorithms] Q: How does dynamic programming differ from divide and conquer?",
        "[Algorithms] A: Both break problems into subproblems. DP stores solutions to overlapping subproblems (memoization/tabulation). D&C subproblems are independent (merge sort, quicksort).",
        "[Algorithms] Q: Can you explain the Bellman-Ford algorithm?",
        "[Algorithms] A: Relaxes all edges V-1 times to find shortest paths. Unlike Dijkstra, handles negative weights. O(VE) time. Can detect negative cycles with one more iteration.",
        "Learning preference: prefers formal proofs and complexity analysis over intuitive explanations",
        "[Algorithms] Q: What's the difference between P, NP, and NP-complete?",
        "[Algorithms] A: P = solvable in polynomial time. NP = verifiable in polynomial time. NP-complete = hardest problems in NP (all NP problems reduce to them). P vs NP is open.",
        "[Algorithms] Q: How do I approach greedy algorithm problems?",
        "[Algorithms] A: 1) Prove greedy choice property (local optimum leads to global). 2) Prove optimal substructure. Classic examples: Huffman coding, Kruskal's MST, activity selection.",
        "[Algorithms] Q: Explain amortized analysis with an example",
        "[Algorithms] A: Amortized analysis averages cost over a sequence. Example: dynamic array doubling — individual push can be O(n) but amortized O(1) because doubling happens rarely.",
    ],
    # Student 1003 - beginner, basic programming concepts
    "moodle:1003": [
        "[Python Programming] Q: What's the difference between a list and a tuple?",
        "[Python Programming] A: Lists are mutable (can change after creation), tuples are immutable. Use tuples for fixed data like coordinates, lists for collections that change.",
        "Struggling with: understanding variable scope — confused why a variable inside a function isn't accessible outside",
        "[Python Programming] Q: How do for loops work in Python?",
        "[Python Programming] A: for iterates over any iterable (list, string, range). 'for i in range(5)' loops 0-4. 'for item in my_list' gives each element directly.",
        "[Python Programming] Q: What are f-strings?",
        '[Python Programming] A: Formatted string literals (Python 3.6+). Write f"Hello {name}" to embed expressions directly in strings. Supports format specs like f"{price:.2f}".',
        "Learning preference: learns best from simple code examples with comments",
        "Struggling with: debugging — doesn't know how to read tracebacks effectively",
        "[Python Programming] Q: How do I handle errors in Python?",
        "[Python Programming] A: Use try/except blocks. try: risky code, except TypeError as e: handle it. Always catch specific exceptions, not bare except.",
    ],
    # Student 1004 - database and SQL focus
    "moodle:1004": [
        "[Database Systems] Q: What is database normalization?",
        "[Database Systems] A: Organizing tables to reduce redundancy. 1NF: atomic values. 2NF: no partial dependencies. 3NF: no transitive dependencies. BCNF: every determinant is a candidate key.",
        "[Database Systems] Q: When should I use an index?",
        "[Database Systems] A: Index columns used in WHERE, JOIN, ORDER BY frequently. Avoid indexing: small tables, columns with low cardinality, tables with heavy writes. B-tree is default in most RDBMS.",
        "Struggling with: writing complex JOIN queries — especially LEFT JOIN vs INNER JOIN confusion",
        "[Database Systems] Q: Explain ACID properties",
        "[Database Systems] A: Atomicity (all or nothing), Consistency (valid state transitions), Isolation (concurrent transactions don't interfere), Durability (committed data persists through crashes).",
        "[Database Systems] Q: What is the difference between SQL and NoSQL?",
        "[Database Systems] A: SQL: relational, schema-enforced, ACID, good for structured data. NoSQL: flexible schema, horizontal scaling, eventual consistency. Choose based on data model and scale needs.",
        "Learning preference: prefers real-world examples connecting theory to practical database design",
        "Struggling with: query optimization — understands EXPLAIN but can't interpret execution plans well",
    ],
}
