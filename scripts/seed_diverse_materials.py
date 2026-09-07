"""Seed diverse-format demo materials for all 5 courses.

Each course gets 2-3 materials of varying formats (markdown article,
plain-text handout, YouTube video) on top of the existing PDFs.

Run after `seed_semester_conversations.py` once the backend is up.
"""

from __future__ import annotations

from pathlib import Path

from litemem import Memory

from eduinsight.config import settings
from eduinsight.rag import CourseRAG
from eduinsight.documents import (
    ParsedMarkdown,
    pdf_to_markdown,  # noqa: F401  (kept for parity with rest of pipeline)
    split_markdown_by_headings,
    text_to_markdown,
)


# (course_id, filename, body_markdown)
MARKDOWN_MATERIALS: list[tuple[str, str, str]] = [
    # ── DS101 資料結構 ──
    ("ds101", "Big-O 速查表.md", """# Big-O 速查表

複雜度成長視覺化 — 適合考前快速複習。

## 常見複雜度排序

| 符號 | 名稱 | 例子 |
|------|------|------|
| $O(1)$ | 常數 | array index access |
| $O(\\log n)$ | 對數 | binary search, balanced BST |
| $O(n)$ | 線性 | linear scan |
| $O(n \\log n)$ | 線性對數 | mergesort, heapsort |
| $O(n^2)$ | 平方 | bubble sort, naive matmul |
| $O(2^n)$ | 指數 | naive recursive Fibonacci |
| $O(n!)$ | 階乘 | brute-force TSP |

## 常見資料結構操作

| 操作 | Array | Linked List | Hash Table | Balanced BST |
|------|-------|-------------|------------|--------------|
| 查找 | O(n) | O(n) | O(1) avg | O(log n) |
| 索引 | O(1) | O(n) | N/A | N/A |
| 插入頭 | O(n) | O(1) | O(1) avg | O(log n) |
| 插入尾 | O(1) amortized | O(1) | O(1) avg | O(log n) |
| 刪除 | O(n) | O(1) given node | O(1) avg | O(log n) |

## 演算法決策樹

```mermaid
graph TD
  S["輸入規模"]
  S -->|"n &lt; 50"| Bf["暴力解 O(n²) OK"]
  S -->|"n &lt; 10⁶"| LL["O(n log n)"]
  S -->|"n &lt; 10⁹"| L["O(n) 或 O(log n)"]
  S -->|"n &gt; 10⁹"| O["O(log n) 或 O(1) 或 平行化"]
```

## 排序演算法選用指南

- **資料近乎排好** → Insertion sort 或 Timsort
- **需要穩定排序** → Mergesort 或 Timsort
- **記憶體受限** → Quicksort 或 Heapsort（原地）
- **資料分布範圍小** → Counting sort 或 Radix sort
"""),

    ("ds101", "作業說明 (Recursion).txt", """遞迴練習作業

繳交期限
本作業需在週五 23:59 前繳交至 Moodle 系統

學習目標
理解遞迴的兩個必要條件：基底情況 base case 與遞迴規則 recursive case
能寫出簡單遞迴函式並分析時間空間複雜度
理解 stack overflow 的成因並能用 tail recursion 或 iterative 解法避免

題目一 階乘
寫一個函式 factorial(n) 計算 n! 並分析時間與空間複雜度

題目二 費氏數列
寫遞迴版本 fib(n) 後測試 fib(40) 看執行多久
然後改寫成 memoization 版本比較速度差異
這題會讓你親身感受 O(2^n) 的恐怖

題目三 河內塔
寫 hanoi(n, from, to, via) 印出 n 個盤子從 from 移到 to 的所有步驟
分析步驟數的數學公式並計算 n=20 時要多少步

題目四 二元樹高度
給定一棵二元樹的根節點 寫遞迴函式 height(root) 計算樹的高度
什麼情況下這個遞迴會 stack overflow

評分標準
正確性 60 分 各題給定測資能通過
複雜度分析 25 分 每題都要附上時間空間複雜度推導
程式風格 15 分 命名清楚 適當註解
"""),

    # ── MK201 行銷管理 ──
    ("mk201", "STP 框架完整指南.md", """# STP 框架完整指南

從區隔到定位的三步驟，行銷策略的基石。

## Segmentation 市場區隔

把整體市場切成幾個有意義的子群體。

### 四大區隔變數

| 變數 | 例子 |
|------|------|
| 地理 | 都會 vs 鄉村、北/中/南台灣 |
| 人口統計 | 年齡、性別、收入、教育 |
| 心理 | 生活風格、價值觀、人格 |
| 行為 | 使用頻率、品牌忠誠、利益追求 |

### 有效區隔的條件

```mermaid
graph LR
  M[Measurable 可衡量] --> S[Substantial 規模夠大]
  S --> A[Accessible 可接觸]
  A --> D[Differentiable 可區別]
  D --> Ac[Actionable 可行動]
```

## Targeting 目標市場

從區隔中選擇要服務的對象。三種策略：

1. **無差異行銷**：所有區隔同樣對待（可口可樂早期）
2. **差異化行銷**：每個區隔用不同 4P（豐田 Camry/Lexus）
3. **集中行銷**：only 一個區隔（勞力士只做高端）

## Positioning 市場定位

在目標客群心智裡建立差異化形象。

### 知覺地圖（Perceptual Map）

選兩個顧客最在意的屬性畫成 2D 圖：

```mermaid
quadrantChart
  title 手機品牌定位
  x-axis 低價 --> 高價
  y-axis 低性能 --> 高性能
  quadrant-1 高端高性能
  quadrant-2 高性能但便宜
  quadrant-3 低性能低價
  quadrant-4 高價但低性能
  iPhone: [0.85, 0.9]
  Samsung S: [0.75, 0.85]
  小米: [0.4, 0.7]
  紅米: [0.2, 0.5]
  Nokia 經典: [0.15, 0.2]
```

### Positioning Statement 公式

> 對 [target] 來說，[brand] 是 [category]，因為 [point of difference]。

範例：
> 對忙碌的都會白領來說，星巴克是第三空間，因為它提供舒適的工作環境而非單純咖啡。
"""),

    # ── CHM301 物理化學 ──
    ("chm301", "熱力學公式總覽.md", """# 熱力學公式總覽

期中考重點公式整理。

## 第一定律

$$\\Delta U = q + w$$

- $q > 0$: 系統吸熱
- $w > 0$: 環境對系統做功

## 不同過程的計算

| 過程 | $q$ | $w$ | $\\Delta U$ |
|------|-----|-----|-------------|
| 等溫可逆 | $-w$ | $-nRT \\ln(V_2/V_1)$ | 0 |
| 絕熱可逆 | 0 | $\\Delta U$ | $nC_v\\Delta T$ |
| 等容 | $nC_v\\Delta T$ | 0 | $nC_v\\Delta T$ |
| 等壓 | $nC_p\\Delta T$ | $-P\\Delta V$ | $nC_v\\Delta T$ |

## 熵的兩種定義

熱力學定義：

$$dS = \\frac{dq_{rev}}{T}$$

統計定義：

$$S = k_B \\ln W$$

## 第二定律

$$\\Delta S_{universe} \\geq 0$$

可逆過程取等號，不可逆過程嚴格大於。

## 自由能判據

| 條件 | 判據 |
|------|------|
| 等溫等容 | $\\Delta A < 0$ 自發 |
| 等溫等壓 | $\\Delta G < 0$ 自發 |

```mermaid
graph TD
  H[H焓變] --> G[ΔG = ΔH - TΔS]
  S[S熵變] --> G
  T[T溫度] --> G
  G -->|< 0| Sp[自發]
  G -->|= 0| Eq[平衡]
  G -->|> 0| Ns[非自發]
```

## Maxwell 關係式

從 $dG = -SdT + VdP$ 可推：

$$\\left(\\frac{\\partial S}{\\partial P}\\right)_T = -\\left(\\frac{\\partial V}{\\partial T}\\right)_P$$
"""),

    # ── ENG201 English Writing ──
    ("eng201", "Academic Writing Cheat Sheet.md", """# Academic Writing Cheat Sheet

## Thesis Statement Formula

$$\\text{Thesis} = \\text{Topic} + \\text{Position} + \\text{Reasons}$$

❌ Weak: *Technology is good.*

✅ Strong: *Excessive smartphone use among college students harms academic performance by fragmenting attention, reducing sleep, and replacing deep reading.*

## Paragraph Structure: PIE

```mermaid
graph TD
  P[Point - 段落主張一句話] --> I[Illustration - 證據/例子/數據]
  I --> E[Explanation - 分析證據如何支持主張]
  E --> N[Next paragraph]
```

## Citation Format Comparison

| Style | Inline | Reference |
|-------|--------|-----------|
| APA | (Smith, 2020) | Smith, J. (2020). *Title*. Publisher. |
| MLA | (Smith 25) | Smith, John. *Title*. Publisher, 2020. |
| Chicago | (Smith 2020, 25) | Smith, John. 2020. *Title*. Publisher. |

## Common Academic Phrases

### Introducing topics
- This paper examines...
- Recent research suggests that...
- A growing body of literature indicates...

### Synthesizing sources
- Smith (2020) argues..., while Jones (2021) counters...
- Both X and Y agree that...
- In contrast to X's findings, Y demonstrates...

### Concluding
- These findings suggest that...
- Further research is needed to determine...
- Taken together, the evidence indicates...

## Writing Process Checklist

- [ ] Brainstorm and outline before drafting
- [ ] Write a working thesis (refine later)
- [ ] First draft: focus on ideas, not perfection
- [ ] Revise structure (PIE in every paragraph?)
- [ ] Edit sentences (clarity, concision)
- [ ] Proofread (typos, citations)
"""),

    # ── IPR101 智財權法 ──
    ("ipr101", "專利三要件詳解.md", """# 專利三要件詳解

台灣專利法 §22 規定，發明專利需具備三要件方可獲准。

## 1. 產業利用性

> 發明在產業上有實際應用可能性。

判斷簡單，多數技術都符合。永動機、神鬼通靈這類**違反自然法則**的不符合。

## 2. 新穎性

> 申請日前該技術未公開於：(1) 國內外刊物 (2) 公開使用 (3) 國內已為公眾所知。

```mermaid
graph LR
  A[申請日前] --> B[已公開?]
  B -->|是| N[喪失新穎性 不可申請]
  B -->|否| C{六個月內自己公開?}
  C -->|是| OK[可主張優惠期]
  C -->|否| N
```

**重要例外：優惠期 §22 III**

申請人在申請日前 6 個月內因下列情形公開，**不喪失新穎性**：
- 因實驗而公開
- 因於刊物發表
- 因陳列於政府主辦或認可之展覽會
- 非出於申請人本意而被公開

## 3. 進步性 (Inventive Step)

> 該領域具通常知識者，無法依先前技術輕易完成。

最難判斷的要件，採三步測試：

1. 確定先前技術 (prior art) 範圍
2. 確定本發明與先前技術的差異
3. 判斷該差異是否為熟練技術人員「顯而易見」

### 次要考量因素 (Secondary Considerations)

當技術差異判斷不明時，可參考：

| 因素 | 意義 |
|------|------|
| 長期未獲解決的需求 | 業界一直想解決卻沒人想到 → 不顯而易見 |
| 業界讚譽 | 同業認為是突破 → 不顯而易見 |
| 商業成功 | 上市後熱賣（要證明因技術而非行銷）|
| 競爭者抄襲 | 對手抄襲反證創新性 |

### 經典案例：Apple 滑動解鎖

```mermaid
timeline
  2005 : Apple 提交 US 8,046,721 申請
  2007 : iPhone 發表震驚業界
  2010 : 專利核准
  2012 : 告 Samsung 侵權
  2014 : 一審判 Samsung 賠 1.2 億美元
```

法院最終以「長期未獲解決需求 + 業界讚譽 + 競爭者抄襲」三大次要因素，認定具進步性。

## 三要件審查順序

```mermaid
graph TD
  A[申請] --> P[產業利用性]
  P -->|有| N[新穎性]
  P -->|無| R1[駁回]
  N -->|新| I[進步性]
  N -->|舊| R2[駁回]
  I -->|有| OK[核准]
  I -->|無| R3[駁回]
```
"""),
]


# (course_id, video_id, title)
YOUTUBE_MATERIALS: list[tuple[str, str, str]] = [
    ("ds101", "Hoixgm4-P4M", "Quicksort 視覺化"),
    ("mk201", "iGOw39GWDaI", "STP 行銷策略"),
    ("chm301", "ZsY4WcQOrfk", "熵 Entropy explained"),
    ("eng201", "DFp1uGTXo4Q", "How to Write a Thesis Statement"),
    ("ipr101", "l1Z3g7Hb01M", "Patent Basics in 5 Minutes"),
]


def main() -> None:
    mem = Memory(settings.memory_db_path)
    rag = CourseRAG(mem)

    md_dir_root = Path("_materials_md")

    n_md = 0
    for course_id, filename, body in MARKDOWN_MATERIALS:
        md_dir = md_dir_root / course_id
        md_dir.mkdir(parents=True, exist_ok=True)
        (md_dir / f"{filename}.md").write_text(body, encoding="utf-8")
        chunks = split_markdown_by_headings(body, source=filename)
        parsed = ParsedMarkdown(filename=filename, markdown=body, total_pages=1, chunks=chunks)
        rag.index_markdown(course_id, parsed)
        n_md += 1
        print(f"  ✓ {course_id}: {filename} ({len(chunks)} chunks)")

    n_yt = 0
    for course_id, vid, title in YOUTUBE_MATERIALS:
        filename = f"{title}.youtube.md"
        md_dir = md_dir_root / course_id
        md_dir.mkdir(parents=True, exist_ok=True)
        body = (
            f"# {title}\n\n"
            f"**來源**：[YouTube](https://www.youtube.com/watch?v={vid})\n\n"
            f'<iframe width="100%" height="380" '
            f'src="https://www.youtube.com/embed/{vid}" '
            f'title="{title}" frameborder="0" '
            f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; '
            f'gyroscope; picture-in-picture" allowfullscreen></iframe>\n\n'
            f"## 本片重點\n\n"
            f"老師指定的補充教學影片。學生可以邊看影片邊在左側 chat panel 提問，"
            f"AI 助理會以此影片作為知識來源回答。\n"
        )
        (md_dir / f"{filename}.md").write_text(body, encoding="utf-8")
        chunks = split_markdown_by_headings(body, source=filename)
        parsed = ParsedMarkdown(filename=filename, markdown=body, total_pages=1, chunks=chunks)
        rag.index_markdown(course_id, parsed)
        n_yt += 1
        print(f"  ✓ {course_id}: {filename} ({len(chunks)} chunks)")

    n_txt = 0
    for course_id, filename, body in MARKDOWN_MATERIALS:
        if not filename.endswith(".txt"):
            continue
        # already counted above; placeholder for clarity
        n_txt += 1

    print(f"\nTotal: {n_md} markdown + {n_yt} YouTube materials indexed")


if __name__ == "__main__":
    main()
