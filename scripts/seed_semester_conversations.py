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

from pathlib import Path

from litemem import Memory

from eduinsight.config import settings
from eduinsight import sessions as sessions_mod
from eduinsight.documents import slugify


def cite(filename: str, heading: str, label: str | None = None) -> str:
    """Return a markdown link the frontend renders as a clickable material chip.

    `[label](<filename#anchor>)` — angle-bracket URL form so spaces in filename
    are valid per CommonMark. RichMarkdown attaches onMaterialLink so the right
    pane jumps to that file + heading anchor with flash highlight.
    """
    anchor = slugify(heading)
    text = label or f"📘 {Path(filename).stem} §{heading}"
    return f"[{text}](<{filename}#{anchor}>)"


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
# Rich-content conversations — these answers showcase markdown features
# (mermaid diagrams, KaTeX math, fenced code, iframe embeds) so the
# chat panel demonstrates the full visual capability of the system.
# ----------------------------------------------------------------------

RICH_CONVERSATIONS: list[Turn] = [
    # ─── A 陳 (1001) — DS101 深度提問 ───
    Turn(5, "ds101", 1001,
         "BST 的時間複雜度為什麼平衡時是 O(log n)？最差情況又長什麼樣？",
         "平衡 BST 的高度 $h = \\lceil \\log_2(n+1) \\rceil$，搜尋只走一條路徑所以 $T(n) = O(h) = O(\\log n)$。\n\n"
         "若退化成單邊鏈（連續插入排序資料），高度 $h = n$，退化為 $O(n)$。\n\n"
         "```mermaid\n"
         "graph TD\n"
         "  A[8] --> B[3]\n"
         "  A --> C[10]\n"
         "  B --> D[1]\n"
         "  B --> E[6]\n"
         "  C --> F[14]\n"
         "  E --> G[4]\n"
         "  E --> H[7]\n"
         "```\n\n"
         "視覺化能幫助理解：上圖是平衡 BST，搜尋 7 走 8→3→6→7 共 4 步 ≈ $\\log_2 8$。\n\n"
         "📎 詳細表格參考：" + cite("Big-O 速查表.md", "常見資料結構操作") + "。"),
    Turn(8, "ds101", 1001,
         "Quicksort 的 partition 步驟可以畫流程圖嗎？",
         "Lomuto partition 流程：\n\n"
         "```mermaid\n"
         "flowchart TD\n"
         "  S[\"Start: pivot = arr[hi]\"] --> I[\"i = lo - 1\"]\n"
         "  I --> L{\"j = lo to hi-1\"}\n"
         "  L -->|\"arr[j] <= pivot\"| Sw[\"swap arr[++i], arr[j]\"]\n"
         "  L -->|else| L\n"
         "  Sw --> L\n"
         "  L -->|\"loop done\"| F[\"swap arr[i+1], arr[hi]\"]\n"
         "  F --> R[\"return i+1\"]\n"
         "```\n\n"
         "對應程式碼（可在這裡直接跑）：\n\n"
         "```pyrun\n"
         "def partition(arr, lo, hi):\n"
         "    pivot = arr[hi]\n"
         "    i = lo - 1\n"
         "    for j in range(lo, hi):\n"
         "        if arr[j] <= pivot:\n"
         "            i += 1\n"
         "            arr[i], arr[j] = arr[j], arr[i]\n"
         "    arr[i+1], arr[hi] = arr[hi], arr[i+1]\n"
         "    return i + 1\n"
         "\n"
         "demo = [3, 1, 4, 1, 5, 9, 2, 6]\n"
         "p = partition(demo, 0, len(demo) - 1)\n"
         "print(f'pivot index = {p}, after partition: {demo}')\n"
         "```\n\n"
         "按 ▶ Run 看 partition 把 6 當 pivot 後陣列變化 — 左側都 ≤6、右側都 >6。\n\n"
         "📎 也建議搭配影片觀看：" + cite("Quicksort 視覺化.youtube.md", "本片重點", "🎬 Quicksort 視覺化影片") + "，再對照 " + cite("Big-O 速查表.md", "排序演算法選用指南") + "。"),

    # ─── B 林 (1002) — MK201 ───
    Turn(6, "mk201", 1002,
         "Porter 五力分析能用圖表示嗎？我背不起來",
         "把五力放在中央產業周圍：\n\n"
         "```mermaid\n"
         "flowchart LR\n"
         "  S[供應商議價力] --> I((產業內競爭))\n"
         "  B[購買者議價力] --> I\n"
         "  N[新進入者威脅] --> I\n"
         "  R[替代品威脅] --> I\n"
         "  I --> P[產業利潤潛力]\n"
         "```\n\n"
         "**判讀心法**：五力越強 ⇒ 產業利潤越被壓縮。航空業就是經典低毛利例子（飛機供應商強、消費者比價、油價替代少）。\n\n"
         "📎 進階補充：" + cite("STP 框架完整指南.md", "Positioning 市場定位") + " 提到的「定位」就是要在五力結構中找到自己的差異化位置。"),
    Turn(10, "mk201", 1002,
         "STP 跟 4P 的順序到底是什麼？",
         "**先 STP 後 4P** — STP 決定「打誰」，4P 才決定「怎麼打」。\n\n"
         "```mermaid\n"
         "graph LR\n"
         "  S[Segmentation 區隔] --> T[Targeting 鎖定]\n"
         "  T --> P[Positioning 定位]\n"
         "  P --> Pr[Product]\n"
         "  P --> Pi[Price]\n"
         "  P --> Pl[Place]\n"
         "  P --> Pm[Promotion]\n"
         "```\n\n"
         "順序錯了就會變成「先做廣告才想客群是誰」，結果預算燒光定位還沒對。\n\n"
         "📎 教材對照：" + cite("STP 框架完整指南.md", "Segmentation 市場區隔") + "、" + cite("STP 框架完整指南.md", "Targeting 目標市場") + "。"),
    Turn(12, "mk201", 1002,
         "可以給我看一下老師指定的 STP 教學影片嗎？我想看完再寫期中報告",
         "影片內嵌在這裡，邊看邊做筆記：\n\n"
         '<iframe width="100%" height="320" src="https://www.youtube.com/embed/FBOExmRXLQc" '
         'title="STP Marketing Strategy" frameborder="0" allowfullscreen></iframe>\n\n'
         "**重點 takeaway**：\n"
         "1. **Segmentation** — 用人口/心理/行為切市場\n"
         "2. **Targeting** — 評估區隔的吸引力 + 公司能力 fit\n"
         "3. **Positioning** — 在目標客群心智裡建立獨特形象\n\n"
         "📎 配對閱讀：" + cite("STP 框架完整指南.md", "知覺地圖perceptual-map", "📘 知覺地圖實作") + "。"),

    # ─── C 王 (1003) — CHM301 物理化學 ───
    Turn(8, "chm301", 1003,
         "理想氣體狀態方程式跟 Van der Waals 方程式怎麼從圖看差異？",
         "理想氣體：$PV = nRT$\n\n"
         "Van der Waals 修正：$\\left(P + \\dfrac{an^2}{V^2}\\right)(V - nb) = nRT$\n\n"
         "其中 $a$ 修正分子間吸引力，$b$ 修正分子體積。\n\n"
         "**參考影片**（老師指定）：\n\n"
         '<iframe width="100%" height="280" src="https://www.youtube.com/embed/ZsY4WcQOrfk" '
         'title="Ideal vs Real Gas" frameborder="0" allowfullscreen></iframe>\n\n'
         "高壓低溫時偏差最大 — 因為分子靠近吸引力影響顯著。\n\n"
         "📎 對照公式：" + cite("熱力學公式總覽.md", "第一定律") + "。"),
    Turn(12, "chm301", 1003,
         "熵的統計定義 S = k ln W 跟熱力學定義 dS = dq_rev/T 怎麼連起來？",
         "兩個都對，但角度不同：\n\n"
         "- **熱力學定義**：$dS = \\dfrac{dq_{rev}}{T}$ — 巨觀可量測\n"
         "- **統計定義**（Boltzmann）：$S = k_B \\ln W$ — 微觀狀態數\n\n"
         "**橋接**：對理想氣體做等溫膨脹，從體積 $V_1$ 到 $V_2$：\n\n"
         "$$\\Delta S_{thermo} = nR \\ln \\frac{V_2}{V_1}$$\n\n"
         "$$\\Delta S_{stat} = k_B \\ln \\frac{W_2}{W_1} = k_B \\ln \\left(\\frac{V_2}{V_1}\\right)^N = N k_B \\ln \\frac{V_2}{V_1}$$\n\n"
         "因為 $N k_B = nR$，兩者完全相等。\n\n"
         "```mermaid\n"
         "graph LR\n"
         "  M[\"巨觀 dq_rev/T\"] -.等價.- B[\"Boltzmann k ln W\"]\n"
         "  M --> C[\"Clausius 不等式\"]\n"
         "  B --> S[\"Statistical Mechanics\"]\n"
         "```\n\n"
         "📎 教材公式整理：" + cite("熱力學公式總覽.md", "熵的兩種定義") + "、" + cite("熱力學公式總覽.md", "第二定律") + "。"),

    # ─── D 李 (1004) — 高風險，需要更多視覺化 ───
    Turn(4, "ds101", 1004,
         "老師講 Big O 我有聽沒有懂，可以畫個圖讓我看 O(1) O(n) O(n²) 差多少嗎？",
         "用一張圖看複雜度成長對比：\n\n"
         "| n | O(1) | O(log n) | O(n) | O(n²) |\n"
         "|---|------|----------|------|-------|\n"
         "| 10 | 1 | 3 | 10 | 100 |\n"
         "| 100 | 1 | 7 | 100 | 10,000 |\n"
         "| 1,000 | 1 | 10 | 1,000 | 1,000,000 |\n"
         "| 10,000 | 1 | 13 | 10,000 | 100,000,000 💀 |\n\n"
         "n=10,000 時 O(n²) 已經是一億次運算 — 那就是為什麼老師強調避免 O(n²)。\n\n"
         "**口訣**：\n"
         "- $O(1)$ 「一秒內」\n"
         "- $O(\\log n)$ 「翻倍只多一步」\n"
         "- $O(n)$ 「線性等比」\n"
         "- $O(n^2)$ 「資料翻倍時間 ×4」\n\n"
         "📎 想複習隨時點：" + cite("Big-O 速查表.md", "常見複雜度排序") + "。"),
    Turn(8, "ds101", 1004,
         "什麼是 stack 跟 queue？我又搞混了",
         "用兩張動圖說明最快：\n\n"
         "**Stack (LIFO 後進先出)**：像疊盤子，最後放上去的最先拿。\n\n"
         "```mermaid\n"
         "graph TD\n"
         "  push3[\"push 3\"] --> top3[\"Top: 3\"]\n"
         "  top3 --> mid2[\"2\"]\n"
         "  mid2 --> bot1[\"1 (Bottom)\"]\n"
         "  pop[\"pop returns 3\"]\n"
         "```\n\n"
         "**Queue (FIFO 先進先出)**：像排隊，先到先服務。\n\n"
         "```mermaid\n"
         "graph LR\n"
         "  enq[\"enqueue 4\"] --> Q[\"1, 2, 3, 4\"]\n"
         "  Q --> deq[\"dequeue returns 1\"]\n"
         "```\n\n"
         "**口訣**：Stack「上面進上面出」，Queue「一邊進另一邊出」。\n\n"
         "Python 對應（按 ▶ Run 看實際輸出）：\n"
         "```pyrun\n"
         "# Stack：用 list 即可\n"
         "stack = []\n"
         "stack.append(1); stack.append(2); stack.append(3)\n"
         "print('pop ->', stack.pop())  # 3 (最後進的最先出)\n"
         "\n"
         "# Queue：用 collections.deque\n"
         "from collections import deque\n"
         "q = deque()\n"
         "q.append(1); q.append(2); q.append(3)\n"
         "print('dequeue ->', q.popleft())  # 1 (最先進的最先出)\n"
         "```\n\n"
         "📎 操作複雜度對照：" + cite("Big-O 速查表.md", "常見資料結構操作") + "。"),
    Turn(12, "eng201", 1004,
         "老師發了 YouTube 影片要我看，但我看不太懂，能總結重點嗎？",
         "影片重點整理（thesis statement formula）：\n\n"
         '<iframe width="100%" height="280" src="https://www.youtube.com/embed/GRZiZ_BUbX0" '
         'title="How to Write a Thesis Statement" frameborder="0" allowfullscreen></iframe>\n\n'
         "**核心公式**：\n\n"
         "> Topic + Position + Reasons = Thesis\n\n"
         "舉例（重寫 'Technology is good'）：\n\n"
         "1. Topic: smartphone use among college students\n"
         "2. Position: harms academic performance\n"
         "3. Reasons: fragments attention, reduces sleep, replaces deep reading\n"
         "\n"
         "✅ Final thesis: *Excessive smartphone use among college students harms academic performance by fragmenting attention, reducing sleep, and replacing deep reading.*\n\n"
         "📎 自學講義：" + cite("Academic Writing Cheat Sheet.md", "Thesis Statement Formula") + "、段落結構 " + cite("Academic Writing Cheat Sheet.md", "Paragraph Structure: PIE") + "。"),

    # ─── E 張 (1005) — 跨域 ───
    Turn(5, "ipr101", 1005,
         "專利申請整個流程是什麼？我想看時間軸",
         "台灣發明專利從申請到核准平均 18-30 個月：\n\n"
         "```mermaid\n"
         "gantt\n"
         "  title 發明專利申請流程\n"
         "  dateFormat YYYY-MM-DD\n"
         "  section 申請階段\n"
         "  撰寫申請書 :a1, 2025-01-01, 30d\n"
         "  提交受理 :a2, after a1, 7d\n"
         "  section 審查階段\n"
         "  形式審查 :b1, after a2, 60d\n"
         "  公開（18個月） :b2, after a2, 540d\n"
         "  實體審查 :b3, after b2, 180d\n"
         "  section 核准\n"
         "  發給專利證書 :c1, after b3, 30d\n"
         "```\n\n"
         "**重點**：\n"
         "- 申請日 → 18 個月後**強制公開**（讓社會知道）\n"
         "- 公開後**才能**請求實體審查（要繳審查費）\n"
         "- 不請求實體審查，3 年內視為撤回 — 別忘了！\n\n"
         "📎 三要件詳解：" + cite("專利三要件詳解.md", "1 產業利用性") + "、" + cite("專利三要件詳解.md", "2 新穎性") + "、" + cite("專利三要件詳解.md", "3 進步性 (Inventive Step)") + "。"),
    Turn(11, "ipr101", 1005,
         "賠償計算的「合理權利金」要怎麼算？有公式嗎？",
         "三種計算方式（擇一最高者）：\n\n"
         "1. **侵權人所得利益**：$\\text{利益} = \\text{銷售額} \\times \\text{毛利率}$\n"
         "2. **權利人損失**：$\\text{損失} = (\\text{無侵權銷售} - \\text{實際銷售}) \\times \\text{單位利潤}$\n"
         "3. **合理權利金**（License Analogy）：$\\text{合理權利金} = \\text{侵權銷售額} \\times \\text{產業權利金率}$\n\n"
         "產業權利金率參考：\n"
         "| 產業 | 典型權利金率 |\n"
         "|------|-------------|\n"
         "| 製藥 | 5-10% |\n"
         "| 半導體 | 1-5% |\n"
         "| 軟體 | 10-25% |\n"
         "| 機械 | 2-7% |\n\n"
         "舉例：某半導體公司侵權銷售 1 億元，採 3% 權利金率 → 賠償 300 萬。\n\n"
         "📎 案例研究：" + cite("專利三要件詳解.md", "經典案例 Apple 滑動解鎖", "🍎 Apple v Samsung") + "。"),
    Turn(14, "ds101", 1004,
         "老師說 list.insert(0, x) 比 deque.appendleft(x) 慢很多，差多少？我想實際看數字",
         "好機會直接量 — 按 ▶ Run 跑一次，數字會告訴你答案：\n\n"
         "```pyrun\n"
         "import time\n"
         "from collections import deque\n"
         "\n"
         "N = 50000\n"
         "\n"
         "# list.insert(0, x) — 每次要把後面元素整體往後挪 → O(n)\n"
         "lst = []\n"
         "t0 = time.perf_counter()\n"
         "for i in range(N):\n"
         "    lst.insert(0, i)\n"
         "list_ms = (time.perf_counter() - t0) * 1000\n"
         "\n"
         "# deque.appendleft(x) — 雙端佇列 → O(1)\n"
         "dq = deque()\n"
         "t0 = time.perf_counter()\n"
         "for i in range(N):\n"
         "    dq.appendleft(i)\n"
         "deque_ms = (time.perf_counter() - t0) * 1000\n"
         "\n"
         "print(f'list.insert(0, x) x {N:,}: {list_ms:.0f} ms')\n"
         "print(f'deque.appendleft(x) x {N:,}: {deque_ms:.0f} ms')\n"
         "print(f'差距: {list_ms / deque_ms:.0f}x')\n"
         "```\n\n"
         "通常 list 版會慢上 100-300 倍 — 這就是「O(n²) vs O(n)」攤銷成本累積的真實感受。\n\n"
         "📎 對照表：" + cite("Big-O 速查表.md", "常見資料結構操作") + "。"),
    Turn(13, "ipr101", 1005,
         "我想看老師指定的專利入門影片",
         "好，影片直接嵌進來：\n\n"
         '<iframe width="100%" height="320" src="https://www.youtube.com/embed/ETIKnXkfhVI" '
         'title="Patent Basics" frameborder="0" allowfullscreen></iframe>\n\n'
         "**5 分鐘 takeaway**：\n"
         "- 專利保護**技術方案**，不保護「想法」本身\n"
         "- 一個發明可分**發明專利、新型專利、設計專利**\n"
         "- 拿到專利就有「排他權」 — 別人沒授權做就算侵權\n\n"
         "📎 三要件對應：" + cite("專利三要件詳解.md", "三要件審查順序") + "。"),
    Turn(15, "eng201", 1005,
         "可以幫我看一下 academic writing 的段落結構（PIE）是什麼意思？",
         "**PIE = Point + Illustration + Explanation**，是學術段落的黃金結構：\n\n"
         "```mermaid\n"
         "graph TD\n"
         "  P[\"Point — 段落主張一句話\"] --> I[\"Illustration — 證據/例子/數據\"]\n"
         "  I --> E[\"Explanation — 分析證據如何支持主張\"]\n"
         "  E --> N[\"Next paragraph\"]\n"
         "```\n\n"
         "**❌ 反例**（只有 P 沒有 I/E）：\n"
         "> Social media affects mental health. Many studies show this. Therefore it is harmful.\n\n"
         "**✅ 正例**（完整 PIE）：\n"
         "> *(P)* Social media correlates with increased adolescent depression. *(I)* A 2019 JAMA study of 6,500 US teens found that those using SNS > 3 hrs/day had 2× odds of depressive symptoms (Riehm et al., 2019). *(E)* The mechanism likely involves social comparison and sleep disruption from late-night scrolling, both established depression risk factors.\n\n"
         "📎 配對閱讀：" + cite("Academic Writing Cheat Sheet.md", "Paragraph Structure: PIE") + "、" + cite("Academic Writing Cheat Sheet.md", "Common Academic Phrases") + "。"),

    # ─── HTML widgets — 內嵌可視化卡片 / 互動元件 ───
    Turn(6, "ds101", 1004,
         "list.insert(0, x) 那個整體往後挪可以畫出來嗎？我看不出實際發生什麼",
         "好，給你一個視覺化卡片：\n\n"
         '<div style="background:#0f172a;border-radius:12px;padding:20px;margin:12px 0;font-family:system-ui">\n'
         '  <div style="color:#94a3b8;font-size:11px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:14px">Before — list = [a, b, c, d]</div>\n'
         '  <div style="display:flex;gap:6px">\n'
         '    <div style="flex:1;padding:14px;background:#1e293b;color:#e2e8f0;text-align:center;border-radius:6px;font-weight:700">a</div>\n'
         '    <div style="flex:1;padding:14px;background:#1e293b;color:#e2e8f0;text-align:center;border-radius:6px;font-weight:700">b</div>\n'
         '    <div style="flex:1;padding:14px;background:#1e293b;color:#e2e8f0;text-align:center;border-radius:6px;font-weight:700">c</div>\n'
         '    <div style="flex:1;padding:14px;background:#1e293b;color:#e2e8f0;text-align:center;border-radius:6px;font-weight:700">d</div>\n'
         '  </div>\n'
         '  <div style="text-align:center;color:#fbbf24;margin:14px 0;font-size:13px;font-weight:700">↓ list.insert(0, X) 要把 a/b/c/d 都往後挪 1 格</div>\n'
         '  <div style="color:#94a3b8;font-size:11px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:14px">After</div>\n'
         '  <div style="display:flex;gap:6px">\n'
         '    <div style="flex:1;padding:14px;background:#22c55e;color:#fff;text-align:center;border-radius:6px;font-weight:700;box-shadow:0 0 0 2px #22c55e">X</div>\n'
         '    <div style="flex:1;padding:14px;background:#475569;color:#e2e8f0;text-align:center;border-radius:6px;font-weight:700">a ←</div>\n'
         '    <div style="flex:1;padding:14px;background:#475569;color:#e2e8f0;text-align:center;border-radius:6px;font-weight:700">b ←</div>\n'
         '    <div style="flex:1;padding:14px;background:#475569;color:#e2e8f0;text-align:center;border-radius:6px;font-weight:700">c ←</div>\n'
         '    <div style="flex:1;padding:14px;background:#475569;color:#e2e8f0;text-align:center;border-radius:6px;font-weight:700">d ←</div>\n'
         '  </div>\n'
         '  <div style="margin-top:16px;padding:10px;background:#fbbf24;color:#451a03;border-radius:6px;font-size:12px;font-weight:600">📌 N 個元素就要挪 N 次 → O(N) 成本</div>\n'
         '</div>\n\n'
         "deque.appendleft 不需要挪，因為它是雙向鏈，加一個 head 指針就好 → O(1)。\n\n"
         "📎 表格對照：" + cite("Big-O 速查表.md", "常見資料結構操作") + "。"),

    Turn(8, "mk201", 1002,
         "可以給我一個完整 SWOT 卡片畫面嗎？我要拍照貼期中報告",
         "拿這個 SWOT 矩陣去用：\n\n"
         '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0;font-family:system-ui">\n'
         '  <div style="background:linear-gradient(135deg,#10b981,#059669);color:#fff;padding:16px;border-radius:10px">\n'
         '    <div style="font-size:11px;font-weight:800;opacity:0.85;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px">Strengths · 內部優勢</div>\n'
         '    <ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.6">\n'
         '      <li>全球品牌力（Top 100 brand value）</li>\n'
         '      <li>第三空間定位深植人心</li>\n'
         '      <li>會員 app 30K+ 訂單/日</li>\n'
         '    </ul>\n'
         '  </div>\n'
         '  <div style="background:linear-gradient(135deg,#ef4444,#dc2626);color:#fff;padding:16px;border-radius:10px">\n'
         '    <div style="font-size:11px;font-weight:800;opacity:0.85;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px">Weaknesses · 內部弱點</div>\n'
         '    <ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.6">\n'
         '      <li>過度依賴美國市場（70% 營收）</li>\n'
         '      <li>單杯價格高，不利低價戰</li>\n'
         '      <li>品項擴張易稀釋核心定位</li>\n'
         '    </ul>\n'
         '  </div>\n'
         '  <div style="background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;padding:16px;border-radius:10px">\n'
         '    <div style="font-size:11px;font-weight:800;opacity:0.85;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px">Opportunities · 外部機會</div>\n'
         '    <ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.6">\n'
         '      <li>中國市場下沉到三線城市</li>\n'
         '      <li>冷飲 / 茶飲產品線拓展</li>\n'
         '      <li>RTD 即飲咖啡零售通路</li>\n'
         '    </ul>\n'
         '  </div>\n'
         '  <div style="background:linear-gradient(135deg,#f59e0b,#d97706);color:#fff;padding:16px;border-radius:10px">\n'
         '    <div style="font-size:11px;font-weight:800;opacity:0.85;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px">Threats · 外部威脅</div>\n'
         '    <ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.6">\n'
         '      <li>瑞幸低價 + 高速展店</li>\n'
         '      <li>原物料（咖啡豆 / 牛奶）通膨</li>\n'
         '      <li>Z 世代轉向手搖茶</li>\n'
         '    </ul>\n'
         '  </div>\n'
         '</div>\n\n'
         "**判讀順序**：先 W/T 找痛點、再 S/O 找機會 — 把 W 配 O 變成「修復策略」、S 配 T 變成「防禦策略」。\n\n"
         "📎 對照框架：" + cite("STP 框架完整指南.md", "Positioning 市場定位") + "。"),

    Turn(10, "chm301", 1003,
         "可以做一個熱力學公式的記憶卡嗎？我每次開卷都翻不到",
         "用可摺疊小卡，要哪個展開哪個：\n\n"
         '<div style="display:flex;flex-direction:column;gap:6px;margin:12px 0;font-family:system-ui">\n'
         '  <details style="background:#1e293b;border-left:4px solid #6366f1;border-radius:6px;padding:10px 14px">\n'
         '    <summary style="cursor:pointer;color:#e2e8f0;font-weight:700;font-size:14px">📐 第一定律 ΔU = q + w</summary>\n'
         '    <div style="margin-top:10px;color:#cbd5e1;font-size:13px;line-height:1.6">\n'
         '      <div>q &gt; 0：系統吸熱；q &lt; 0：系統放熱</div>\n'
         '      <div>w &gt; 0：環境對系統做功；w &lt; 0：系統對環境做功</div>\n'
         '      <div style="margin-top:6px;color:#fbbf24">口訣：「進來算正」</div>\n'
         '    </div>\n'
         '  </details>\n'
         '  <details style="background:#1e293b;border-left:4px solid #10b981;border-radius:6px;padding:10px 14px">\n'
         '    <summary style="cursor:pointer;color:#e2e8f0;font-weight:700;font-size:14px">🔥 等溫可逆膨脹</summary>\n'
         '    <div style="margin-top:10px;color:#cbd5e1;font-size:13px;line-height:1.6">\n'
         '      <div>w = −nRT ln(V₂/V₁)</div>\n'
         '      <div>q = −w（因為 ΔU = 0）</div>\n'
         '    </div>\n'
         '  </details>\n'
         '  <details style="background:#1e293b;border-left:4px solid #f59e0b;border-radius:6px;padding:10px 14px">\n'
         '    <summary style="cursor:pointer;color:#e2e8f0;font-weight:700;font-size:14px">❄️ 絕熱可逆</summary>\n'
         '    <div style="margin-top:10px;color:#cbd5e1;font-size:13px;line-height:1.6">\n'
         '      <div>q = 0，所以 ΔU = w = nCv·ΔT</div>\n'
         '      <div>PV<sup>γ</sup> = const，TV<sup>γ-1</sup> = const</div>\n'
         '      <div style="margin-top:6px;color:#fbbf24">γ = Cp/Cv（單原子 5/3、雙原子 7/5）</div>\n'
         '    </div>\n'
         '  </details>\n'
         '  <details style="background:#1e293b;border-left:4px solid #ec4899;border-radius:6px;padding:10px 14px">\n'
         '    <summary style="cursor:pointer;color:#e2e8f0;font-weight:700;font-size:14px">📊 自由能判據</summary>\n'
         '    <div style="margin-top:10px;color:#cbd5e1;font-size:13px;line-height:1.6">\n'
         '      <div>等溫等壓：ΔG &lt; 0 自發、=0 平衡、&gt;0 非自發</div>\n'
         '      <div>ΔG = ΔH − T·ΔS</div>\n'
         '    </div>\n'
         '  </details>\n'
         '</div>\n\n'
         "點任一張展開細節 — 上場考前複習用。\n\n"
         "📎 完整公式集：" + cite("熱力學公式總覽.md", "不同過程的計算") + "。"),

    Turn(9, "ds101", 1004,
         "BST 我看圖看不懂，能不能讓我自己加節點看會長怎樣？",
         "可以，這個小工具丟你親手玩 — 輸入數字按 ➕ 插入：\n\n"
         '<iframe src="/api/backend/static/widgets/bst-builder.html" '
         'style="width:100%;height:420px;border:0;border-radius:10px;background:#0f172a"></iframe>\n\n'
         "**試試這幾組**：\n"
         "1. 50, 30, 70, 20, 40 → 平衡的小樹，高度 = 3\n"
         "2. 1, 2, 3, 4, 5 → 退化成單邊鏈（高度 = 5），這就是 quicksort 最差的觸發條件\n"
         "3. 按 🎲 隨機 7 個 看真實樹形\n\n"
         "右上角數字會即時告訴你「節點數 vs 高度 vs log₂n」差距 — 這就是平衡 vs 退化的視覺證據。\n\n"
         "📎 對照理論：" + cite("Big-O 速查表.md", "常見資料結構操作") + "。"),

    Turn(11, "chm301", 1003,
         "PV=nRT 我背但不真的懂。固定溫度時把 P 變大 V 真的會等比例變小嗎？",
         "你自己滑滑看 — 拖 P 看 V 怎麼變，氣球會一起改變大小：\n\n"
         '<iframe src="/api/backend/static/widgets/ideal-gas.html" '
         'style="width:100%;height:560px;border:0;border-radius:10px;background:#0f172a"></iframe>\n\n'
         "**操作建議**：\n"
         "1. 先選「解算對象 = V」固定 n=1, T=273，把 P 從 1 → 2 → 5 → 10 atm，看 V 等比反向縮小（P 翻倍 V 減半 = Boyle's law）\n"
         "2. 改成「解算對象 = T」固定 P=1, V=22.4，把 n 從 1 → 2，看 T 直接除 2（更多氣體分子要更低溫才能維持同壓力同體積）\n"
         "3. 看氣球：T 越高顏色越紅、V 越大球越大\n\n"
         "📎 公式背景：" + cite("熱力學公式總覽.md", "第一定律") + "。"),

    Turn(15, "eng201", 1004,
         "APA 跟 MLA 我每次都記反，能給我一個比較卡嗎？",
         "拿這張並列卡：\n\n"
         '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0;font-family:system-ui">\n'
         '  <div style="border:2px solid #3b82f6;border-radius:10px;padding:14px;background:#eff6ff">\n'
         '    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">\n'
         '      <div style="width:32px;height:32px;background:#3b82f6;color:#fff;border-radius:6px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:13px">APA</div>\n'
         '      <div style="font-size:11px;color:#1e3a8a;font-weight:700;letter-spacing:0.05em">SOCIAL · BEHAVIORAL</div>\n'
         '    </div>\n'
         '    <div style="font-size:12px;line-height:1.7;color:#1e293b">\n'
         '      <div><strong>Inline</strong>：(Smith, 2020)</div>\n'
         '      <div><strong>Reference</strong>：Smith, J. (2020). <em>Title</em>. Publisher.</div>\n'
         '      <div style="margin-top:8px;color:#475569;font-size:11px">📌 強調「年份」 → 重時效</div>\n'
         '    </div>\n'
         '  </div>\n'
         '  <div style="border:2px solid #ef4444;border-radius:10px;padding:14px;background:#fef2f2">\n'
         '    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">\n'
         '      <div style="width:32px;height:32px;background:#ef4444;color:#fff;border-radius:6px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:13px">MLA</div>\n'
         '      <div style="font-size:11px;color:#7f1d1d;font-weight:700;letter-spacing:0.05em">HUMANITIES</div>\n'
         '    </div>\n'
         '    <div style="font-size:12px;line-height:1.7;color:#1e293b">\n'
         '      <div><strong>Inline</strong>：(Smith 25)</div>\n'
         '      <div><strong>Reference</strong>：Smith, John. <em>Title</em>. Publisher, 2020.</div>\n'
         '      <div style="margin-top:8px;color:#475569;font-size:11px">📌 強調「頁碼」 → 重原文</div>\n'
         '    </div>\n'
         '  </div>\n'
         '</div>\n\n'
         "**選擇法則**：寫商管 / 心理 / 社科 → APA；寫文學 / 哲學 / 歷史 → MLA。EduInsight 預設 APA。\n\n"
         "📎 全格式表：" + cite("Academic Writing Cheat Sheet.md", "Citation Format Comparison") + "。"),
]

# Merge into main list so the rest of main() handles them uniformly.
CONVERSATIONS = CONVERSATIONS + RICH_CONVERSATIONS


# ----------------------------------------------------------------------
# Multi-turn study sessions: one session = several Q+A exchanges on the
# same topic. These create deep, realistic chat threads when the user
# opens any individual session.
# ----------------------------------------------------------------------

class MultiTurnSession(NamedTuple):
    week: int
    course: str
    student: int
    title: str
    turns: list[tuple[str, str]]  # (question, answer) pairs


MULTITURN_SESSIONS: list[MultiTurnSession] = [
    # ─── D 李 (1004) — DS101 鏈結串列深度補課 ───
    MultiTurnSession(5, "ds101", 1004, "鏈結串列從零複習",
        turns=[
            ("我完全不懂鏈結串列，老師講得太快了，可以從最基本開始嗎？",
             "好，從最基本開始。\n\n**Node 是什麼？**\n\n```pyrun\nclass Node:\n    def __init__(self, val):\n        self.val = val      # 存資料\n        self.next = None    # 指向下一個 Node\n\nprint('Node class 已定義')\n```\n\n一個 Node = 一節「火車車廂」，裡面有貨（val）+ 連到下一節的鉤子（next）。按 ▶ Run 把 class 載進來，下一段才能用。"),
            ("那一整條 linked list 怎麼接起來？",
             "用一個 head 指標指向第一節：\n\n```mermaid\ngraph LR\n  head --> A[1] --> B[2] --> C[3] --> N[None]\n```\n\n```pyrun\nhead = Node(1)\nhead.next = Node(2)\nhead.next.next = Node(3)\nprint('head ->', head.val, '->', head.next.val, '->', head.next.next.val)\n```"),
            ("那要找第三個值要怎麼做？",
             "從 head 走兩步：\n\n```pyrun\ncurr = head\nfor _ in range(2):\n    curr = curr.next\nprint('第 3 個值 =', curr.val)  # 3\n```\n\n所以查找第 i 個 = $O(i)$，跟陣列的 $O(1)$ 不同 — 這就是鏈結串列「沒有索引」的代價。"),
            ("那為什麼還要用鏈結串列？陣列不就好了？",
             "因為**插入/刪除快**。陣列在中間插入要把後面的元素整體往後挪 $O(n)$；鏈結串列只要改兩個 next 指針 $O(1)$。\n\n```mermaid\ngraph LR\n  A[1] --> B[2] --> C[3]\n  A2[1] --> X[NEW] --> B2[2] --> C2[3]\n```\n\n**口訣**：\n- 常**讀**取 → 用陣列\n- 常**插刪** → 用鏈結"),
        ]),

    # ─── A 陳 (1001) — DS101 advanced ───
    MultiTurnSession(9, "ds101", 1001, "Hash Table 衝突處理深入",
        turns=[
            ("Hash Table 衝突處理有哪幾種？實務上怎麼選？",
             "三大主流：\n\n| 策略 | 平均查找 | 最差 | 記憶體效率 |\n|---|---|---|---|\n| Separate Chaining | $O(1+\\alpha)$ | $O(n)$ | 中 |\n| Open Addressing | $O(\\frac{1}{1-\\alpha})$ | $O(n)$ | 高 |\n| Robin Hood Hashing | $O(1+\\alpha)$ | 接近 $O(1+\\alpha)$ | 高 |\n\n$\\alpha$ = load factor = $n/m$。"),
            ("Robin Hood Hashing 是什麼？沒聽過",
             "Open addressing 的變體 — **「劫富濟貧」**：插入時若新元素的 probe 距離大於現有元素，就把現有元素「踢走」往後找。\n\n好處：probe 距離分布均勻，最差查找接近平均，方差小。Rust 的 HashMap 在 1.36 之前就是用這個。"),
            ("那 Java HashMap 為什麼用 chaining + 紅黑樹？",
             "Java 8 改採「混合策略」：鏈長 < 8 用鏈表（簡單），≥ 8 自動轉紅黑樹避免最差 $O(n)$。\n\n為什麼是 8？泊松分布計算：在 load factor 0.75 下，鏈長達 8 的機率 < 1e-6，所以平時不會啟用樹化的開銷。"),
        ]),

    # ─── B 林 (1002) — MK201 期中專案 ───
    MultiTurnSession(11, "mk201", 1002, "幫我做星巴克 SWOT 分析作業",
        turns=[
            ("老師要我做星巴克的 SWOT，但我寫了三遍都被退，可以幫我看哪裡錯嗎？",
             "可以，先給我看你寫的三點 Strengths 跟 Weaknesses 我們一起檢查。\n\n但先講重點：**SWOT 必須區分「企業內部 (S/W)」vs「外部環境 (O/T)」**。判斷小技巧：『換一家公司也還是這樣 = 外部』。"),
            ("我寫 S: 全球品牌力強。W: 競爭激烈。O: 數位轉型。T: 經濟衰退",
             "✅ S 對：品牌力是內部資產。\n\n❌ W 錯：「競爭激烈」是**外部 Threat**，所有咖啡業者都面對 — 換成「過度依賴美國市場（70% 營收）」這種**只有星巴克才有**的弱點。\n\n✅ O 部分對：「數位轉型」太籠統，改成「app 訂單已佔 26% 美國訂單，仍有成長空間」。\n\n✅ T 對：經濟衰退影響非必需消費。"),
            ("為什麼「依賴美國市場」是 W 而不是 T？",
             "因為這是**星巴克的選擇**（內部）— 是它的拓店策略造成的，可以改變（多投資中國）。而「經濟衰退」是宏觀環境，星巴克改不了。\n\n判斷公式：\n```mermaid\ngraph TD\n  Q[這個因素] --> A{企業可控?}\n  A -->|可控| B{對企業有利?}\n  A -->|不可控| C{對企業有利?}\n  B -->|是| S[Strength]\n  B -->|否| W[Weakness]\n  C -->|是| O[Opportunity]\n  C -->|否| T[Threat]\n```"),
        ]),

    # ─── C 王 (1003) — CHM301 期中考前複習 ───
    MultiTurnSession(7, "chm301", 1003, "熱力學第一定律題目演練",
        turns=[
            ("題目：1 mol 理想氣體在 300K 等溫可逆膨脹從 1L 到 10L，求 q 跟 w",
             "等溫可逆膨脹的功：\n\n$$w = -nRT \\ln \\frac{V_2}{V_1}$$\n\n代入 $n=1, R=8.314, T=300, V_2/V_1 = 10$：\n\n$$w = -1 \\times 8.314 \\times 300 \\times \\ln 10 \\approx -5743 \\text{ J}$$\n\n等溫 $\\Delta U = 0$，所以 $q = -w = +5743 \\text{ J}$（系統吸熱）。"),
            ("為什麼等溫 ΔU = 0？",
             "因為理想氣體的內能只跟溫度有關（$U = \\frac{3}{2}nRT$ 對單原子）。\n\n$dU = C_v dT$，$T$ 不變 ⇒ $dU = 0$。\n\n```mermaid\ngraph LR\n  A[\"等溫\"] --> B[\"dT = 0\"]\n  B --> C[\"dU = Cv·dT = 0\"]\n  C --> D[\"q = -w 由第一定律\"]\n```"),
            ("如果改成絕熱可逆呢？",
             "絕熱：$q = 0$，所以 $\\Delta U = w$。\n\n用 $TV^{\\gamma-1} = \\text{const}$ 求終溫，再 $\\Delta U = nC_v\\Delta T$。\n\n單原子 $\\gamma = 5/3$：$T_2 = T_1 (V_1/V_2)^{2/3} = 300 \\times 0.1^{0.667} \\approx 64.6 \\text{ K}$。\n\n$\\Delta U = 1 \\times \\frac{3}{2} \\times 8.314 \\times (64.6-300) \\approx -2935 \\text{ J}$。\n\n所以 $w = -2935 \\text{ J}$（系統對環境做功，內能下降）。"),
        ]),

    # ─── E 張 (1005) — IPR101 案例討論 ───
    MultiTurnSession(14, "ipr101", 1005, "Apple vs Samsung 滑動解鎖案例",
        turns=[
            ("老師上課提到 Apple v. Samsung 滑動解鎖案，可以幫我整理重點嗎？",
             "**案件背景**：Apple 在 2010 年取得 US Patent 8,046,721（'721 專利）— 滑動解鎖手勢。\n\n2012 年告 Samsung 侵權，地方法院判 Samsung 賠 1.2 億美元；後來連環上訴。\n\n爭議核心：滑動解鎖是否「顯而易見」？該領域的工程師看到 NeoNode N1m 的 sweep-to-unlock，能否「輕易完成」。\n\n```mermaid\ntimeline\n  2005 : Apple 提交申請\n  2010 : 'Apple 獲准 US 8,046,721'\n  2012 : Apple 告 Samsung\n  2014 : 一審 Samsung 賠 1.2 億美元\n  2017 : 上訴 Apple 勝訴\n```"),
            ("最後法院認定進步性的依據是什麼？",
             "聯邦巡迴法院強調**次要考量因素 (secondary considerations)**：\n\n1. **長期未獲解決的需求**（long-felt unmet need）：智慧手機解鎖體驗多年來都不夠直覺\n2. **業界讚譽**：iPhone 上市後滑動解鎖被業界認為是革命性\n3. **商業成功**：iPhone 銷量爆炸\n4. **競爭者抄襲**：Samsung 自己內部文件顯示「我們需要做出 iPhone-like 體驗」\n\n這些反推「不顯而易見」 — 否則為什麼這麼久沒人想到？"),
            ("那台灣有類似的判決嗎？",
             "有，HTC vs Apple 在台灣也是類似戰爭。台灣智慧財產法院在 102 年度民專訴字第 47 號中也用類似的次要考量分析。\n\n台灣法的不同點：\n- 著重「同業普通技術人員」的判斷（§22 II）\n- 商業成功**不能單獨**證明進步性，要結合技術差異\n- 法院較少採信「業界讚譽」這類軟性證據\n\n所以同一個專利在台美的命運可能不同。"),
        ]),
]


def _seed_multiturn_sessions(store, sess_db) -> tuple[int, int]:
    """Returns (sessions_added, messages_added)."""
    sess_n = 0
    msg_n = 0
    for i, sess in enumerate(MULTITURN_SESSIONS):
        uid = f"moodle:{sess.student}"
        ts = week_ts(sess.week)
        sid = f"sim-mt-{sess.course}-{sess.student}-w{sess.week}-{i}"

        with sessions_mod._db() as conn:  # noqa: SLF001
            conn.execute(
                "INSERT OR REPLACE INTO chat_sessions "
                "(session_id, moodle_user_id, course_id, title, created_at, last_msg_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sid, sess.student, sess.course, sess.title, ts, ts + 60 * len(sess.turns) * 2),
            )
            conn.commit()
        sess_n += 1

        with store._lock:  # noqa: SLF001
            conn = store._get_conn()  # noqa: SLF001
            for j, (q, a) in enumerate(sess.turns):
                t_user = ts + j * 120
                t_asst = ts + j * 120 + 60
                conn.execute(
                    "INSERT INTO messages (user_id, session_id, role, content, speaker_name, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (uid, sid, "user", q, "", t_user),
                )
                conn.execute(
                    "INSERT INTO messages (user_id, session_id, role, content, speaker_name, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (uid, sid, "assistant", a, "", t_asst),
                )
                msg_n += 2
            conn.commit()
    return sess_n, msg_n


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

    # 2. 寫入完整對話歷史（messages 表 + chat_sessions metadata）
    sessions_mod.init_sessions_table()
    store = mem._store  # noqa: SLF001

    # Idempotency: clear all previously-seeded `sim-*` rows before re-inserting
    with sessions_mod._db() as conn:  # noqa: SLF001
        conn.execute("DELETE FROM chat_sessions WHERE session_id LIKE 'sim-%'")
        conn.commit()
    with store._lock:  # noqa: SLF001
        conn = store._get_conn()  # noqa: SLF001
        conn.execute("DELETE FROM messages WHERE session_id LIKE 'sim-%'")
        conn.commit()
    print("Cleared previous sim-* sessions/messages for idempotent re-seed")

    msg_count = 0
    sess_count = 0
    for i, t in enumerate(CONVERSATIONS):
        uid = f"moodle:{t.student}"
        ts = week_ts(t.week)
        sid = f"sim-{t.course}-{t.student}-w{t.week}-{i}"
        title = (t.question[:30] + "…") if len(t.question) > 30 else t.question

        # session metadata so frontend sidebar lists it
        with sessions_mod._db() as conn:  # noqa: SLF001
            conn.execute(
                "INSERT OR REPLACE INTO chat_sessions "
                "(session_id, moodle_user_id, course_id, title, created_at, last_msg_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sid, t.student, t.course, title, ts, ts + 60),
            )
            conn.commit()
        sess_count += 1

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
    print(f"Stored {msg_count} messages across {sess_count} chat_sessions")

    # 2b. 多輪深度對話 sessions
    mt_sess, mt_msg = _seed_multiturn_sessions(store, sessions_mod)
    print(f"Stored {mt_msg} multi-turn messages across {mt_sess} deep-dive sessions")

    # 3. 統計
    by_student: dict[int, int] = {}
    for t in CONVERSATIONS:
        by_student[t.student] = by_student.get(t.student, 0) + 1
    for sid, n in sorted(by_student.items()):
        print(f"  Student {sid}: {n} conversations")


if __name__ == "__main__":
    main()
