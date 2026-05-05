"""Generate diverse course material PDFs across multiple departments."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


def _register_cjk_font() -> str:
    candidates = [
        ("MSJH", r"C:\Windows\Fonts\msjh.ttc"),
        ("MingLiU", r"C:\Windows\Fonts\mingliu.ttc"),
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
        str(output), pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm,
    )
    base = getSampleStyleSheet()
    title_style = ParagraphStyle("T", parent=base["Title"], fontName=FONT, fontSize=22, leading=28)
    h2 = ParagraphStyle("H2", parent=base["Heading2"], fontName=FONT, fontSize=14, leading=20, spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("B", parent=base["BodyText"], fontName=FONT, fontSize=11, leading=16, spaceAfter=6)
    story = [Paragraph(title, title_style), Spacer(1, 12)]
    for idx, (h, ps) in enumerate(sections):
        if idx > 0 and idx % 4 == 0:
            story.append(PageBreak())
        story.append(Paragraph(h, h2))
        for p in ps:
            story.append(Paragraph(p, body))
    doc.build(story)


# 行銷管理 — 企管系 黃教授
MARKETING = (
    "mk201_marketing_management.pdf",
    "行銷管理 — 4P 與 STP 策略",
    [
        ("第 1 章 行銷組合 4P", [
            "4P 是行銷策略的基本架構：Product（產品）、Price（價格）、Place（通路）、Promotion（推廣）。"
            "這四個要素必須整合考量，不能只強化單一要素。",
            "Product 不只是實體商品，還包括服務、品牌、保固、設計、包裝。"
            "從顧客角度看，Product 對應到「需求被滿足的程度」。",
            "Price 是 4P 中唯一產生收入的要素，其餘三個都是成本。"
            "定價策略包括成本加成、價值定價、競爭定價、心理定價（如 $999 而非 $1000）。",
            "Place（通路）決定產品如何從廠商到消費者手上。"
            "通路長度（直銷 vs 多階通路）和通路寬度（密集 vs 選擇性 vs 獨家）都要設計。",
            "Promotion 包含廣告、促銷、人員銷售、公關、直效行銷與數位行銷。"
            "AIDA 模式：Attention → Interest → Desire → Action 描述消費者反應。",
        ]),
        ("第 2 章 STP 流程", [
            "STP 是 Segmentation（市場區隔）→ Targeting（選定目標市場）→ Positioning（定位）。"
            "這是任何行銷計畫的起手式，必須在決定 4P 之前完成。",
            "市場區隔依據：地理（北中南）、人口統計（年齡/性別/收入）、心理（生活型態）、行為（購買頻率）。"
            "好的區隔要符合「可衡量、可接近、有規模、可區分、可行動」五個條件。",
            "目標市場選擇策略：無差異行銷（一個方案打全市場）、差異化行銷（不同區隔不同方案）、集中化行銷（鎖定單一區隔）。",
            "定位是在「目標顧客的心智」中佔據獨特位置。常見定位法：屬性定位（最便宜）、利益定位（最快）、使用者定位（為專業人士）、競爭定位（不是 Coke）。",
            "知覺地圖（Perceptual Map）：用兩個關鍵屬性畫二維圖，看品牌相對位置與市場空缺。",
        ]),
        ("第 3 章 SWOT 分析", [
            "SWOT 是分析企業內外部處境的工具：Strengths、Weaknesses 屬內部；Opportunities、Threats 屬外部。"
            "常見錯誤是把外部因素（如「景氣不好」）寫進 Weaknesses。",
            "SWOT 不是終點。要轉成 TOWS 矩陣推策略：SO（用優勢抓機會）、WO（克弱點抓機會）、ST（用優勢避威脅）、WT（弱化弱點避威脅）。",
        ]),
        ("第 4 章 案例：星巴克的 STP+4P", [
            "Segmentation：星巴克鎖定「都會白領、注重生活品質」族群（心理 + 行為區隔）。"
            "Positioning：「第三空間」——家與辦公室之外的舒適社交場所，定位高於普通咖啡連鎖。",
            "4P 對應：Product 強調精品咖啡 + 體驗；Price 採高價值定價；Place 選黃金地段；"
            "Promotion 走口碑與會員制，廣告投放比競品低。各要素彼此呼應，這就是「行銷組合一致性」。",
        ]),
    ],
)

# 物理化學 — 化工系 林教授
PCHEM = (
    "chm301_pchem_thermo.pdf",
    "物理化學 — 熱力學第一定律與相平衡",
    [
        ("§1 熱力學第一定律", [
            "ΔU = q + w，其中 ΔU 是系統內能變化，q 是熱量（系統吸熱為正），w 是功（外界對系統作功為正）。"
            "符號慣例在不同教科書可能不同，IUPAC 與 Atkins 使用此慣例。",
            "對於理想氣體在等溫過程：ΔU = 0，因為內能僅依溫度而定。"
            "因此 q = -w。等溫可逆膨脹：w = -nRT ln(V₂/V₁)。",
            "焓 H = U + PV。等壓過程：q_p = ΔH。這就是為什麼化學反應的反應熱通常用 ΔH 表示——大多數反應在恆壓下進行（敞開大氣）。",
        ]),
        ("§2 熱容與絕熱過程", [
            "等容熱容 Cv = (∂U/∂T)_V；等壓熱容 Cp = (∂H/∂T)_P。"
            "對理想氣體 Cp - Cv = nR（Mayer 關係式）。",
            "絕熱過程 q = 0，所以 ΔU = w。對理想氣體絕熱可逆：PV^γ = const，其中 γ = Cp/Cv。"
            "γ 對單原子氣體 = 5/3，雙原子 = 7/5（室溫）。",
        ]),
        ("§3 Gibbs 自由能與相平衡", [
            "G = H - TS。在等溫等壓下，自發過程 ΔG < 0；平衡時 ΔG = 0。"
            "ΔG = ΔH - TΔS：低溫下 ΔH 主導，高溫下 TΔS 主導，這解釋了相變的方向性。",
            "Clausius-Clapeyron 方程式描述純物質的相界線："
            "dP/dT = ΔS_trs/ΔV_trs = ΔH_trs/(T·ΔV_trs)。"
            "對液-氣相界線並假設氣體理想 + V_液 << V_氣，可推導為 ln(P₂/P₁) = -(ΔH_vap/R)(1/T₂ - 1/T₁)。",
            "Gibbs 相律：F = C - P + 2，其中 F 自由度、C 組分數、P 相數。"
            "純水三相點：F = 1 - 3 + 2 = 0（固定點），所以三相點溫度與壓力都被決定。",
        ]),
        ("§4 練習與常見錯誤", [
            "常見錯誤一：把絕熱與等溫混淆。絕熱：q = 0，溫度通常會變；等溫：T 不變，q ≠ 0。",
            "常見錯誤二：算 ΔS 時忘了「可逆」前提。ΔS = q_rev/T，q 必須是可逆過程的熱。",
            "常見錯誤三：相律算自由度時 C 算錯。氯化鈉水溶液 C = 2（NaCl + H₂O），不是 3 或 1。",
            "解題步驟：(1) 列出已知條件 (2) 確認系統與過程類型 (3) 寫熱力學第一定律 (4) 套對應公式。",
        ]),
    ],
)

# 英文報告寫作 — 應外系 王教授
ENG_WRITING = (
    "eng201_academic_writing.pdf",
    "English Academic Writing — Argumentation & Citation",
    [
        ("1. Thesis Statement", [
            "A thesis statement is the central claim of your essay. It must be (1) specific, "
            "(2) arguable, (3) supported by evidence in the body. Avoid vague theses like "
            "\"Technology has changed our lives.\" Instead: \"Smartphone notifications fragment "
            "attention spans, reducing deep work productivity by 23% according to Stanford 2019.\"",
            "Place your thesis at the end of the introduction. The body paragraphs are evidence; "
            "each topic sentence should connect back to the thesis.",
        ]),
        ("2. Paragraph Structure (PEEL)", [
            "Point: Topic sentence stating the paragraph's main claim. "
            "Evidence: Data, quotation, or example supporting the point. "
            "Explain: Analyze HOW the evidence supports the point — this is where weak essays fall flat. "
            "Link: Transition to next paragraph or restate connection to thesis.",
            "A common mistake: stacking quotes without explanation. The reader cannot guess your interpretation.",
        ]),
        ("3. Citation: APA 7th Edition", [
            "In-text: (Author, Year, p. X) for direct quotes; (Author, Year) for paraphrase. "
            "Multiple authors: (Smith & Lee, 2020); 3+ authors: (Smith et al., 2020). "
            "Reference list: alphabetical by surname, hanging indent, italic journal/book titles.",
            "Common error: confusing APA with MLA. APA uses (Author, Year); MLA uses (Author Page). "
            "Pick one style per paper and stick to it.",
            "Direct quote longer than 40 words: block quote, indented, no quotation marks. "
            "Paraphrase rule: change at least 3 of {word order, vocabulary, sentence structure}; "
            "keeping only synonyms (\"big\" → \"large\") still counts as plagiarism.",
        ]),
        ("4. Common Grammatical Errors", [
            "Subject-verb agreement: \"The data show...\" (data is plural). "
            "Run-on sentences: split or use semicolon. "
            "Article use: \"a\" before consonant sound, \"an\" before vowel sound, \"the\" for specific.",
            "Hedging language: avoid absolutist claims. Use \"suggests\", \"indicates\", \"may\", "
            "\"appears to\". Strong claims need stronger evidence.",
            "Active voice generally preferred over passive in modern academic English. "
            "\"Smith (2020) found that...\" is better than \"It was found by Smith (2020) that...\"",
        ]),
    ],
)

# 智慧財產權法 — 智財學程 李教授
IP_LAW = (
    "ipr101_patent_law.pdf",
    "智慧財產權法 — 專利三要件與侵權判定",
    [
        ("§1 專利三要件", [
            "依我國專利法第 22 條，發明專利須符合：產業利用性、新穎性、進步性（Inventive Step）。"
            "三要件缺一不可，且審查順序通常是：先產業利用性 → 新穎性 → 進步性。",
            "產業利用性（Industrial Applicability）：發明可供產業上利用即符合，門檻最低。"
            "純粹學術理論、永動機、違反自然律的發明不具產業利用性。",
            "新穎性（Novelty）：申請日前未公開揭露於國內外。"
            "「擬制喪失新穎性」例外：申請人自行公開後 12 個月內仍可申請（優惠期）。",
            "進步性（Inventive Step）：相對於先前技術，所屬技術領域中具通常知識者「非能輕易完成」。"
            "判斷三步驟：(1) 確定先前技術範圍 (2) 確定差異 (3) 判斷差異是否輕易可得。",
        ]),
        ("§2 侵權判定流程：兩段論", [
            "第一段「全要件原則」（All Elements Rule）："
            "比對被控侵權物是否包含請求項所有技術特徵。"
            "若任一特徵缺失 → 文義不侵權，進入均等論判斷。",
            "第二段「均等論」（Doctrine of Equivalents）："
            "雖無文義侵權，但被控物以實質相同方式、達成實質相同功能、產生實質相同結果，仍構成侵權。"
            "此即三步測試（Triple Identity Test）。",
            "均等論的限制：禁反言（Prosecution History Estoppel）。"
            "申請過程中為克服核駁所作的限縮修改，不能事後用均等論再主張涵蓋。",
        ]),
        ("§3 著作權合理使用", [
            "我國著作權法第 65 條合理使用四要素："
            "(1) 利用目的（商業 / 非營利、教育）"
            "(2) 著作性質（事實性 / 創意性）"
            "(3) 利用比例（質與量）"
            "(4) 對市場價值之影響（最重要）。",
            "教科書節選用於課堂：通常符合合理使用。"
            "整本書影印發給學生：不符合（市場替代）。"
            "迷因二創：要看是否轉化（transformative）以及對原著市場影響。",
        ]),
        ("§4 案例：iPhone vs HTC（2012）", [
            "Apple 主張 HTC 侵犯多項軟體專利，包括 '647 號（資料偵測）。"
            "ITC 裁定 HTC 部分侵權，HTC 透過軟體 workaround 規避。"
            "本案重點：軟體專利的範圍解釋與設計繞過（Design Around）的合法界限。",
            "教學重點：請求項解釋是侵權判斷核心。"
            "申請時的 \"any data\" 範圍若太廣，審查官會要求限縮；事後想用均等論回擴會被禁反言阻擋。",
        ]),
    ],
)


def main() -> None:
    out_dir = Path(__file__).parent.parent / "_sim_materials"
    for filename, title, sections in [MARKETING, PCHEM, ENG_WRITING, IP_LAW]:
        path = out_dir / filename
        make_pdf(path, title, sections)
        print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
