"""Seed EduInsight with rich 10-week demo data.

Creates realistic learning memories for 5 students across 4 courses,
simulating 10 weeks of AI assistant usage. Facts are backdated to
appropriate weeks using direct DB updates.

Usage:
    uv run python scripts/seed_rich_demo.py [--db eduinsight.db]
"""
import sqlite3
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from litemem import Memory

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "eduinsight.db"

# ── Time helpers ──
NOW = time.time()
WEEK_SECS = 7 * 24 * 3600

def week_ts(weeks_ago: int, offset_hours: float = 0) -> float:
    """Timestamp for N weeks ago + offset hours."""
    return NOW - (weeks_ago * WEEK_SECS) + (offset_hours * 3600)


# ══════════════════════════════════════════════════════════════
# DEMO STUDENTS AND THEIR 10-WEEK LEARNING JOURNEY
# ══════════════════════════════════════════════════════════════

# Format: (user_id, fact_text, category, weeks_ago, offset_hours)
# Categories: general, struggling, preference

SEED_DATA: list[tuple[str, str, str, int, float]] = []

# NOTE: Each fact_text MUST be unique enough to survive Lite-Mem dedup.
# Use specific details, timestamps, context to make each distinct.

# ────────────────────────────────────────
# A 陳同學 (moodle:1001) — 認真但基礎弱
# 修：資料結構(王)、Python(王)、資料庫(張)
# 期中考：DS B-(68)、Python B+(82)、DB C+(70)
# ────────────────────────────────────────
A = "moodle:1001"

# Week 1: 初次使用
SEED_DATA += [
    (A, "[W1-DS] Q: linked list 和 array 記憶體配置差別", "general", 10, 1),
    (A, "[W1-DS] Q: 為什麼需要學資料結構，array 不夠用嗎", "general", 10, 2),
    (A, "[W1] Preference: 偏好視覺圖解和 step-by-step 流程說明", "preference", 10, 3),
    (A, "[W1-Py] Q: Python list 和 tuple 的差異與使用場景", "general", 10, 5),
    (A, "[W1-DB] Q: SQL SELECT 基本語法和 WHERE 過濾", "general", 10, 8),
]

# Week 3: 開始遇到困難
SEED_DATA += [
    (A, "[W3-DS] Q: linked list 插入節點時 next pointer 重新指向的順序", "general", 8, 1),
    (A, "[W3-DS] Struggle: linked list 插入操作 pointer 重接順序混淆", "struggling", 8, 2),
    (A, "[W3-Py] Q: for 迴圈 vs while 迴圈適用場景比較", "general", 8, 10),
    (A, "[W3-DB] Q: primary key 與 foreign key 的關聯與用途", "general", 8, 15),
]

# Week 5: pointer 問題持續
SEED_DATA += [
    (A, "[W5-DS] Q: linked list 刪除節點的 pointer 處理（插入已懂但刪除搞混）", "general", 6, 1),
    (A, "[W5-DS] Struggle: 刪除 linked list 節點時忘記先保存 next pointer", "struggling", 6, 2),
    (A, "[W5-DS] Q: Stack(LIFO) 與 Queue(FIFO) 的區別和應用場景", "general", 6, 5),
    (A, "[W5-DS] Observation: pointer 操作已連續 3 次提問，建議加強練習", "general", 6, 6),
    (A, "[W5-Py] Q: Python def 函式定義語法和參數傳遞", "general", 6, 12),
    (A, "[W5-DB] Q: 什麼是 normalization（正規化）以及拆表的理由", "general", 6, 18),
]

# Week 7: 開始問 tree
SEED_DATA += [
    (A, "[W7-DS] Q: binary tree 的定義以及和一般 tree 的差異", "general", 4, 1),
    (A, "[W7-DS] Q: hash table 碰撞處理方法 chaining 的原理", "general", 4, 3),
    (A, "[W7-DS] Struggle: hash table 理解 chaining 但無法實作 open addressing", "struggling", 4, 4),
    (A, "[W7-Py] Q: Python variable scope 問題（function 內外變數不共享）", "general", 4, 8),
    (A, "[W7-Py] Struggle: local vs global scope 區分困難", "struggling", 4, 9),
    (A, "[W7-DB] Q: LEFT JOIN 和 INNER JOIN 差異（要求圖解）", "general", 4, 14),
    (A, "[W7-DB] Struggle: SQL JOIN 類型選擇困難，LEFT/INNER 混淆", "struggling", 4, 15),
]

# Week 8: tree 困難出現
SEED_DATA += [
    (A, "[W8-DS] Q: binary tree inorder traversal 的走訪順序（課本看不懂）", "general", 3, 1),
    (A, "[W8-DS] Struggle: 無法區分 inorder/preorder/postorder traversal 的視覺差異", "struggling", 3, 2),
    (A, "[W8-DS] Q: amortized analysis 和一般 time complexity 的概念差異", "general", 3, 8),
    (A, "[W8-DS] Struggle: 理解 O(n) 但無法掌握均攤分析的概念", "struggling", 3, 9),
]

# Week 9: 期中考前衝刺 (大量提問)
SEED_DATA += [
    (A, "[W9-DS] Q: linked list 反轉的三指標法（prev/curr/next）步驟", "general", 2, 1),
    (A, "[W9-DS] Q: binary tree 三種 traversal 的記憶口訣", "general", 2, 2),
    (A, "[W9-DS] Q: hash table load factor 定義和 rehash 觸發條件", "general", 2, 3),
    (A, "[W9-DS] Q: 用 Stack 做 expression evaluation 的步驟", "general", 2, 4),
    (A, "[W9-DS] Q: BFS vs DFS 的差別和適用場景", "general", 2, 6),
    (A, "[W9] Alert: 考前衝刺模式——2天內問了8個問題（平時每週2-3個）", "general", 2, 7),
    (A, "[W9-Py] Q: f-string 內嵌表達式和三元運算", "general", 2, 10),
    (A, "[W9-DB] Q: GROUP BY 搭配 HAVING 的使用時機", "general", 2, 14),
    (A, "[W9-DB] Q: ACID 四字母含義，特別是 Isolation 的概念", "general", 2, 16),
]

# Week 10: 期中考後
SEED_DATA += [
    (A, "[W10-DS] Q: 期中考 inorder traversal 寫錯，重新確認 left-root-right 順序", "general", 1, 1),
    (A, "[W10-DS] Q: 均攤分析考題完全不會，要求重新教學", "general", 1, 3),
    (A, "[W10] Midterm: 資料結構 B-(68)，tree traversal 和 amortized analysis 失分最多", "general", 1, 5),
    (A, "[W10] Midterm: Python B+(82)，scope 錯一題其餘正確", "general", 1, 6),
    (A, "[W10] Midterm: 資料庫 C+(70)，JOIN 大題幾乎全錯", "general", 1, 7),
]


# ────────────────────────────────────────
# B 林同學 (moodle:1002) — 進階生
# 修：資料結構(王)、資料庫(張)
# 期中考：DS A(92)、DB A-(87)
# ────────────────────────────────────────
B = "moodle:1002"

SEED_DATA += [
    (B, "[W1] Preference: 偏好正式數學證明和複雜度分析，不要直覺式解釋", "preference", 10, 1),
    (B, "[W2-DS] Q: dynamic programming 與 divide and conquer 的本質差異（overlapping subproblems）", "general", 9, 1),
    (B, "[W3-DS] Q: hash table worst case O(n) 的成因，perfect hashing 可行性", "general", 8, 1),
    (B, "[W4-DS] Q: AVL tree vs Red-Black tree 旋轉次數和適用場景比較", "general", 7, 1),
    (B, "[W4-DB] Q: B+ Tree indexing 優勢（range query）和 B Tree 的結構差異", "general", 7, 8),
    (B, "[W5-DB] Q: CAP theorem 在 MongoDB/Cassandra/PostgreSQL 的取捨", "general", 6, 1),
    (B, "[W6-DS] Q: amortized analysis potential method 完整數學推導", "general", 5, 1),
    (B, "[W7-DS] Q: Dijkstra vs Bellman-Ford 適用條件，negative weight edge 處理", "general", 4, 1),
    (B, "[W8-DS] Q: NP-Complete 定義和 polynomial reduction 證明方法", "general", 3, 1),
    (B, "[W9-DB] Q: PostgreSQL MVCC 實現 Isolation 的機制，和 2PL 的效能比較", "general", 2, 1),
    (B, "[W9-DB] Q: consistent hashing 在分散式資料庫 sharding 的應用", "general", 2, 5),
    (B, "[W10] Midterm: 資料結構 A(92)，graph shortest path 證明題小失分", "general", 1, 1),
    (B, "[W10] Midterm: 資料庫 A-(87)，query optimization 回答不夠完整", "general", 1, 2),
    (B, "[W10-DB] Struggle: EXPLAIN 能執行但複雜 query plan 解讀不夠精確", "struggling", 1, 3),
]


# ────────────────────────────────────────
# C 王同學 (moodle:1003) — 重修 Python，態度消極
# 修：Python(王, 重修)、資料庫(張)
# 期中考：Python D(45)、DB D+(52)
# ────────────────────────────────────────
C = "moodle:1003"

SEED_DATA += [
    (C, "[W1] Preference: 需要非常基礎的解釋，容易感到挫折放棄", "preference", 10, 1),
    (C, "[W1-Py] Background: 去年修 Python 被當(F)，本學期重修", "general", 10, 2),
    (C, "[W1-Py] Q: 什麼是 variable（變數），為什麼需要命名", "general", 10, 3),
    (C, "[W2-Py] Q: print() 輸出和 return 回傳值的差異", "general", 9, 1),
    (C, "[W2-Py] Struggle: 無法區分 print() 和 return 的用途", "struggling", 9, 2),
    (C, "[W3-Py] Q: for 迴圈執行結果與預期不同，請幫忙找 bug", "general", 8, 1),
    (C, "[W3-Py] Struggle: 不會閱讀 Python traceback 錯誤訊息", "struggling", 8, 2),
    (C, "[W4-Py] Q: list 新增元素 append vs insert 差異", "general", 7, 1),
    (C, "[W4-DB] Q: SQL WHERE 子句的條件寫法", "general", 7, 8),
    (C, "[W4-DB] Struggle: SQL 基本語法混淆（WHERE 條件寫成欄位名稱）", "struggling", 7, 9),
    (C, "[W5-Py] Q: function 參數(parameter)的含義和傳入方式", "general", 6, 1),
    (C, "[W5-Py] Struggle: 混淆 argument 和 parameter 的概念", "struggling", 6, 2),
    (C, "[W6-Py] Q: 巢狀迴圈看不懂，要求最簡化解釋", "general", 5, 1),
    (C, "[W6-Py] Struggle: 巢狀迴圈——解釋稍微複雜就放棄", "struggling", 5, 2),
    (C, "[W7-Py] Alert: 使用頻率從每週3次降至每週1次", "general", 4, 1),
    (C, "[W7-Py] Q: dictionary 資料結構和 list 的差異", "general", 4, 5),
    (C, "[W9-Py] Q: 期中考考試範圍確認（自述很多都不會）", "general", 2, 1),
    (C, "[W9-Py] Q: try/except 例外處理語法和使用時機", "general", 2, 5),
    (C, "[W10] Midterm: Python D(45)，基礎語法錯誤多，function 全錯", "general", 1, 1),
    (C, "[W10] Midterm: 資料庫 D+(52)，SQL 不完整，JOIN 全跳過", "general", 1, 2),
    (C, "[W10] Alert: 第10週 AI 互動驟降80%，僅登入1次未提問", "general", 1, 3),
]


# ────────────────────────────────────────
# D 李同學 (moodle:1004) — 期中考後消失
# 修：資料結構(王)
# 期中考：DS F(23)
# ────────────────────────────────────────
D = "moodle:1004"

SEED_DATA += [
    (D, "[W1-DS] Q: 什麼是 stack，生活中有哪些例子", "general", 10, 1),
    (D, "[W1] Preference: 需要簡單的生活類比來理解抽象概念", "preference", 10, 2),
    (D, "[W2-DS] Q: array index 為什麼從 0 開始而不是 1", "general", 9, 1),
    (D, "[W3-DS] Q: linked list 為什麼需要 pointer，array 不夠用嗎", "general", 8, 1),
    (D, "[W3-DS] Struggle: 基礎概念薄弱，無法理解為什麼需要 array 以外的資料結構", "struggling", 8, 2),
    (D, "[W4-DS] Q: queue 跟 stack 差在哪（LIFO/FIFO 搞混）", "general", 7, 1),
    (D, "[W4-DS] Struggle: 多次解釋後仍混淆 LIFO 和 FIFO", "struggling", 7, 2),
    (D, "[W5-DS] Q: Big-O 表示法的意義，O(n) 代表什麼", "general", 6, 1),
    (D, "[W5-DS] Struggle: 基礎概念進步極其緩慢，跨 session 幾乎無改善", "struggling", 6, 2),
    (D, "[W6-DS] Alert: 學習理解度持續偏低，建議尋求額外輔導", "general", 5, 1),
    (D, "[W7-DS] Q: 作業 linked list 題目完全不會寫，求救", "general", 4, 1),
    (D, "[W8-DS] Alert: 已連續 2 週未使用 AI 助教", "general", 3, 1),
    (D, "[W9-DS] Q: 期中考怎麼準備（自述什麼都不會）", "general", 2, 1),
    (D, "[W10] Midterm: 資料結構 F(23)，大部分空白或答非所問", "general", 1, 1),
    (D, "[W10] ⚠️ CRITICAL: 第10週完全零互動，最後登入為考前1天，高度疑似考慮二退", "general", 1, 2),
]


# ────────────────────────────────────────
# E 張同學 (moodle:1005) — 中等偏實作
# 修：資料庫(張)
# 期中考：DB C+(70)
# ────────────────────────────────────────
E = "moodle:1005"

SEED_DATA += [
    (E, "[W1] Preference: 偏好動手實作而非理論，喜歡用真實資料庫案例學習", "preference", 10, 1),
    (E, "[W1-DB] Q: CREATE TABLE 建立學生資料表的完整語法", "general", 10, 3),
    (E, "[W2-DB] Q: INSERT INTO 語法和批次插入多筆資料的方法", "general", 9, 1),
    (E, "[W3-DB] Q: SELECT WHERE 搭配 AND/OR 的優先順序", "general", 8, 1),
    (E, "[W4-DB] Q: index 的建立時機和過度索引的副作用", "general", 7, 1),
    (E, "[W4-DB] Struggle: 知道 index 定義但不確定什麼場景該建", "struggling", 7, 2),
    (E, "[W5-DB] Q: ACID Isolation 的含義（要求用銀行轉帳案例說明）", "general", 6, 1),
    (E, "[W6-DB] Q: 三表 JOIN 的寫法和 join 順序是否影響結果", "general", 5, 1),
    (E, "[W6-DB] Struggle: multi-table JOIN 的 join 順序和 alias 命名困惑", "struggling", 5, 2),
    (E, "[W7-DB] Q: GROUP BY + HAVING 和 WHERE 的過濾時機差異", "general", 4, 1),
    (E, "[W8-DB] Q: subquery vs JOIN 效能比較和適用場景", "general", 3, 1),
    (E, "[W8-DB] Q: EXPLAIN 輸出解讀，Seq Scan 的含義", "general", 3, 5),
    (E, "[W8-DB] Struggle: 會執行 EXPLAIN 但無法解讀複雜 execution plan", "struggling", 3, 6),
    (E, "[W9-DB] Q: 1NF/2NF/3NF 正規化差異和拆表判斷標準", "general", 2, 1),
    (E, "[W9-DB] Q: 實務專案是否真的做到 3NF（denormalization 時機）", "general", 2, 3),
    (E, "[W10] Midterm: 資料庫 C+(70)，SQL 實作題佳，正規化理論弱", "general", 1, 1),
    (E, "[W10-DB] Q: 期中考 normalization 理論題記不住，求記憶方法", "general", 1, 3),
]


def main():
    print(f"Seeding rich demo data to: {DB_PATH}")

    # Create fresh DB
    import os
    for suffix in ("", "-wal", "-shm"):
        p = DB_PATH + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except PermissionError:
                pass

    mem = Memory(DB_PATH)

    # Insert all facts
    for user_id, text, category, weeks_ago, offset_hours in SEED_DATA:
        mem.add(user_id, text, category=category, extract=False)

    # Close litemem to release DB lock
    del mem

    # Backdate timestamps
    conn = sqlite3.connect(DB_PATH)
    for user_id, text, category, weeks_ago, offset_hours in SEED_DATA:
        ts = week_ts(weeks_ago, offset_hours)
        conn.execute(
            "UPDATE facts SET created_at=?, updated_at=? WHERE user_id=? AND fact_text=?",
            (ts, ts, user_id, text)
        )
    conn.commit()

    # Verify
    counts = conn.execute(
        "SELECT user_id, COUNT(*) FROM facts GROUP BY user_id ORDER BY user_id"
    ).fetchall()
    total = sum(c for _, c in counts)
    print(f"\nSeeded {total} facts for {len(counts)} students:")
    names = {"moodle:1001": "A 陳同學", "moodle:1002": "B 林同學", "moodle:1003": "C 王同學(重修)",
             "moodle:1004": "D 李同學", "moodle:1005": "E 張同學"}
    for uid, count in counts:
        print(f"  {names.get(uid, uid)}: {count} facts")

    # Show date range
    for uid, _ in counts:
        oldest = conn.execute("SELECT MIN(created_at) FROM facts WHERE user_id=?", (uid,)).fetchone()[0]
        newest = conn.execute("SELECT MAX(created_at) FROM facts WHERE user_id=?", (uid,)).fetchone()[0]
        import datetime
        o = datetime.datetime.fromtimestamp(oldest).strftime("%m/%d")
        n = datetime.datetime.fromtimestamp(newest).strftime("%m/%d")
        print(f"    {names.get(uid, uid)}: {o} → {n}")

    conn.close()
    print(f"\n✅ Done! DB: {DB_PATH}")


if __name__ == "__main__":
    main()
