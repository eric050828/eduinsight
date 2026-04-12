"""Demo course materials for RAG seeding.

Provides pre-built ParsedDocument objects that can be indexed into CourseRAG
without needing actual PDF/PPTX files. This enables the full
RAG → AI Quiz → Live Quiz demo flow from a single /demo/reset click.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .documents import DocumentChunk, ParsedDocument

if TYPE_CHECKING:
    from .rag import CourseRAG

# ── ds101 資料結構 教材 ──

DS101_LECTURE_NOTES = ParsedDocument(
    filename="ds101_lecture_notes.pdf",
    total_pages=8,
    chunks=[
        DocumentChunk(
            text=(
                "陣列（Array）是最基本的資料結構，將相同型別的元素連續存放在記憶體中。"
                "陣列的優點是隨機存取時間為 O(1)，透過索引即可直接取得元素。"
                "缺點是插入和刪除需要搬移元素，時間複雜度為 O(n)。"
                "動態陣列（如 Python 的 list）在空間不足時會自動擴容，"
                "通常以 2 倍擴容策略達到平均 O(1) 的 append 操作。"
            ),
            source="ds101_lecture_notes.pdf",
            page=1,
            chunk_index=0,
        ),
        DocumentChunk(
            text=(
                "鏈結串列（Linked List）由節點組成，每個節點包含資料和指向下一個節點的指標。"
                "單向鏈結串列（Singly Linked List）只能往後走訪，"
                "雙向鏈結串列（Doubly Linked List）可以雙向走訪。"
                "鏈結串列的插入和刪除只需 O(1)（已知位置時），"
                "但搜尋需要 O(n) 因為必須從頭走訪。"
                "常見應用：實作堆疊、佇列、LRU Cache。"
            ),
            source="ds101_lecture_notes.pdf",
            page=2,
            chunk_index=1,
        ),
        DocumentChunk(
            text=(
                "堆疊（Stack）遵循後進先出（LIFO）原則。"
                "基本操作：push（推入）、pop（彈出）、peek（查看頂端），都是 O(1)。"
                "應用場景：函式呼叫堆疊、運算式求值、括號配對檢查、"
                "深度優先搜尋（DFS）、瀏覽器上一頁功能。"
                "Python 中可以直接用 list 實作堆疊（append/pop）。"
            ),
            source="ds101_lecture_notes.pdf",
            page=3,
            chunk_index=2,
        ),
        DocumentChunk(
            text=(
                "佇列（Queue）遵循先進先出（FIFO）原則。"
                "基本操作：enqueue（入列）、dequeue（出列），都是 O(1)。"
                "變形：雙端佇列（Deque）兩端都可以進出；"
                "優先佇列（Priority Queue）按優先權出列，通常用堆積實作。"
                "應用場景：BFS（廣度優先搜尋）、工作排程、訊息佇列。"
                "Python 中使用 collections.deque 比 list 更高效。"
            ),
            source="ds101_lecture_notes.pdf",
            page=3,
            chunk_index=3,
        ),
        DocumentChunk(
            text=(
                "二元樹（Binary Tree）每個節點最多有兩個子節點（左、右）。"
                "二元搜尋樹（BST）滿足左子樹所有值 < 根 < 右子樹所有值。"
                "BST 搜尋、插入、刪除的平均時間為 O(log n)，最差 O(n)。"
                "走訪方式：前序（Preorder）、中序（Inorder）、後序（Postorder）、層序（Level-order）。"
                "中序走訪 BST 會得到排序結果。"
            ),
            source="ds101_lecture_notes.pdf",
            page=4,
            chunk_index=4,
        ),
        DocumentChunk(
            text=(
                "平衡二元搜尋樹（如 AVL Tree、紅黑樹）保證樹的高度為 O(log n)。"
                "AVL Tree 透過旋轉操作（左旋、右旋、左右旋、右左旋）維持平衡。"
                "平衡因子 = 左子樹高度 - 右子樹高度，必須在 {-1, 0, 1} 之間。"
                "紅黑樹是 Java TreeMap、C++ std::map 的底層實作。"
                "B-Tree 和 B+ Tree 則常用於資料庫索引和檔案系統。"
            ),
            source="ds101_lecture_notes.pdf",
            page=5,
            chunk_index=5,
        ),
        DocumentChunk(
            text=(
                "雜湊表（Hash Table）透過雜湊函數將鍵映射到陣列索引，"
                "平均情況下查詢、插入、刪除都是 O(1)。"
                "碰撞處理方法：開放定址法（Open Addressing）和鏈結法（Chaining）。"
                "負載因子（Load Factor）= 元素數 / 桶數，通常超過 0.75 時需要 rehash。"
                "Python 的 dict 就是雜湊表實作，具有 O(1) 平均查詢時間。"
                "應用：快取系統、重複檢測、資料庫索引、計數器。"
            ),
            source="ds101_lecture_notes.pdf",
            page=6,
            chunk_index=6,
        ),
        DocumentChunk(
            text=(
                "圖（Graph）由頂點（Vertex）和邊（Edge）組成。"
                "表示方法：鄰接矩陣（Adjacency Matrix）適合稠密圖，鄰接串列（Adjacency List）適合稀疏圖。"
                "深度優先搜尋（DFS）使用堆疊，適合拓撲排序、連通分量偵測。"
                "廣度優先搜尋（BFS）使用佇列，適合最短路徑（無權圖）。"
                "最短路徑演算法：Dijkstra（非負權重）、Bellman-Ford（可處理負權重）。"
                "最小生成樹：Kruskal（邊排序）、Prim（頂點擴展）。"
            ),
            source="ds101_lecture_notes.pdf",
            page=7,
            chunk_index=7,
        ),
        DocumentChunk(
            text=(
                "排序演算法比較："
                "氣泡排序（Bubble Sort）O(n²)，簡單但效率低。"
                "選擇排序（Selection Sort）O(n²)，不穩定。"
                "插入排序（Insertion Sort）O(n²)，小資料或近乎排序的資料表現良好。"
                "合併排序（Merge Sort）O(n log n)，穩定，適合外部排序。"
                "快速排序（Quick Sort）平均 O(n log n)，最差 O(n²)，實務中最快。"
                "堆積排序（Heap Sort）O(n log n)，原地排序但不穩定。"
                "Python 的 sorted() 使用 Timsort，結合合併排序和插入排序。"
            ),
            source="ds101_lecture_notes.pdf",
            page=8,
            chunk_index=8,
        ),
    ],
)

# ── Courses to seed: (course_id, documents) ──
DEMO_MATERIALS: list[tuple[str, list[ParsedDocument]]] = [
    ("ds101", [DS101_LECTURE_NOTES]),
]


def seed_demo_materials(rag: CourseRAG) -> int:
    """Seed demo course materials into RAG.

    Returns total number of chunks indexed.
    """
    total = 0
    for course_id, docs in DEMO_MATERIALS:
        # Clear existing materials for this course first
        existing = rag.list_documents(course_id)
        for doc_name in existing:
            rag.remove_document(course_id, doc_name)

        for doc in docs:
            total += rag.index_document(course_id, doc)
    return total
