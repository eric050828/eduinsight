"""Seed realistic semester conversations + facts for all 5 demo students.

Bypasses the LLM (which would take ~75s per turn) and writes Q+A directly to
Lite-Mem's messages table with backdated timestamps spread across an
18-week semester. Also stores struggle / preference facts so the
analytics endpoints have something to surface beyond the chat history.

Run after a /demo/reset wipes prior conversations:

    uv run python scripts/seed_semester_conversations.py
"""

from __future__ import annotations

import time
from typing import NamedTuple

from litemem import Memory

from eduinsight.config import settings


class Turn(NamedTuple):
    week: int  # 1-18
    course: str
    student: int
    question: str
    answer: str


# 18-week semester ending now. Day 0 = today, Day -126 ≈ Week 1.
NOW = time.time()
WEEK_SECONDS = 7 * 86400


def week_ts(week: int) -> float:
    """Convert a (1-18) week number into an approximate Unix timestamp."""
    weeks_ago = 18 - week
    return NOW - weeks_ago * WEEK_SECONDS + (week % 3) * 7200  # add slight per-week jitter


# ----------------------------------------------------------------------
# Conversation script: ~10 turns per student spread across the semester
# ----------------------------------------------------------------------

CONVERSATIONS: list[Turn] = [
    # ============== A 陳同學 (1001, 資管系) — 學霸，深度提問 ==============
    Turn(2, "ds101", 1001,
         "為什麼動態陣列要用倍增擴容而不是線性 +10？我看講義說攤銷 O(1)，具體推導是什麼？",
         "倍增擴容的攤銷 O(1) 來自於：每次擴容把容量翻倍，所以 N 次插入中總共只發生 log N 次擴容，"
         "每次擴容複製成本與當下容量成正比，總成本 O(2N) ≈ O(N)，攤銷到每次插入就是 O(1)。"
         "如果改用 +10 線性擴容，N 次插入會觸發 N/10 次擴容，總成本 O(N²/10)，每次攤銷 O(N) — 退化。"),
    Turn(4, "ds101", 1001,
         "為什麼 BST 用 inorder 走會自動排序好？這個性質有什麼實際應用？",
         "BST 的不變式是「左子樹所有節點 < 根 < 右子樹所有節點」。"
         "Inorder 的訪問順序「左 → 根 → 右」剛好對應升序。"
         "實際應用：Java TreeMap.values() 內部就是 inorder 走訪，所以 keySet() 拿到的是排序好的 key set。"
         "這也是為什麼資料庫 index 用 B-Tree（BST 變種）— 範圍查詢是 inorder。"),
    Turn(7, "ds101", 1001,
         "如果今天是 hash table 內部要存衝突的元素，用陣列還是鏈結串列比較好？",
         "短鏈表用 LinkedList 開銷反而大（cache miss + 指標額外 16 bytes/node），"
         "Java 8 的 HashMap 採折衷：鏈長 < 8 用鏈表，>= 8 自動轉紅黑樹避免最差 O(n)。"
         "所以「用什麼」取決於預期碰撞長度，這是工程取捨而非單純資料結構選擇。"),
    Turn(11, "ds101", 1001,
         "既然 quicksort 平均比 mergesort 快又是原地排序，為什麼 Python 的 sorted() 不選 quicksort 而選 Timsort？",
         "三個原因：(1) Timsort 是穩定排序，quicksort 不是，Python list 的排序需要保留同 key 元素相對順序。"
         "(2) Timsort 對「近乎排序」資料是 O(n)，真實資料常含已排序段。"
         "(3) Quicksort 最差 O(n²)，Python 不能接受 worst-case 隨資料分布暴漲。"),
    Turn(15, "ds101", 1001,
         "Dijkstra 為什麼不能處理負邊？我看課本講「貪心策略失效」但不太具體",
         "Dijkstra 假設「一旦從 priority queue pop 出來，這個節點的距離就確定了」。"
         "若有負邊，可能後面還會有更短路徑經過已 pop 的節點。"
         "舉例 A→B 權重 5, A→C→B 權重 4 + (-2) = 2，"
         "A 出發先 pop B（距離 5），但實際最短路徑是 A→C→B 距離 2 — Dijkstra 不會回頭重算。"
         "所以負邊要用 Bellman-Ford 或 SPFA。"),

    # ============== B 林同學 (1002, 企管系) — 中上，跨修 mk201 ==============
    Turn(3, "mk201", 1002,
         "老師講 STP 的時候，我搞不清楚 Targeting 跟 Positioning 有什麼差別？感覺都是「鎖定客群」",
         "差別在「決定誰」vs「在那群人心中的形象」。Targeting = 選擇要服務哪個區隔（決定誰）。"
         "Positioning = 在被選中那群人的心智裡，建立差異化形象。"
         "星巴克 Targeting：都會白領；Positioning：第三空間（不只是咖啡店是社交場所）。"
         "若只 Targeting 沒 Positioning，會跟其他咖啡連鎖一樣，無法收高價。"),
    Turn(5, "mk201", 1002,
         "作業要做 SWOT 分析，我把「市場競爭激烈」寫進 Weaknesses，老師說我寫錯了，為什麼？",
         "Weaknesses 必須是「企業內部」可控因素（如資源不足、品牌弱）。"
         "市場競爭激烈是「外部環境」，屬於 Threats。"
         "判斷小技巧：如果這個因素「換一家公司也還是這樣」，那就是外部 (O/T)；"
         "「換一家公司就不會這樣」才是內部 (S/W)。"),
    Turn(9, "ds101", 1002,
         "Bellman-Ford 的時間複雜度為什麼是 O(VE)？",
         "Bellman-Ford 要做 V-1 輪 relax，每輪掃過所有 E 條邊，"
         "所以 O((V-1) × E) = O(VE)。為什麼 V-1 輪夠？因為任何最短路徑最多 V-1 條邊（無負環）。"),
    Turn(13, "mk201", 1002,
         "競爭定位的「知覺地圖」要選哪兩個軸？",
         "選對顧客決策最重要的兩個屬性。例：手機選「價格 vs 性能」、汽車選「安全 vs 動力」。"
         "畫法：縱軸高/低，橫軸某種 spectrum，把競品畫成點，看市場空缺。"
         "錯誤示範：選「銷量 vs 滿意度」— 這兩個都是結果不是定位屬性。"),

    # ============== C 王同學 (1003, 化工系) — 中段 ==============
    Turn(2, "ds101", 1003,
         "作業要實作鏈結串列的 reverse，我寫了但 next pointer 一直繞來繞去搞混。三個指標 prev/curr/next 怎麼動？",
         "三步驟反覆：(1) 暫存 next = curr.next（先記住下一個，因為等等要改）"
         "(2) 反轉指針 curr.next = prev（這是核心，把箭頭反過來）"
         "(3) 推進 prev = curr; curr = next。\n"
         "用紙筆畫圖比較好懂：每個 iteration 三個指標都往右走一格。"),
    Turn(6, "chm301", 1003,
         "老師講熱力學第一定律 ΔU = q + w，我每次符號都搞反，q 是吸熱還是放熱算正？我考試又錯",
         "用 IUPAC / Atkins 慣例（最常見的）："
         "q > 0 = 系統「吸熱」，q < 0 = 系統「放熱」。"
         "w > 0 = 環境「對系統」做功，w < 0 = 系統對環境做功。"
         "口訣：「進來的算正」— 不管熱還是功，只要往系統方向，就是正。"),
    Turn(10, "chm301", 1003,
         "理想氣體絕熱可逆 PV^γ = const，γ 是怎麼推來的？我直接背是 5/3 跟 7/5 但不知道為什麼",
         "γ = Cp/Cv（等壓熱容除以等容熱容），物理意義是「氣體的剛性程度」。"
         "從 Mayer 關係 Cp = Cv + nR，加上能量均分原理：單原子有 3 個自由度 → Cv = 3R/2，Cp = 5R/2 → γ = 5/3。"
         "雙原子（室溫）轉動自由度也激發 → Cv = 5R/2 → γ = 7/5。"
         "所以 γ 越大代表自由度越少（剛性越強）。"),
    Turn(14, "chm301", 1003,
         "考試題：「一個近乎排好的陣列要排序，選哪個演算法最快？」我寫 quicksort 結果錯了，正解是 insertion sort",
         "Insertion sort 對「幾乎已排序」資料表現特別好，因為每個元素只要往前少數幾步就找到位置 → O(n)。"
         "Quicksort 平均 O(n log n) 沒錯，但對已排序資料如果 pivot 選最左，會退化成 O(n²)。"
         "Timsort 也採用同樣邏輯：對短的「近乎排好的 run」用 insertion sort 補強，再用 merge 合起來。"),

    # ============== D 李同學 (1004, 應外輔修) — 高風險 ==============
    Turn(1, "ds101", 1004,
         "老師講陣列我聽不太懂，什麼是 index？為什麼陣列存取是 O(1)？",
         "Index 就是「位置編號」，從 0 開始：a[0] 是第一個，a[1] 是第二個。"
         "為什麼 O(1)？因為陣列在記憶體中是連續配置，"
         "拿到 a[i] 的位址公式很簡單：base_address + i × element_size，"
         "不管 i 多大都是「一次乘法 + 一次加法」就到，跟陣列大小無關。"),
    Turn(3, "ds101", 1004,
         "為什麼我寫 list.insert(0, x) 老師說很慢？我看不出來哪裡慢",
         "因為 Python list 底層是動態陣列，元素連續排列。"
         "insert(0, x) 要把所有現有元素「整體往後挪一格」，再把 x 放到位置 0。"
         "所以 N 個元素的 list 做 insert(0, x) 是 O(N)。"
         "如果你需要常常在頭部插入，改用 collections.deque，那是雙端佇列，append/appendleft 都是 O(1)。"),
    Turn(6, "ds101", 1004,
         "老師講 inorder 跟 preorder 我完全分不出來，每次寫測驗都選錯。可以給我超簡單的口訣嗎？",
         "看「根」的位置就好："
         "Pre = 根在 **前**：根 → 左 → 右"
         "In = 根在 **中**：左 → 根 → 右"
         "Post = 根在 **後**：左 → 右 → 根"
         "「Pre / In / Post」就是「根」的相對位置。記英文比中文順序快。"),
    Turn(7, "ds101", 1004,
         "那 BST 我完全不懂，為什麼要把資料這樣排？陣列不就好了嗎",
         "陣列查找特定值要 O(N)（從頭找），但 BST 平衡時是 O(log N)。"
         "舉例：找一個 100 萬筆資料的某筆，陣列最差 100 萬次比較，平衡 BST 約 20 次。"
         "陣列當然也可以排序後二分搜尋達 O(log N)，但「插入新資料」是 O(N)（要挪位置），"
         "BST 插入是 O(log N)。所以 BST 是「動態資料 + 快速搜尋」的最佳折衷。"),
    Turn(11, "ds101", 1004,
         "老師講了 7 種排序演算法，我都搞混了...quicksort 跟 mergesort 我看不出差別。我是不是不適合資工系",
         "你不是不適合，是「七個一起學」對任何人都太多。先記兩個就好："
         "Quicksort：選 pivot → 左小右大遞迴。**原地**、平均最快、不穩定、最差 O(n²)。"
         "Mergesort：對半切 → 各自排 → 合併。**穩定**、保證 O(n log n)、需 O(n) 額外空間。"
         "其他五個之後再認識，先把這兩個用熟。"),
    Turn(14, "eng201", 1004,
         "My thesis statement is 'Technology is good.' Teacher said it's too vague. How should I make it specific?",
         "A strong thesis must be (1) specific, (2) arguable, (3) supported by evidence. "
         "'Technology is good' fails all three. "
         "Better: 'Smartphone notifications fragment college students' attention spans, "
         "reducing deep work productivity by 23% per Stanford 2019.' "
         "It's specific (college students), arguable (someone could disagree), and citable."),
    Turn(16, "eng201", 1004,
         "APA 跟 MLA 引用差在哪？我每次寫 (Smith 2020) 還是 (Smith, 2020) 都搞混",
         "兩個系統最大差別在「inline 引用」和「reference list」格式。"
         "APA：(Smith, 2020) 有逗號 — 強調「年份」（社會科學重時間）。"
         "MLA：(Smith 25) 沒逗號，給頁碼不給年 — 強調「文本位置」（人文重原文）。"
         "選一個用到底，論文裡不要混。EduInsight 預設要求 APA。"),

    # ============== E 張同學 (1005, 跨域) — 積極跨修 ==============
    Turn(2, "ds101", 1005,
         "陣列跟鏈結串列我看不出差異，反正最後不就都是放東西的容器嗎？什麼時候用哪個？",
         "三個關鍵差異：(1) 記憶體佈局：陣列**連續**、鏈結**分散**。"
         "(2) 隨機存取：陣列 a[i] O(1)、鏈結要從頭走 O(n)。"
         "(3) 插入/刪除：陣列頭中部 O(n)、鏈結 O(1)（已知節點）。"
         "口訣：「常存取用陣列、常增刪用鏈結」。多數應用陣列勝出，這也是為什麼 Python 主用 list（其實是動態陣列）。"),
    Turn(8, "ipr101", 1005,
         "專利三要件：產業利用性、新穎性、進步性。我搞不懂進步性怎麼判斷？什麼叫「非能輕易完成」？",
         "進步性的判斷標準是「該領域具通常知識者，是否能輕易從現有技術組合出本發明」。"
         "三步測試：(1) 確定先前技術範圍 (2) 確定差異 (3) 判斷該差異是否為熟練技術人員「顯而易見」。"
         "舉例：把鉛筆加橡皮擦 — 看似簡單但歷史上獲專利，因為當年沒人想到。"
         "判斷時不能用「事後諸葛亮」，要回到申請日當時的技術水準。"),
    Turn(13, "ipr101", 1005,
         "什麼是禁反言？我看課本說「均等論的限制」但不太懂為什麼要這個原則",
         "禁反言（Prosecution History Estoppel）的精神是「申請人不能說兩套」。"
         "申請過程為了通過審查、限縮了 claim 範圍，事後就不能用均等論把放棄的範圍要回來。"
         "舉例：申請時主張「直徑 1-10 cm」被審查官說範圍太廣，改成「3-5 cm」獲准；"
         "事後告人家做了直徑 6 cm 的產品「侵權」是不行的 — 你已經放棄 5 cm 以上範圍了。"
         "目的：確保專利範圍對社會清晰可預測。"),
    Turn(16, "ipr101", 1005,
         "迷因二創跟合理使用要怎麼判斷？我朋友想做網路梗圖牟利但不確定合不合法",
         "用著作權法第 65 條四要素審：(1) 商業目的會扣分 (2) 原著創意性高扣分 "
         "(3) 用了多少（質與量）(4) 對原著市場的影響 — **最重要**。"
         "純惡搞無營利通常 OK；牟利的二創若「轉化性高」（加入新意義評論諷刺）有空間，"
         "但若只是「換個情境」沒有新意義，加上有營利，很可能不算合理使用。"
         "建議：先做給朋友看，要商業化前找律師。"),
    Turn(17, "ds101", 1005,
         "EXPLAIN 跑出來一堆東西看不懂，Seq Scan 是什麼意思？",
         "Seq Scan = Sequential Scan，「整張表掃一遍」。"
         "通常表示沒有 index 命中或 planner 認為掃全表比用 index 快（小表時）。"
         "判斷要不要建 index：看 EXPLAIN ANALYZE 的「Rows」，"
         "如果 Seq Scan 一個 1M 行的表只回 10 筆，那絕對該建 index。"),
]


# ----------------------------------------------------------------------
# Struggle / preference facts derived from the conversations above.
# These populate /analytics/student/*/struggles + weak_topics + preferences.
# ----------------------------------------------------------------------

FACT_SEEDS: list[tuple[int, str]] = [
    # 1001 A 陳 — 高層次提問，少掙扎；偏好深度推導
    (1001, "Learning preference: prefers formal proofs and complexity analysis over intuitive explanations"),
    # 1002 B 林 — 跨修 mk201
    (1002, "Struggling with: SWOT 內外部因素分類 — confused 「市場競爭激烈」 should be Threat (external) not Weakness (internal)"),
    (1002, "Struggling with: Targeting 與 Positioning 區別"),
    (1002, "Learning preference: prefers concrete brand cases (Starbucks, Apple) over abstract frameworks"),
    # 1003 C 王 — 化工
    (1003, "Struggling with: 熱力學第一定律 q/w 符號慣例"),
    (1003, "Struggling with: γ = Cp/Cv 推導"),
    (1003, "Struggling with: 鏈結串列 prev/curr/next 三指標反轉操作"),
    (1003, "Learning preference: 偏好用紙筆畫圖追蹤指標移動"),
    # 1004 D 李 — 高風險，跨修 eng201
    (1004, "Struggling with: 陣列 list.insert(0, x) 為 O(n)"),
    (1004, "Struggling with: inorder vs preorder 順序混淆"),
    (1004, "Struggling with: BST 為什麼比陣列好"),
    (1004, "Struggling with: 多種排序演算法區分（quicksort vs mergesort）"),
    (1004, "Struggling with: thesis statement specificity"),
    (1004, "Struggling with: APA vs MLA citation format"),
    (1004, "Learning preference: 偏好簡單口訣與類比，先學少數核心再擴展"),
    # 1005 E 張 — 跨域積極
    (1005, "Struggling with: 進步性 (Inventive Step) 判斷標準"),
    (1005, "Struggling with: 禁反言 (Prosecution History Estoppel) 概念"),
    (1005, "Learning preference: 偏好用真實案例 (iPhone vs HTC, 鉛筆+橡皮擦) 學抽象法律概念"),
]


def main() -> None:
    mem = Memory(settings.memory_db_path)

    # 1. 寫入結構化 facts（給 analytics 用）
    fact_count = 0
    for moodle_id, text in FACT_SEEDS:
        try:
            mem.add(f"moodle:{moodle_id}", text)
            fact_count += 1
        except Exception as e:  # noqa: BLE001
            print(f"  fact for {moodle_id} skipped: {e}")
    print(f"Stored {fact_count} structured facts")

    # 2. 寫入完整對話歷史（messages 表）
    # 透過 internal _store (LiteMem 物件) 直接 SQL 操作以維持 backdated timestamp
    store = mem._store  # noqa: SLF001
    msg_count = 0
    for i, t in enumerate(CONVERSATIONS):
        uid = f"moodle:{t.student}"
        ts = week_ts(t.week)
        sid = f"sim-{t.student}-w{t.week}-{i}"
        with store._lock:  # noqa: SLF001
            conn = store._get_conn()  # noqa: SLF001
            conn.execute(
                "INSERT INTO messages (user_id, session_id, role, content, speaker_name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uid, sid, "user", t.question, "", ts),
            )
            conn.execute(
                "INSERT INTO messages (user_id, session_id, role, content, speaker_name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uid, sid, "assistant", t.answer, "", ts + 30),
            )
            conn.commit()
        msg_count += 2
    print(f"Stored {msg_count} messages across {len(CONVERSATIONS)} conversations")

    # 3. 統計
    by_student: dict[int, int] = {}
    for t in CONVERSATIONS:
        by_student[t.student] = by_student.get(t.student, 0) + 1
    for sid, n in sorted(by_student.items()):
        print(f"  Student {sid}: {n} conversations")


if __name__ == "__main__":
    main()
