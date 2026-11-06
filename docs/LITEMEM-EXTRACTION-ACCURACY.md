# Lite-Mem 事實萃取準確率評估

> **標註者：AI（Claude Opus 5.5），非人工標註。**
> 本報告所有 gold 標註都由 AI 完成，沒有經過人工複核。數字只能當作初步估計。
> 標註表放在 `eval/extraction_labels_2026-11-04.csv`，組員可以直接修改 gold 欄位後重算（見第 8 節）。

> **2026-11-06 更新：** 儀表板的困難判斷已修正，修正後的數字見第 9 節。第 1 到 6 節保留修正前的基準結果，其中 `analyze_student` 那一列（3/24）是修正前的數字，標註表的 `analytics_struggles` 欄則已是修正後的輸出。

- 評估日期：2026-11-04
- 對應交接項目：交接文件第 4 節「Lite-Mem 萃取準確率量化」
- 受測版本：`litemem` 0.4.0（依 `uv.lock`），EduInsight `main` @ `cb19889`
- 重跑指令：`uv run python scripts/eval_extraction.py score`

## 1. 結論摘要

| 指標（n = 50 則學生訊息） | 數值 | 95% 信賴區間 |
|---|---|---|
| 事實層級 Precision（strict） | **0.500**（8/16） | Wilson [0.280, 0.720] |
| 事實層級 Recall（strict） | **0.276**（8/29） | Wilson [0.147, 0.457] |
| 事實層級 F1（strict） | **0.356** | bootstrap [0.182, 0.510] |
| 事實層級 Precision／Recall／F1（lenient） | 0.562／0.310／0.400 | P [0.332, 0.769]、R [0.173, 0.492]、F1 [0.222, 0.556] |
| 「學習困難」訊息層級 Recall：萃取出的事實帶有困難語句 | 0.250（6/24） | Wilson [0.120, 0.449] |
| 「學習困難」訊息層級 Recall：教師端 `analyze_student` 實際算成 struggle | **0.125**（3/24） | Wilson [0.043, 0.310] |
| 上面兩項的 Precision | 1.000（6/6、3/3） | [0.610, 1.000]、[0.438, 1.000] |

重點：

1. **production 用的萃取器是 Lite-Mem 的規則式 `StubExtractor`**，不是 LLM。50 則訊息裡只有 13 則抽得出東西（共 16 個事實），其餘 37 則改走 fallback，存原始的 `Q:`／`A:` 文字。
2. 抽到的事實大約一半是對的（P ≈ 0.5），但真正該記住的事實只抽到約四分之一到三分之一（R ≈ 0.28–0.31）。
3. 學生明確說了「不懂、搞混、看不懂」的 24 則訊息裡，教師儀表板（`analytics.analyze_student`）只算到 3 則有 struggle。主要原因有兩個（見第 6 節）：
   - 萃取器漏抽，例如「搞不清楚」「又搞混了」「看不出差異」「記反」「背不起來」都沒有對應規則。
   - 前端每則訊息都帶 `[課程名]` 前綴，而 `analyze_student` 遇到 `[...]` 開頭的事實，一律當成「提問主題」處理，不會判成 struggle。
4. 樣本來源是示範對話，不是真實學生；標註由 AI 完成；n = 50，所以信賴區間很寬。這些數字只能看量級（「低」），不適合拿來和其他系統做精確比較。

## 2. 受測系統：production 實際的萃取路徑

以下依原始碼確認，沒有用假設：

```
POST /chat（有設定 LLM 時）                         src/eduinsight/app.py
  → LearningAssistant.answer()                      src/eduinsight/assistant.py
      → extract_from_conversation(question, reply, topic=req.topic)
          → Memory.add_conversation(uid, [user, assistant], extractor=self._extractor)
             └ self._extractor 預設 "stub"；app.py 以 LearningAssistant(_memory, llm=_llm) 建構，沒有覆寫
             └ litemem/api.py：extractor == "stub" → StubExtractor().extract(session)
      → 如果沒抽到任何事實：record_interaction() 存 "[topic] Q: …" 與 "[topic] A: …"（extract=False）
```

- **萃取器**：`litemem.lite_mem.StubExtractor`。Lite-Mem 自己的說明寫的是「規則型抽取（離線，品質低）」、「驗證 pipeline 正確性（不驗證抽取品質）」。它其實不是空殼：裡面大約有 3,800 行中英文觸發詞規則，主要針對一般個人事實（identity／family／emotion／social／education 等類別），學習相關的只有少數觸發詞，例如「不懂」「不會」「搞不懂」「學會了」，分類是 `learning`。這些規則只看 `role == "user"` 的訊息，助理回覆不影響結果。
- **即使設定了 `GEMINI_API_KEY` 也一樣用 stub**。EduInsight 明確傳入 `"stub"`，所以 Lite-Mem 的 `"auto"`（有 key 時改用 Gemini）在 production 不會生效。
- **沒有 LLM 時**，`/chat` 只呼叫 `record_question()`（`extract=False`），完全不萃取。
- **`topic`**：學生端前端（`static/student.html`）送出 `topic: course.name`，所以實際餵進萃取器的使用者訊息是 `"[資料結構] 我完全不懂鏈結串列…"`。
- **其他 `add(..., extract=False)` 呼叫**（record_struggle、RAG、office hours、demo 種子）都不經過萃取器，不在本評估範圍內。

### 與示範資料的差異

`scripts/seed_semester_conversations.py` 的 `FACT_SEEDS` 和 `demo_data.py`，是**人工預先寫好的**結構化事實，例如 `Struggling with: SWOT 內外部因素分類 — …`。它們用 `extract=False` 直接寫入，格式剛好符合 `analytics._STRUGGLE_RE`。所以 demo 時儀表板看到的困難主題，**不是萃取器產生的**。對話本身只寫進 `messages` 表，從來沒有餵給萃取器。

本評估把這些對話裡的學生訊息**重新餵給真正的萃取器**，量的是上線後真實學生對話會得到的結果，不是示範資料預寫的 facts。

## 3. 方法

### 3.1 語料與抽樣

- 母體：示範對話裡所有學生發言，共 73 則。
  - `scripts/seed_semester_conversations.py`：`CONVERSATIONS` 46 則加 `MULTITURN_SESSIONS` 16 則，5 位學生，跨 18 週，課程包含 ds101／mk201／chm301／eng201／ipr101 等。
  - `src/eduinsight/demo_conversations.py`：`DEMO_CONVERSATIONS` 11 則（沒有課程欄）。
- 抽樣：依 sample_id 排序後，用 `random.Random(20261104).sample(pool, 50)` 抽 50 則，**不放回、沒有挑樣本**。抽中的樣本包含 31 則 semester 單輪、11 則 multi-turn、8 則 demo_conversations。
- 重播：每則訊息都在獨立的 `Memory(":memory:", embedder=None)` 上，**直接呼叫 production 的 `LearningAssistant.extract_from_conversation()`**。沒抽到東西時再呼叫 `record_interaction()`，最後跑 `analytics.analyze_student()`。
  - 有課程的樣本以 `COURSE_CATALOG` 的中文課名當 topic，和前端行為一致。
  - `demo_conversations` 的樣本沒有課程，所以 topic 是空字串（`ChatRequest.topic` 的預設值）。
  - 關閉 embedder 不影響萃取出哪些事實，只影響之後的檢索。

### 3.2 Gold 標註判準（什麼是「該萃取的事實」）

Gold 事實必須是**學生在這則訊息裡自己明示的、值得長期記住的學生狀態**。分成 4 類：

| 類型 | 定義 | 例子 |
|---|---|---|
| `struggle` | 學生自述對某個概念不懂、搞混、看不懂、記反、背不起來；或自述作答被老師或考試判錯 | 「我搞不清楚 Targeting 跟 Positioning」「老師說我寫錯了」 |
| `affect` | 與學習風險相關的自我評價或情緒 | 「我是不是不適合資工系」「老師講得太快了」 |
| `preference` | **一般性、習慣性**的學習偏好陳述（「我比較喜歡…」） | （本樣本 0 則） |
| `context` | 學生自己的修課情境 | 「作業要做 SWOT 分析」「想看完再寫期中報告」 |

不算 gold 的情況：

- 單純的內容提問，例如「Bellman-Ford 為什麼是 O(VE)？」。提問主題已由 fallback 的 `Q:` 紀錄保存，不屬於「學生事實」。
- 需要靠領域知識批改才看得出的錯誤，例如 mt-2-1 學生貼出的 SWOT 草稿。
- 第三人的事，例如 sem-023 的「我朋友…不確定合不合法」。
- **一次性的學習形式請求**，例如「可以畫個圖嗎」「給我口訣」。這類在標註表 notes 裡標為 `possible_pref`，共 7 則，敏感度分析見 5.3。

`gold_struggle`（訊息層級）：只要該訊息有任何 `struggle` 類的 gold 事實就是 1。結果 24/50 為 1。

### 3.3 「一個萃取事實算對」的判準

萃取出的事實會被**單獨**存進記憶，之後給 LLM 和 analytics 讀。所以判斷時只看這段文字本身能不能傳達 gold 事實：

- **strict TP**：事實文字本身能看出 gold 事實的**類型**，而且**主題可以辨識**。
  - struggle 要看得出是哪個概念（例如「搞不懂進步性怎麼判斷」「null 值一直搞混」）。
  - 文字殘缺但主題詞還在的也算，例如「[資料結構] 那 bst完全不懂」。
- **lenient TP**：能看出類型，而且確實對應該 gold 事實，但主題缺漏也算。例如只剩「沒有懂」。
- **一對一配對**：一個 gold 事實最多被一個萃取事實配對。同一事實重複抽出時，多出來的計為 FP（例如 mt-0-0 抽出「[資料結構]完全不懂」和「不懂鏈結串列」）。
- **FP**：沒有配對到任何 gold 的萃取事實，例如問句片段「用inorder」「申請整個流程是什麼」，或語意錯亂的「就讀不不適合資工系」。
- **FN**：沒有被任何萃取事實配對到的 gold 事實。
- Precision = TP / 萃取事實數；Recall = TP / gold 事實數；F1 是兩者的調和平均（micro）。
- Lite-Mem 自己給的 category（learning／general／skill…）**不列入對錯判定**，只用來分組計算 precision。

### 3.4 訊息層級的「學習困難」偵測

EduInsight 真正在意的是能不能看出學生卡在哪裡，所以另外評估兩個二元判定（gold 是 `gold_struggle`）：

1. **萃取事實帶有困難語句**：任何一個萃取事實能通過 `analytics._is_natural_struggle()`（關鍵字比對）。這相當於回答時 LLM 讀記憶能看到的訊號。
2. **教師端算成 struggle**：對該則訊息實際存下的內容（萃取事實，或 fallback 的 Q/A）跑 `analytics.analyze_student()`，`struggles` 不為空。這就是儀表板、弱點主題、diagnostics mastery 的來源。

### 3.5 統計

- Precision／Recall 使用 **Wilson score 95% 區間**（z = 1.96）。
- F1 使用以訊息為單位重抽的 **percentile bootstrap**（2,000 次，seed 20261104）。
- 同一則訊息裡的多個事實並不獨立，所以事實層級的 Wilson 區間會偏窄。bootstrap 是以訊息為單位重抽，比較能反映這一點。

## 4. 結果

### 4.1 整體

| 模式 | 萃取事實 | gold 事實 | TP | FP | FN | Precision [95% CI] | Recall [95% CI] | F1 [95% CI] |
|---|---|---|---|---|---|---|---|---|
| strict | 16 | 29 | 8 | 8 | 21 | 0.500 [0.280, 0.720] | 0.276 [0.147, 0.457] | 0.356 [0.182, 0.510] |
| lenient | 16 | 29 | 9 | 7 | 20 | 0.562 [0.332, 0.769] | 0.310 [0.173, 0.492] | 0.400 [0.222, 0.556] |

- 50 則裡 13 則至少抽出 1 個事實，37 則（74%）抽不到，改存原始 Q/A。
- 在 4 則訊息裡（mt-1-2、sem-001、sem-004、sem-035），抽出的**全是錯的片段**。因為有抽到東西，fallback 就不會觸發，結果原始問題不會被存進記憶，只留下「用inorder」這類片段。

### 4.2 依 gold 類型的 Recall（strict）

| gold 類型 | 配對到 / 總數 | Recall [95% CI] |
|---|---|---|
| struggle | 6 / 24 | 0.250 [0.120, 0.449] |
| affect | 1 / 2 | 0.500 [0.095, 0.905] |
| context | 1 / 3 | 0.333 [0.061, 0.792] |
| preference | 0 / 0 | n/a |

（lenient 只有 struggle 變成 7/24 = 0.292，其他相同。）

### 4.3 依 Lite-Mem category 的 Precision（strict）

| Lite-Mem category | TP / 萃取數 | Precision [95% CI] |
|---|---|---|
| learning | 6 / 8 | 0.750 [0.409, 0.929] |
| general | 1 / 3 | 0.333 [0.061, 0.792] |
| skill | 0 / 2 | 0.000 [0.000, 0.658] |
| identity | 1 / 1 | 1.000 [0.207, 1.000] |
| education | 0 / 1 | 0.000 [0.000, 0.793] |
| social | 0 / 1 | 0.000 [0.000, 0.793] |

`learning` 類別相對可靠。`skill`／`social`／`education` 在學習對話裡幾乎都是誤觸發，例如「用X」被當成技能，「…是什麼」被當成社交。

### 4.4 訊息層級：學習困難偵測（gold 正例 24 / 50）

| 系統判定 | TP | FP | FN | TN | Precision [95% CI] | Recall [95% CI] | F1 |
|---|---|---|---|---|---|---|---|
| 萃取事實帶困難語句 | 6 | 0 | 18 | 26 | 1.000 [0.610, 1.000] | 0.250 [0.120, 0.449] | 0.400 |
| `analyze_student` 算成 struggle（儀表板） | 3 | 0 | 21 | 26 | 1.000 [0.438, 1.000] | 0.125 [0.043, 0.310] | 0.222 |

儀表板的 3 個 TP 是 sem-021、sem-022（萃取事實沒有課程前綴）和 demo-1005-s2-0（走 fallback，而且因為 demo 樣本沒有 topic，`Q:` 前面沒有 `[課程]`）。sem-021 被 analytics 歸到的主題是「判斷」，學生實際卡的是「進步性」，所以**主題也是錯的**。

## 5. 錯誤分析

### 5.1 典型 FN（漏抽，21 個中的主要模式）

| 模式 | 例子（sample_id） | 原因 |
|---|---|---|
| 困難用語不在觸發詞表裡 | 「搞不清楚」(sem-005)、「又搞混了」(sem-033)、「看不出差異」(sem-020)、「每次都記反」(sem-045)、「背不起來」(sem-027)、「分不出來」(sem-015) | 規則只認「不懂／不會／搞不懂／一直搞混」等少數寫法 |
| 被老師或考試判錯 | 「老師說我寫錯了」(sem-006)、「寫 quicksort 結果錯了」(sem-012)、「Teacher said it's too vague」(sem-018)、「寫了三遍都被退」(mt-2-0) | 規則沒有「作答被判錯 = 困難」的概念 |
| 觸發詞存在但被切分規則漏掉 | 「BST 我看圖看不懂」(sem-043) | 同樣含「看不懂」，句型不同就沒命中 |
| 情意、情境 | 「老師講得太快了」(mt-0-0)、「想看完再寫期中報告」(sem-029) | 沒有對應規則 |
| 英文學習困難 | sem-018 | 英文規則以個人資料為主（allergic、live in、work at…） |

### 5.2 典型 FP（誤抽，8 個）

| 類型 | 例子 | 說明 |
|---|---|---|
| 問句片段被當成事實 | 「用inorder」(sem-001, skill)、「用chaining」(mt-1-2, skill)、「申請整個流程是什麼」(sem-035, social)、「不能處理負邊」(sem-004, general) | 觸發詞「用」「流程」「不能」命中了學科內容，不是學生狀態 |
| 語意錯亂 | 「就讀不不適合資工系」(sem-017, education) | 規則改寫時產生雙重否定，意思和原句相反 |
| 重複 | 「[資料結構]完全不懂」(mt-0-0)、「不太懂為什麼要這個原則」(sem-022) | 同一個困難被抽兩次，其中一則沒有主題 |

### 5.3 敏感度：如果把一次性學習形式請求也算成 preference

標註表 notes 裡有 7 則標了 `possible_pref`（sem-015、027、032、035、042、043、045），stub 一則都沒有抽到。如果把它們也列為 gold：

- strict Recall 降到 8/36 = 0.222
- lenient Recall 降到 9/36 = 0.250
- Precision 不變

### 5.4 下游問題（不是萃取器本身的問題，但會影響實際效果）

1. **課程前綴吃掉 struggle**：`analyze_student` 的判斷順序是 `_STRUGGLE_RE` → `_PREFERENCE_RE` → `_QUESTION_RE` → `_TOPIC_RE`，最後才做自然語言判斷。前端一定會帶 `topic`，所以：
   - fallback 的 `"[課程] Q: …"` 一律被當成提問。
   - 像「[資料結構] 那 bst完全不懂」這類保留了前綴的萃取事實也一樣，**永遠不會被算成 struggle**。
   - `diagnostics.py` docstring 說「stub extractor never emits one」，指的是 stub 從來不產生 `Struggling with:` 格式，這點正確。但 stub 其實會產生帶「不懂」的 `learning` 事實，只是多半在這一關被過濾掉。
2. **主題抽取**：`_extract_natural_topic` 只認「」引號、大寫縮寫、「什麼是／為什麼／怎麼 X」三種模式。所以「搞不懂進步性怎麼判斷」的主題變成「判斷」。
3. 本評估**沒有修改**任何產品程式碼或 Lite-Mem。上面的觀察留給後續決定要不要處理，例如：
   - 改用 LLM 萃取器（`extractor="gemini"`，或傳入萃取器物件）
   - 調整 analytics 的判斷順序
   - 在 `/chat` 補一個 struggle 偵測

## 6. 限制

1. **AI 標註，不是人工標註**。gold 標註與 TP/FP/FN 判定都由 Claude Opus 5.5 完成，只有單一標註者，沒有標註者間一致性（inter-annotator agreement）。判準本身也有主觀成分，例如 sem-004「解釋不夠具體」和 sem-042「開卷翻不到公式」是否算 struggle、strict 與 lenient 的界線。
2. **樣本來源是示範對話，不是真實學生**。這些對話是開發團隊為了 demo 寫的，困難表述比真實學生更集中、更「教科書式」（24/50 有困難），用語分布也和真實學生不同。真實語料上的 recall 可能更高，也可能更低，無法從這裡推論。
3. **n = 50**，而且母體只有 73 則，抽樣比例 68%，同一位學生、同一個 session 的訊息不獨立。區間很寬，例如 strict Precision 的 95% Wilson 區間是 [0.28, 0.72]。這裡沒有做有限母體校正，也沒有做群集校正。
4. 每則訊息都是在**全新、空白的記憶**上單獨評估。production 中同一位學生的事實會經過 Lite-Mem 的 upsert 去重或合併，這部分不在本評估範圍內。
5. `demo_conversations` 的 8 則樣本沒有課程，所以 topic 為空。真實前端一定會帶課名，在那種情況下 demo-1005-s2-0 不會被儀表板算成 struggle，儀表板 recall 會從 3/24 降到 2/24。
6. 結果綁定 `litemem` 0.4.0。版本升級後，`score` 會偵測到萃取輸出改變並直接報錯，必須重新標註。

## 7. 檔案

| 檔案 | 用途 |
|---|---|
| `scripts/eval_extraction.py` | 抽樣、重播 production 萃取路徑、產生標註表、計分（Wilson 區間與 bootstrap） |
| `eval/extraction_labels_2026-11-04.csv` | 50 筆標註表（UTF-8 with BOM，可以直接用 Excel 開）。每一列的 notes 都以 `[標註者: AI (Claude Opus 5.5)]` 開頭 |
| `tests/test_eval_extraction.py` | 驗證抽樣可重現、統計公式正確、標註表能重算出本報告的數字、萃取輸出沒有漂移 |

標註表欄位：

| 欄位 | 意義 |
|---|---|
| `sample_id` / `source` / `student` / `course` | 樣本來源（`sem-NNN` = CONVERSATIONS 索引；`mt-i-j` = 第 i 個多輪 session 的第 j 輪；`demo-…` = demo_conversations） |
| `user_content` | 實際餵給萃取器的使用者訊息（含 `[課名]` 前綴） |
| `extracted_facts` | 萃取器輸出，JSON：`[{"text", "category"}]` |
| `stored_via_fallback` | 1 = 沒抽到東西，改存原始 Q/A |
| `analytics_struggles` | `analyze_student` 對該訊息算出的 struggle（`主題 | 細節`） |
| `gold_facts` | gold，JSON：`[{"id": "g1", "type": "struggle|affect|preference|context", "topic", "desc"}]` |
| `gold_struggle` | 訊息層級 gold（0/1） |
| `match_strict` / `match_lenient` | 依 `extracted_facts` 的順序，每個萃取事實對應的 gold id 或 `-`，以 `;` 分隔 |
| `notes` | 標註理由 |

## 8. 如何人工複核並重算

1. 用 Excel 或文字編輯器開啟 `eval/extraction_labels_2026-11-04.csv`。**只改** `gold_facts`、`gold_struggle`、`match_strict`、`match_lenient`、`notes`。複核後建議把 notes 的標註者改成複核人的名字。
2. 重算：

   ```powershell
   uv run python scripts/eval_extraction.py score                 # 文字報表
   uv run python scripts/eval_extraction.py score --json          # 完整 JSON
   ```

   `score` 會重新抽樣並重跑萃取器。如果 sample id、`extracted_facts` 或 `analytics_struggles` 和現況不一致，會直接報錯，避免用過期的標註算出數字。格式錯誤也會報錯，例如 match 數量和萃取事實數不符、同一個 gold 被配對兩次、gold id 不存在。
3. 如果修改了 gold，`tests/test_eval_extraction.py::test_labels_file_reproduces_reported_numbers` 裡寫死的數字也要一起更新，並同步修改本報告第 1、4 節。
4. 要產生新的空白標註表（例如換種子或換語料）：

   ```powershell
   uv run python scripts/eval_extraction.py sheet --out eval/new_sheet.csv
   ```

## 9. 2026-11-06 修正：教師端的困難判斷

這次修改的是 EduInsight 的 `analytics.analyze_student`，**沒有修改萃取器或 Lite-Mem**，所以第 4.1 到 4.3 節的萃取數字不變。gold 標註也沒有更動。

修改內容：

- 帶 `[課程]` 前綴的事實，現在也會檢查學生的話裡有沒有困難用語。
- 助理回覆（`A:`）一律不算學生的困難。原本沒有前綴的回覆可能被誤判。
- 補上第 5.1 節漏掉的用語：「看不出」「記反」「背不起來」「記不住」。
- 主題優先取困難用語後面的詞，例如「搞不懂進步性怎麼判斷」的主題是「進步性」，不再是「判斷」。抓不到具體主題時，以課程名稱當主題。

同一份 50 則樣本的訊息層級結果（gold 正例 24 / 50）：

| `analyze_student` 算成 struggle | TP | FP | FN | TN | Precision [95% CI] | Recall [95% CI] | F1 |
|---|---|---|---|---|---|---|---|
| 修正前 | 3 | 0 | 21 | 26 | 1.000 [0.438, 1.000] | 0.125 [0.043, 0.310] | 0.222 |
| 修正後 | 14 | 1 | 10 | 25 | 0.933 [0.702, 0.988] | 0.583 [0.388, 0.755] | 0.718 |

解讀時要注意：

1. **這份樣本同時用來找問題和驗收，數字會偏樂觀。** 新增的用語正是從這份樣本的漏判整理出來的，所以這不是獨立測試集的結果。
2. 第 6 節的限制仍然適用：AI 標註、示範對話、n = 50。
3. 新增 1 個誤判是 sem-023：「我朋友…不確定合不合法」說的是第三人。
4. 其餘 10 個漏判主要是兩種：學生被老師或考試判錯但沒有說自己不懂；或萃取器抽到別的片段，原始訊息沒有存進記憶。這些都需要改善萃取才能解決。
5. 第 2 節描述的 `[課程]` 前綴來自舊的 `static/student.html`。2026-11-06 檢查正式環境資料時，Next 前端存下的是沒有前綴的 `Q:`／`A:`，所以有前綴和沒有前綴的情況都要能判斷。
6. 主題仍然不完全準確，例如 sem-005 的主題是引號裡的「鎖定客群」，有些則退回課程名稱。

### 同時修正的兩個問題（2026-11-07）

用學期模擬資料重跑時，發現本報告沒有測到的兩個問題。本報告每則訊息都在空白記憶上單獨評估，所以看不出來：

1. **學生的問題互相覆蓋。** Lite-Mem 以 ASCII 冒號前的文字當作事實的鍵（沒有冒號時取前 20 個字元），所以 `Q: ...` 每次都會蓋掉前一筆，一位學生只留得住最近一題。現在改用全形冒號 `Q：`。開頭 18 個字完全相同的問題仍會合併成一筆，開頭相同的 AI 回答也一樣。
2. **診斷混入其他課程。** 記憶是以學生為單位，所以每門課的診斷都包含學生的所有科目。現在 `/chat` 會把事實連到對話，診斷只讀該課程的對話所產生的事實。沒有連到對話的舊事實，所有課程都會讀到。

`analyze_student` 的輸出改變後，要用目前的輸出更新標註表的 `analytics_struggles` 欄，否則 `score` 會報錯。
