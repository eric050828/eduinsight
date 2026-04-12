"""Seed realistic conversation history into EduInsight demo DB.

Inserts past Q&A conversations into Lite-Mem's messages table,
simulating 10 weeks of student-AI interactions.

Usage:
    uv run python scripts/seed_conversations.py [--db eduinsight_demo.db]
"""
import sqlite3
import sys
import time

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "eduinsight_demo.db"
NOW = time.time()
WEEK = 7 * 24 * 3600

def ts(weeks_ago, hours=0):
    return NOW - weeks_ago * WEEK + hours * 3600

# (user_id, session_id, role, content, weeks_ago, hours_offset)
CONVOS: list[tuple[str, str, str, str, int, float]] = []

def add_qa(user_id, q, a, weeks_ago, hour=0):
    """Add a Q&A pair with the same session."""
    sid = f"s-{user_id}-w{weeks_ago}-{int(hour)}"
    CONVOS.append((user_id, sid, "user", q, weeks_ago, hour))
    CONVOS.append((user_id, sid, "assistant", a, weeks_ago, hour + 0.05))

# ══════════════════════════════════════════
# A 陳同學 (moodle:1001)
# ══════════════════════════════════════════
A = "moodle:1001"

add_qa(A, "linked list 和 array 有什麼差別？",
"好問題！簡單來說：\n\n**Array（陣列）**：元素連續存放在記憶體中，可以用 index 直接存取（O(1)），但插入/刪除需要搬動元素（O(n)）。\n\n**Linked List（鏈結串列）**：元素分散在記憶體中，用 pointer 串起來。插入/刪除只要改 pointer（O(1)），但存取第 k 個元素要從頭走（O(n)）。\n\n想像 array 像一排座位，linked list 像尋寶遊戲的線索鏈 🔗",
10, 1)

add_qa(A, "linked list 插入節點時 pointer 怎麼接？能不能畫圖給我看？",
"好的！假設要在 A → C 之間插入 B：\n\n```\n插入前：A → C → D\n\n步驟 1：建立新節點 B\n步驟 2：B.next = C      （B 先指向 C）\n步驟 3：A.next = B      （A 改指向 B）\n\n插入後：A → B → C → D\n```\n\n⚠️ 順序很重要！如果先做步驟 3，C 就找不到了（斷鏈）。\n\n記口訣：**新的先接後面，舊的再改指向** 📝",
8, 1)

add_qa(A, "刪除 linked list 節點時要怎麼處理 pointer？上次插入我懂了但刪除又搞混了",
"刪除跟插入類似，關鍵是要**先保存**要刪除節點的下一個：\n\n```\n刪除 B：A → B → C → D\n\n步驟 1：temp = B.next    （先記住 C）\n步驟 2：A.next = temp    （A 跳過 B 直接指 C）\n步驟 3：刪除 B\n\n結果：A → C → D\n```\n\n你之前插入記住了「新的先接後面」，刪除就是「先記住後面，再跳過」 🎯\n\n要不要試著自己畫一次 A → B → C → D → E 刪除 C 的過程？",
6, 1)

add_qa(A, "hash table 碰撞要怎麼處理？chaining 怎麼運作？",
"""Hash Table 碰撞處理有兩大方法：**Chaining** 和 **Open Addressing**。

## Chaining（鏈結法）

每個 bucket 掛一條 linked list，碰撞的元素接在後面：

- 插入：$O(1)$（直接接在 list 頭）
- 搜尋：$O(1 + \\alpha)$，其中 $\\alpha = \\frac{n}{m}$ 是 load factor
- 當 $\\alpha < 1$ 時效能很好

## 互動模擬

下面這個互動模組讓你實際操作 hash table 的 chaining 過程：

```html
<!DOCTYPE html>
<html><head><style>
*{margin:0;padding:0;box-sizing:border-box;font-family:system-ui,sans-serif}
body{padding:16px;background:#f8fafc}
h3{font-size:14px;margin-bottom:10px;color:#1e293b}
.controls{display:flex;gap:8px;margin-bottom:16px}
input{padding:6px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;width:100px}
button{padding:6px 14px;border:none;border-radius:6px;font-size:13px;cursor:pointer;font-weight:500}
.btn-insert{background:#6366f1;color:#fff}
.btn-insert:hover{background:#4f46e5}
.btn-clear{background:#f1f5f9;color:#64748b;border:1px solid #d1d5db}
.table-viz{display:flex;gap:2px;margin-top:8px}
.bucket{min-width:60px;background:#fff;border:1px solid #d1d5db;border-radius:6px;padding:4px;font-size:11px;text-align:center}
.bucket-idx{font-weight:700;color:#6366f1;padding:2px;border-bottom:1px solid #e5e7eb;margin-bottom:4px}
.bucket-item{background:#eef2ff;border-radius:4px;padding:2px 4px;margin:2px 0;font-size:11px;animation:fadeIn .3s}
.bucket-item.collision{background:#fef3c7;border:1px solid #fbbf24}
.log{margin-top:12px;padding:8px;background:#fff;border:1px solid #d1d5db;border-radius:6px;font-size:11px;max-height:100px;overflow-y:auto;color:#64748b}
@keyframes fadeIn{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:translateY(0)}}
</style></head><body>
<h3>🔗 Hash Table Chaining 互動模擬</h3>
<div class="controls">
  <input type="number" id="val" placeholder="輸入數字" min="0" max="99">
  <button class="btn-insert" onclick="insert()">插入</button>
  <button class="btn-clear" onclick="clearAll()">清除</button>
  <span style="font-size:12px;color:#94a3b8;padding-top:6px">表格大小: 7 | hash(x) = x mod 7</span>
</div>
<div class="table-viz" id="tableViz"></div>
<div class="log" id="log">等待操作...</div>
<script>
const SIZE=7;let buckets=Array.from({length:SIZE},()=>[]);
function render(){
  const el=document.getElementById('tableViz');
  el.innerHTML='';
  for(let i=0;i<SIZE;i++){
    let html=`<div class="bucket"><div class="bucket-idx">[${i}]</div>`;
    buckets[i].forEach((v,j)=>{
      const cls=j>0?'bucket-item collision':'bucket-item';
      html+=`<div class="${cls}">${v}</div>`;
    });
    if(!buckets[i].length) html+='<div style="color:#d1d5db;font-size:10px;padding:4px">空</div>';
    html+='</div>';
    el.innerHTML+=html;
  }
}
function insert(){
  const v=parseInt(document.getElementById('val').value);
  if(isNaN(v))return;
  const idx=v%SIZE;
  const collision=buckets[idx].length>0;
  buckets[idx].push(v);
  const logEl=document.getElementById('log');
  if(collision) logEl.innerHTML=`⚠️ <b>碰撞！</b> hash(${v})=${idx}，bucket[${idx}]已有 [${buckets[idx].slice(0,-1)}]，用 chaining 接在後面<br>`+logEl.innerHTML;
  else logEl.innerHTML=`✅ hash(${v})=${idx}，放入 bucket[${idx}]<br>`+logEl.innerHTML;
  document.getElementById('val').value='';
  render();
}
function clearAll(){buckets=Array.from({length:SIZE},()=>[]);document.getElementById('log').innerHTML='已清除';render()}
document.getElementById('val').addEventListener('keydown',e=>{if(e.key==='Enter')insert()});
render();
</script></body></html>
```

試試看：輸入 10, 17, 24 這三個數字，它們的 hash 值都是 3（因為 mod 7 都等於 3），你會看到 chaining 的過程 👆""",
4, 3)

add_qa(A, "binary tree 的 inorder traversal 怎麼走？我看了課本但看不懂",
"Inorder traversal 的口訣是 **左 → 根 → 右**（LNR）：\n\n```\n        4\n       / \\\n      2   6\n     / \\ / \\\n    1  3 5  7\n```\n\n走法：先一直往左走到底 → 印出 → 回到 parent → 去右邊\n\n結果：1, 2, 3, 4, 5, 6, 7 ← 注意是排序好的！\n\n**記法**：\n- **In**order = 根在**中**間 → 左根右\n- **Pre**order = 根在**前**面 → 根左右\n- **Post**order = 根在**後**面 → 左右根\n\n你偏好視覺化，建議拿紙實際走一遍上面那棵樹 ✏️",
3, 1)

add_qa(A, "binary tree 的三種 traversal 我還是分不清，有沒有好記的方法？",
"來！用你喜歡的圖解方式，三種 traversal 的差別就是**根（印）的時間點**：\n\n```\n同一棵樹：    A\n            / \\\n           B   C\n\nPreorder  (根左右)：A → B → C   根最先\nInorder   (左根右)：B → A → C   根在中間  \nPostorder (左右根)：B → C → A   根最後\n```\n\n**超好記口訣**：\n- Pre = 先印自己，再管小孩\n- In = 左邊的先，自己中間，右邊最後\n- Post = 小孩都印完了，才輪到自己\n\n你之前問了 5 次這個概念，這次用口訣記下來，考試直接秒殺 💪",
2, 2)

add_qa(A, "期中考 inorder traversal 寫錯了，到底 left-root-right 是什麼意思？",
"沒關係，考完了我們重新把它搞懂！\n\nInorder = **L**eft → **N**ode → **R**ight\n\n用遞迴的方式想：\n```python\ndef inorder(node):\n    if node is None:\n        return\n    inorder(node.left)   # 先走完左子樹\n    print(node.val)      # 印自己\n    inorder(node.right)  # 再走右子樹\n```\n\n你期中考那題的樹，我幫你走一遍：\n```\n      5\n     / \\\n    3   8\n   /   / \\\n  1   6   9\n\n答案：1 → 3 → 5 → 6 → 8 → 9\n```\n\n注意到了嗎？**BST 的 inorder 結果一定是排序好的** 🎯",
1, 1)

add_qa(A, "LEFT JOIN 和 INNER JOIN 到底差在哪？",
"用你喜歡的圖解：\n\n假設有兩個 table：\n- Students: 小明、小華、小美\n- Grades: 小明 90分、小華 85分\n\n```\nINNER JOIN：只留兩邊都有的\n→ 小明 90、小華 85\n→ 小美不見了（因為沒成績）\n\nLEFT JOIN：左邊全保留，右邊沒有就 NULL\n→ 小明 90、小華 85、小美 NULL\n→ 小美還在！只是成績是 NULL\n```\n\n**口訣**：INNER = 交集、LEFT = 左邊全要 📊",
4, 14)

# ══════════════════════════════════════════
# B 林同學 (moodle:1002) — 進階問題
# ══════════════════════════════════════════
B = "moodle:1002"

add_qa(B, "amortized analysis 用 potential method 怎麼證明？",
"好問題！Potential method 的核心公式：\n\n**ĉᵢ = cᵢ + Φ(Dᵢ) - Φ(Dᵢ₋₁)**\n\n其中 ĉᵢ 是 amortized cost，cᵢ 是 actual cost，Φ 是 potential function。\n\n以 Dynamic Array 為例：\n- Φ(D) = 2n - capacity （n 是目前元素數）\n- 一般 push：actual cost = 1，Φ 增加 2 → ĉ = 1 + 2 = 3\n- Doubling push：actual cost = n+1，Φ 降到 2 → ĉ = (n+1) + 2 - 2(n-1) = 3\n\n所以不管哪種情況，amortized cost 都是 **O(1)** ✨\n\n你想要看 aggregate method 或 accounting method 的對比嗎？",
5, 1)

add_qa(B, "AVL tree 和 Red-Black tree 的效能差異是什麼？什麼場景選哪個？",
"核心差異在於**平衡的嚴格度**：\n\n| | AVL Tree | Red-Black Tree |\n|---|---|---|\n| 平衡條件 | 高度差 ≤ 1（嚴格） | 黑高相同（寬鬆） |\n| 搜尋 | O(log n)，常數較小 | O(log n)，常數較大 |\n| 插入旋轉 | 最多 2 次 | 最多 2 次 |\n| 刪除旋轉 | O(log n) 次 | 最多 3 次 |\n| 適用場景 | 讀多寫少 | 寫多讀少 |\n\nRed-Black 刪除最多只要 3 次旋轉是它的殺手鐧 — 這就是為什麼 C++ STL `std::map` 和 Java `TreeMap` 都用 Red-Black Tree。\n\n如果是 in-memory database index 這種讀遠多於寫的場景，AVL 更適合。",
7, 1)

add_qa(B, "PostgreSQL MVCC 怎麼實現 Isolation？跟 2PL 比較？",
"PostgreSQL 用 **MVCC (Multi-Version Concurrency Control)**：\n\n**核心機制**：每個 transaction 看到的是一個 consistent snapshot，不會被其他 transaction 的寫入干擾。\n\n- 每筆 row 有 `xmin`（建立的 txn ID）和 `xmax`（刪除的 txn ID）\n- 讀取時根據自己的 txn ID 判斷哪個版本可見\n- **讀不會 block 寫，寫不會 block 讀** ← 最大優勢\n\n**vs 2PL (Two-Phase Locking)**：\n- 2PL：讀加 shared lock，寫加 exclusive lock → 讀寫互相 block\n- MVCC：空間換時間（多版本佔空間，但並發度高）\n- 2PL 保證 Serializable，MVCC 預設 Read Committed（更高隔離等級需要額外機制）\n\n效能上 MVCC 在高並發 OLTP 場景完勝 2PL。",
2, 1)

# ══════════════════════════════════════════
# C 王同學 (moodle:1003) — 重修，基礎弱
# ══════════════════════════════════════════
C = "moodle:1003"

add_qa(C, "什麼是 variable？為什麼要取名字？",
"Variable（變數）就像一個**有名字的盒子** 📦\n\n你可以把東西放進去，之後用名字找到它：\n\n```python\nage = 20        # 一個叫 age 的盒子，裡面放 20\nname = \"小王\"    # 一個叫 name 的盒子，裡面放文字\n\nprint(age)      # 印出 20\nprint(name)     # 印出 小王\n```\n\n為什麼要取名字？因為電腦記憶體有幾十億個位置，你不可能記住每個地址。名字就是你的快捷鍵 🏷️",
10, 3)

add_qa(C, "print() 和 return 有什麼不一樣？",
"這是初學者最容易搞混的！\n\n```python\ndef add_print(a, b):\n    print(a + b)    # 印出來給你看\n\ndef add_return(a, b):\n    return a + b    # 把結果送回去\n\n# 差別：\nadd_print(1, 2)           # 螢幕顯示 3，但抓不到值\nresult = add_return(1, 2) # 螢幕什麼都沒有，但 result = 3\n```\n\n**比喻**：\n- `print` = 大聲說出答案（別人聽到了但沒人記住）\n- `return` = 把答案寫在紙上交回去（可以繼續用）\n\n記住：要**用**結果就 return，要**看**結果就 print 👀",
9, 1)

add_qa(C, "for 迴圈跑出來的結果跟我想的不一樣",
"來，把你的 code 貼給我，我幫你一行一行走。\n\n假設你的 code 是：\n```python\nfor i in range(3):\n    print(i * 2)\n```\n\n逐行執行：\n| 迴圈次數 | i 的值 | i * 2 | 印出 |\n|---------|--------|-------|------|\n| 第 1 次 | 0 | 0 | 0 |\n| 第 2 次 | 1 | 2 | 2 |\n| 第 3 次 | 2 | 4 | 4 |\n\n常見錯誤：\n- `range(3)` 是 0, 1, 2（不包含 3）\n- `range(1, 4)` 才是 1, 2, 3\n\n小技巧：不確定的時候，用表格把每一步寫下來追蹤 📋",
8, 1)

add_qa(C, "期中考會考什麼？我很多都不會",
"別慌！我根據你之前的學習紀錄，幫你列出最重要的：\n\n**一定會考**：\n1. variable 型別和賦值 ← 你已經會了 ✅\n2. if/else 條件判斷 ← 要複習\n3. for/while 迴圈 ← 你之前有困難，重點複習\n4. function 定義和呼叫 ← 你最弱的部分 ⚠️\n\n**可能會考**：\n5. list 操作（append、slice）\n6. try/except 基礎\n\n建議：先花 1 小時把 function 的 print vs return 搞懂，這個最值得投資。你要我從 function 開始幫你複習嗎？",
2, 1)

# ══════════════════════════════════════════
# D 李同學 (moodle:1004) — 消失的學生
# ══════════════════════════════════════════
D = "moodle:1004"

add_qa(D, "什麼是 stack？可以舉個生活中的例子嗎？",
"Stack 就像**疊盤子** 🍽️\n\n最後放上去的盤子，最先被拿起來 = **LIFO (Last In, First Out)**\n\n```\n放入：1 → 2 → 3\n\n  |  3  | ← 最上面\n  |  2  |\n  |  1  | ← 最下面\n  +-----+\n\n拿出：3 → 2 → 1（反過來）\n```\n\n生活例子：\n- 疊盤子（最後放的最先拿）\n- 瀏覽器的「上一頁」按鈕\n- Ctrl+Z 復原\n\n操作只有兩個：push（放上去）和 pop（拿走最上面的）",
10, 1)

add_qa(D, "linked list 為什麼要用 pointer？直接用 array 不行嗎？",
"Array 有個問題：大小固定，中間插入要搬家。\n\n想像你排隊買飲料，有人要插隊到中間：\n- **Array 做法**：後面所有人都要往後退一步 😓\n- **Linked list 做法**：插隊的人直接站進去，前後兩人手拉手連起來就好 🤝\n\nPointer 就是那個「手」，告訴你下一個人在哪裡。\n\n所以 linked list 的優勢是：插入刪除很快（O(1)），代價是找人比較慢（O(n)，要從頭開始數）。",
8, 1)

add_qa(D, "期中考要怎麼準備？我什麼都不會",
"先不要慌，我幫你分析一下。根據紀錄，你目前掌握的：\n\n✅ stack 的基本概念（疊盤子比喻你記住了）\n🟡 array vs linked list 的差別（有概念但細節不熟）\n❌ pointer 操作（還沒練過）\n❌ tree、hash table（還沒開始）\n❌ 時間複雜度分析\n\n**考前 3 天救急策略**：\n1. 只準備 stack 和 queue 的選擇題（最容易拿分）\n2. array 和 linked list 的比較題（你有基礎概念）\n3. 放棄 tree 和 hash table（來不及了，期末再補）\n\n但我要說實話：如果這門課太吃力，建議跟老師談談，看有沒有其他選擇。你的身心健康比成績重要。",
2, 1)

# ══════════════════════════════════════════
# E 張同學 (moodle:1005) — 實作派
# ══════════════════════════════════════════
E = "moodle:1005"

add_qa(E, "ACID 的 Isolation 是什麼意思？可以用銀行轉帳的例子說明嗎？",
"當然！**Isolation = 交易之間互不干擾**\n\n場景：小明轉 1000 元給小華\n\n```\n交易 A（小明 → 小華 1000 元）：\n  1. 讀小明餘額 = 5000\n  2. 小明 - 1000 = 4000\n  3. 讀小華餘額 = 3000  \n  4. 小華 + 1000 = 4000\n```\n\n如果**沒有 Isolation**，另一個交易 B 在步驟 2 和 3 之間讀了小明餘額，可能看到只扣了一半的狀態 → **髒讀 (Dirty Read)**\n\n有 Isolation：交易 B 要嘛看到轉帳前的狀態，要嘛看到轉帳後的，不會看到中間狀態。\n\n就像 ATM 轉帳時螢幕會顯示「交易處理中」，不讓你做其他操作 🏧",
6, 1)

add_qa(E, "什麼時候該用 index？加太多 index 會怎樣？",
"**該加 index 的時候**：\n- WHERE 裡經常用到的欄位（如 `WHERE student_id = 123`）\n- JOIN 的條件欄位\n- ORDER BY 的欄位\n\n**不該加 index**：\n- 很少查詢的欄位\n- 值很少變化的欄位（如 gender 只有 M/F）\n- 資料量很小的表（全掃描就很快了）\n\n**加太多的副作用**：\n```\n寫入變慢 📉：每次 INSERT/UPDATE 都要更新所有 index\n佔空間 💾：index 本身也要存在硬碟\n```\n\n比喻：index 就像書的目錄頁。一本 100 頁的書有 3 頁目錄很合理，但如果目錄比內容還多（50 頁目錄），那找目錄本身就很慢了 📚",
7, 1)

add_qa(E, "EXPLAIN 跑出來的結果要怎麼看？",
"EXPLAIN 告訴你資料庫打算**怎麼執行**你的 SQL：\n\n```sql\nEXPLAIN SELECT * FROM students WHERE age > 20;\n```\n\n結果可能是：\n```\nSeq Scan on students  (cost=0.00..25.50 rows=500)\n  Filter: (age > 20)\n```\n\n**重要關鍵字**：\n- `Seq Scan` = 一筆一筆掃全表（慢 🐌）\n- `Index Scan` = 用 index 查（快 ⚡）\n- `cost` = 預估成本（越小越好）\n- `rows` = 預估回傳筆數\n\n如果看到 Seq Scan 在大表上 → 考慮加 index\n如果看到 Index Scan → 很好，index 有被用到\n\n你可以試試：先 EXPLAIN 不加 index，再加了之後 EXPLAIN 一次，比較差異 🔍",
3, 5)


def main():
    print(f"Seeding conversations to: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)

    # Clear existing messages
    conn.execute("DELETE FROM messages")
    conn.commit()

    count = 0
    for user_id, session_id, role, content, weeks_ago, hours in CONVOS:
        created_at = ts(weeks_ago, hours)
        conn.execute(
            "INSERT INTO messages (user_id, session_id, role, content, speaker_name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, session_id, role, content, "", created_at)
        )
        count += 1

    conn.commit()

    # Verify
    per_user = conn.execute(
        "SELECT user_id, COUNT(*) FROM messages GROUP BY user_id"
    ).fetchall()
    print(f"\nSeeded {count} messages:")
    names = {"moodle:1001": "A 陳", "moodle:1002": "B 林", "moodle:1003": "C 王",
             "moodle:1004": "D 李", "moodle:1005": "E 張"}
    for uid, cnt in per_user:
        pairs = cnt // 2
        print(f"  {names.get(uid, uid)}: {pairs} conversations ({cnt} messages)")

    conn.close()
    print("✅ Done!")


if __name__ == "__main__":
    main()
