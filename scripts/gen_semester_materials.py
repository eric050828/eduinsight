"""Generate course material PDFs for the semester simulation."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)


def _register_cjk_font() -> str:
    """Register a CJK font available on Windows."""
    candidates = [
        ("MSJH", r"C:\Windows\Fonts\msjh.ttc"),  # 微軟正黑體
        ("MingLiU", r"C:\Windows\Fonts\mingliu.ttc"),
        ("KaiU", r"C:\Windows\Fonts\kaiu.ttf"),
    ]
    for name, path in candidates:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=0))
                return name
            except Exception:  # noqa: BLE001
                continue
    return "Helvetica"


FONT = _register_cjk_font()


def make_pdf(output: Path, title: str, sections: list[tuple[str, list[str]]]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    base = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCJK", parent=base["Title"], fontName=FONT, fontSize=22, leading=28,
    )
    h2_style = ParagraphStyle(
        "H2CJK", parent=base["Heading2"], fontName=FONT, fontSize=14,
        leading=20, spaceBefore=12, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "BodyCJK", parent=base["BodyText"], fontName=FONT, fontSize=11,
        leading=16, spaceAfter=6,
    )

    story = [Paragraph(title, title_style), Spacer(1, 12)]
    for idx, (heading, paragraphs) in enumerate(sections):
        if idx > 0 and idx % 4 == 0:
            story.append(PageBreak())
        story.append(Paragraph(heading, h2_style))
        for para in paragraphs:
            story.append(Paragraph(para, body_style))

    doc.build(story)


WEEK1 = (
    "ds101_week01_intro_arrays.pdf",
    "Week 1：資料結構導論 + 陣列",
    [
        ("1.1 為什麼要學資料結構", [
            "資料結構決定演算法的效率上限。同樣是「找出最大值」，"
            "在排序後的陣列上是 O(1)，未排序則是 O(n)。",
            "本課程從最基本的線性結構（陣列、鏈結串列）開始，"
            "逐步進入樹、雜湊表、圖等非線性結構。",
        ]),
        ("1.2 陣列 (Array) 的基本操作", [
            "存取：透過索引 (index) 直接定址，時間複雜度 O(1)。",
            "插入到尾端：若有預留空間 O(1)，需要擴容則為攤銷 O(1)。",
            "插入到中間：必須將後續元素整體後移，O(n)。",
            "刪除中間元素：同樣需要將後續元素前移，O(n)。",
        ]),
        ("1.3 動態陣列與擴容策略", [
            "Python list、Java ArrayList、C++ std::vector 都採用倍增擴容。"
            "當容量不足時，配置兩倍空間並把舊資料複製過去。",
            "倍增策略保證了平均 (amortized) 插入仍是 O(1)，"
            "雖然單次擴容是 O(n)。",
        ]),
        ("1.4 練習與常見錯誤", [
            "常見錯誤：在 for 迴圈裡同時刪除元素，會造成索引錯位。"
            "正確做法是反向迭代，或建立新的 list。",
            "效率陷阱：用 list.insert(0, x) 反覆在頭端插入是 O(n)，"
            "若需要這種操作改用 collections.deque 才是 O(1)。",
        ]),
    ],
)

WEEK4 = (
    "ds101_week04_trees_traversal.pdf",
    "Week 4：二元樹與遍歷",
    [
        ("4.1 二元樹的定義", [
            "二元樹是每個節點最多有兩個子節點的樹結構，分別稱為左子樹和右子樹。"
            "高度 (height) 是從根到最深葉節點的邊數，深度 (depth) 是從根到該節點的邊數。",
            "完全二元樹 (Complete Binary Tree)：除最後一層外都填滿，最後一層由左至右填入。"
            "高度為 h 的完全二元樹至少 2^h 個節點，至多 2^(h+1)-1 個節點。",
        ]),
        ("4.2 三種遍歷方式", [
            "Inorder (中序)：左 → 根 → 右。對二元搜尋樹會得到「升序」結果，"
            "這是 inorder 最重要的應用。",
            "Preorder (前序)：根 → 左 → 右。常用於序列化樹結構，"
            "因為根節點先出現，便於重建。",
            "Postorder (後序)：左 → 右 → 根。用於計算樹的大小、刪除整棵樹，"
            "因為要先處理子節點再處理父節點。",
        ]),
        ("4.3 遞迴 vs 迭代", [
            "三種遍歷的遞迴版本都很短，但有 stack overflow 風險。"
            "迭代版本需要顯式維護一個 stack。",
            "Inorder 迭代：先一路往左壓入 stack，pop 一個就訪問它，"
            "然後處理右子樹。Preorder 類似但訪問時機在 push 之前。",
            "Postorder 迭代相對複雜，常見做法是用兩個 stack，"
            "或在每個節點加上「是否已訪問子樹」的標記。",
        ]),
        ("4.4 二元搜尋樹 (BST)", [
            "BST 的不變式：對任意節點 x，左子樹所有節點 < x < 右子樹所有節點。",
            "在平衡的 BST 中，搜尋、插入、刪除都是 O(log n)；"
            "但若插入順序剛好是排序好的，BST 會退化成鏈結串列，O(n)。",
            "因此實務上會用 AVL Tree 或紅黑樹來維持平衡。"
            "Java TreeMap 與 C++ std::map 底層就是紅黑樹。",
        ]),
    ],
)

WEEK8 = (
    "ds101_week08_sorting.pdf",
    "Week 8：排序演算法總整理",
    [
        ("8.1 簡單排序 O(n²)", [
            "氣泡排序 (Bubble Sort)：相鄰兩兩比較交換，最差 O(n²)，最佳 O(n)。"
            "穩定排序但效率低，僅適合教學示範。",
            "選擇排序 (Selection Sort)：每次選最小放最前面。固定 O(n²)，"
            "比較次數固定但寫入次數最少。不穩定。",
            "插入排序 (Insertion Sort)：把元素逐一插到已排序區的正確位置。"
            "對近乎排序的資料表現極佳 O(n)，是 Timsort 的小資料子流程。",
        ]),
        ("8.2 分治排序 O(n log n)", [
            "合併排序 (Merge Sort)：分→排→合，穩定排序，最差 O(n log n) 保證。"
            "空間複雜度 O(n)，適合外部排序。",
            "快速排序 (Quick Sort)：選 pivot 切兩半遞迴。"
            "平均 O(n log n)，最差 O(n²)（已排序資料 + 每次選最左 pivot）。"
            "實務中最快，因為原地排序、cache 友善。",
            "堆積排序 (Heap Sort)：先建 max-heap 再逐一取出。原地、最差 O(n log n)，"
            "但 cache 效率比 quicksort 差，實際比較慢。不穩定。",
        ]),
        ("8.3 線性時間排序", [
            "計數排序 (Counting Sort)：當值域 k 不大時 O(n+k)。"
            "穩定但需要額外 O(k) 空間。",
            "基數排序 (Radix Sort)：對每個位數做 stable sort，O(d(n+k))。"
            "適合固定長度的整數或字串。",
            "桶排序 (Bucket Sort)：分到 k 個桶後各自排序。"
            "在均勻分布假設下平均 O(n+k)，最差 O(n²)。",
        ]),
        ("8.4 實務 sort: Python 的 Timsort", [
            "Timsort = Merge Sort + Insertion Sort 的混合算法。"
            "識別資料中已排序的「run」，用 insertion sort 擴展短 run，"
            "再用 merge sort 合併。最差 O(n log n)、最佳 O(n)、穩定。",
            "Python 的 sorted() 和 list.sort()、Java Collections.sort() 都是 Timsort。"
            "對「幾乎已排序」的真實資料表現極好。",
        ]),
    ],
)


def main() -> None:
    out_dir = Path(__file__).parent.parent / "_sim_materials"
    for filename, title, sections in [WEEK1, WEEK4, WEEK8]:
        path = out_dir / filename
        make_pdf(path, title, sections)
        print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
