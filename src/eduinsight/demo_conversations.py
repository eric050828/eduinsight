"""Demo conversation data for seeding the messages table.

Each entry is (session_id, [(role, content), ...]).
These populate the /student/{id}/conversations endpoint so the
student dashboard shows realistic chat history during demos.
"""

from __future__ import annotations

# (session_id, [(role, content), ...])
DemoConversation = tuple[str, list[tuple[str, str]]]

DEMO_CONVERSATIONS: dict[str, list[DemoConversation]] = {
    "moodle:1001": [
        ("demo-1001-s1", [
            ("user", "linked list 跟 array 有什麼不同？"),
            ("assistant", "Linked list 和 array 的主要差異在於記憶體配置方式：\n\n"
             "- **Array**：使用連續記憶體，支援 O(1) 隨機存取，但插入/刪除需要搬移元素\n"
             "- **Linked List**：每個節點存資料和指向下一個節點的指標，插入/刪除是 O(1)（已知位置時），但存取是 O(n)\n\n"
             "簡單來說，如果你需要頻繁存取特定位置的資料，用 array；如果需要頻繁插入刪除，用 linked list。"),
        ]),
        ("demo-1001-s2", [
            ("user", "怎麼反轉一個 linked list？我一直搞不懂指標操作"),
            ("assistant", "反轉 linked list 的核心是用三個指標：`prev`、`curr`、`next`\n\n```python\ndef reverse(head):\n    prev = None\n    curr = head\n    while curr:\n        next_node = curr.next  # 先存下一個\n        curr.next = prev       # 反轉指向\n        prev = curr            # prev 前進\n        curr = next_node       # curr 前進\n    return prev\n```\n\n"
             "關鍵是：每一步都先把 `curr.next` 存起來，不然反轉後就找不到下一個節點了。建議你畫圖跟著走一遍！"),
            ("user", "原來要先存 next！我之前一直忘記這步驟"),
            ("assistant", "對！這是最常見的錯誤。你可以記口訣：「存、轉、移、移」\n1. **存**：存下一個節點\n2. **轉**：反轉 curr 指向\n3. **移**：prev 前進\n4. **移**：curr 前進\n\n多練幾次就會變成直覺了 💪"),
        ]),
    ],
    "moodle:1002": [
        ("demo-1002-s1", [
            ("user", "DP 和 divide and conquer 的差別是什麼？"),
            ("assistant", "兩者都是把大問題拆成子問題，關鍵差異在於**子問題是否重疊**：\n\n"
             "- **Divide & Conquer**：子問題互相獨立（如 Merge Sort），直接遞迴解決\n"
             "- **Dynamic Programming**：子問題重疊（如 Fibonacci），用 memoization 或 tabulation 避免重複計算\n\n"
             "判斷標準：如果你發現遞迴解法中同一個子問題被算了很多次 → 用 DP。"),
        ]),
        ("demo-1002-s2", [
            ("user", "Bellman-Ford 的時間複雜度為什麼是 O(VE)？"),
            ("assistant", "Bellman-Ford 的做法是：\n1. 對所有邊做 relaxation（更新最短距離）\n2. 重複 V-1 次\n\n"
             "每次 relaxation 遍歷所有 E 條邊，做 V-1 輪，所以是 O((V-1) × E) = O(VE)\n\n"
             "為什麼要 V-1 輪？因為最短路徑最多經過 V-1 條邊（不含負環時）。每輪至少確定一個頂點的最短距離。\n\n"
             "附帶一提：第 V 輪如果還能 relax，代表存在負環。這就是 Bellman-Ford 能偵測負環的原理。"),
        ]),
    ],
    "moodle:1003": [
        ("demo-1003-s1", [
            ("user", "list 和 tuple 到底差在哪裡？什麼時候該用哪個？"),
            ("assistant", "最大的差異是 **可變性**：\n\n"
             "- `list`：可變（mutable），可以增刪改元素\n"
             "- `tuple`：不可變（immutable），建立後不能修改\n\n"
             "```python\nmy_list = [1, 2, 3]\nmy_list[0] = 99  # OK\n\nmy_tuple = (1, 2, 3)\nmy_tuple[0] = 99  # TypeError!\n```\n\n"
             "**使用時機**：\n- 資料會變動 → `list`（如購物車）\n- 資料固定不變 → `tuple`（如座標 (x, y)、RGB 色碼）\n- tuple 也可以當 dict 的 key，list 不行"),
            ("user", "為什麼 tuple 可以當 key 但 list 不行？"),
            ("assistant", "因為 dict 的 key 必須是 **hashable**（可雜湊的），而 hashable 的前提是不可變。\n\n"
             "tuple 不可變 → 可以計算固定的 hash 值 → 可以當 key\n"
             "list 可變 → hash 值可能改變 → 不能當 key\n\n"
             "這是 Python 設計上的安全考量，防止 key 被意外修改導致找不到對應的 value。"),
        ]),
    ],
    "moodle:1004": [
        ("demo-1004-s1", [
            ("user", "LEFT JOIN 和 INNER JOIN 差在哪裡？我 NULL 值一直搞混"),
            ("assistant", "核心差異在於**不匹配時的行為**：\n\n"
             "- **INNER JOIN**：只回傳兩邊都有匹配的列\n"
             "- **LEFT JOIN**：左表全部保留，右表不匹配的填 NULL\n\n"
             "```sql\n-- 假設 students 有 3 人，grades 只有 2 筆\n\n-- INNER JOIN: 只回傳有成績的 2 人\n"
             "SELECT s.name, g.score\nFROM students s\nINNER JOIN grades g ON s.id = g.student_id;\n\n"
             "-- LEFT JOIN: 3 人都出現，沒成績的 score = NULL\n"
             "SELECT s.name, g.score\nFROM students s\nLEFT JOIN grades g ON s.id = g.student_id;\n```\n\n"
             "記住：LEFT JOIN = 「左表一定全部出現」"),
        ]),
    ],
}
