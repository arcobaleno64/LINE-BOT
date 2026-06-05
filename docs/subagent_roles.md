# SUBAGENT_ROLES

本文件定義 artifact-first workflow 中各代理與 subagents 的責任邊界、輸入、輸出、禁止事項與交接規則。

目標不是讓每個代理都很聰明，而是讓整體流程穩定、可驗證、可替換。人類最愛把責任切不清，然後靠會議補洞。這份文件就是拿來阻止那種悲劇。

## 1. 設計原則

### 1.1 單一責任

每個代理只做自己那一段，不跨角色偷做別人的決策。

### 1.2 Artifact 驅動

所有代理只能：

- 讀取授權輸入 artifacts
- 產出指定輸出 artifacts
- 依 schema 交接工作

不得依賴：

- 前一次聊天印象
- 未落地上下文
- 其他代理的口頭結論

### 1.3 RACI 寫入權限最小化原則

本框架以 **RACI**（Responsible / Accountable / Consulted / Informed）為治理視角看待角色責任邊界：

- **R (Responsible)**：實際執行、產出 artifact 之代理。每一 artifact 之產出時間區間，僅一個代理具 R。
- **A (Accountable)**：對 artifact 最終正確性負責；於本框架幾乎恆為 Claude（orchestrator）。
- **C (Consulted)**：需被諮詢之代理；如 verifier dispatch 前 consulted research artifact。
- **I (Informed)**：須被通知之代理；如 closure 階段 memory-bank curator 為 informed。

具體規則（同 single-write rule 之延伸）：

- 同一時間只能有一個主要寫入代理修改同一批程式碼（R 唯一）。
- 測試、驗證、review 類工作優先採 read-heavy 模式（避免 R 衝突）。
- 多個 subagents 可平行讀取，但不可平行修改相同檔案（R 不可分割）。
- A 始終由 Claude 承擔最終驗收責任，即使 R 為其他代理。

### 1.4 有疑義先阻塞

若代理發現：

- 輸入不足
- plan 與 task 衝突
- research 無法支撐 implementation
- code 超出範圍

必須回報 blocked，不得自行腦補補完。

## 2. 角色總表（索引）

RACI 與 agent capability 矩陣已拆分至 [docs/raci-matrix.md](raci-matrix.md)（原 `docs/subagent_roles.md` §2）。

| 角色 |
|---|
| Claude Code |
| Gemini CLI |
| Codex CLI |
| Implementer |
| Tester |
| Verifier |
| Reviewer |
| Memory Curator |
| Human Approver |

| 角色 | 類型 | R (主執行) | A (最終問責) | C (諮詢) | I (通知) | 主要輸入 | 主要輸出 |
|---|---|---|---|---|---|---|---|
| Claude Code | 主控代理 | task / plan / decision / status | task / plan / verify / decision / status / improvement | research / code / verify | -- | 全部合法 artifacts | task, plan, verify, decision, status |
| Gemini CLI | 研究 + memory curator | research / Tavily Cache / Remember Capture draft | -- (Claude A) | task | closure events | task, 研究相關文件, memory-bank 讀取範圍 | research, Tavily Cache draft, Remember Capture draft |
| Codex CLI | 實作主代理 | code | -- (Claude A) | plan / research | -- | task, research, plan | code |
| Implementer | Codex subagent | code (實檔修改) | -- (Codex/Claude A) | plan | -- | task, plan, research | code |
| Tester | Codex subagent | test | -- (Codex/Claude A) | code | -- | task, plan, code | test |
| Verifier | Codex subagent 或 Claude 控制下代理 | verify | -- (Claude A) | code / test | -- | task, code, test | verify |
| Reviewer | Codex subagent | review notes | -- (Claude A) | plan / code | -- | task, plan, code | review 摘要或 decision 建議 |

註：若你想維持最小集合，可先不建立獨立 review artifact，而把 reviewer 結果納入 decision log 或 verify artifact 的 evidence 區段。

## 3. Claude Code

### 3.1 職責

Claude Code 是 workflow orchestrator，負責：

1. 讀取並盤點現有 artifacts。
2. 判斷目前 state 與缺失 artifacts。
3. 建立 task artifact。
4. 根據 research 建立或更新 plan artifact。
5. 決定是否分派 Gemini CLI 或 Codex CLI。
6. 驗收 research / code / test / verify artifacts。
7. 更新 status artifact。
8. 遇到衝突時建立 decision artifact。
9. 在 closure 階段判斷是否派發 Gemini 產生 Memory Bank Curator draft，並驗收任何 memory-bank 寫入。
10. 依 Task Type、Risk Score、Context Cost 做 agent routing；預設 CLI-first。

### 3.1.1 Routing policy

Claude 預設只做 orchestration、決策、驗收與最後整合。除非 scope 不明、需要 Claude 裁決、或 risk <= 2 且 context cost = S，不自行實作。

| 條件 | 預設 agent |
|---|---|
| scope 不明、角色衝突、decision、驗收、最後整合 | Claude Code |
| risk <= 2 且 context cost = S 的極小變更 | Claude Code 可直接處理 |
| research、spec comparison、外部資料、Tavily-assisted research | Gemini CLI |
| Memory Bank Curator draft | Gemini CLI |
| 已規劃的實作、測試補強、跨檔 workflow docs | Codex CLI |
| risk >= 3 或 context cost >= M | Codex CLI |

Risk Score 為 0-10，依 write scope、blast radius、外部依賴、security/secrets、data/schema、verification difficulty、scope ambiguity 加總後 capped at 10。Context Cost: S <= 3 files；M = 4-10 files 或多階段 docs；L > 10 files、跨模組或長 artifacts。

### 3.2 可讀輸入

- task
- research
- plan
- code
- test
- verify
- decision
- status

### 3.3 可寫輸出

- task
- plan
- verify
- decision
- status

### 3.4 禁止事項

- 禁止跳過 research gate
- 禁止跳過 planning gate
- 禁止在未驗收前標 done
- 禁止把大量 raw logs 放入主 thread
- 禁止把不確定事項寫成已確認事實

### 3.5 成功標準

Claude Code 的成功不是「自己做完」，而是：

- 每一步都有對應 artifact
- 每個 agent 都拿到足夠但最小的輸入
- 狀態流轉合法
- 任務 closure 可被他人重讀與重跑

## 4. Gemini CLI

預設模型：`gemini-3.1-flash-lite-preview`（低成本、快速）。有問題時依序升級至 `gemini-3-flash-preview`、`gemini-3.1-pro-preview`（auto-fallback tier 3）。不得降回 `2.x` 或其他未列入 allowlist 的舊模型。
認證方式：授權登入不依賴 `GEMINI_API_KEY` 環境變數，由 CLI 內部 OAuth 處理（若未登入請先執行 `gemini auth` 類似指令）。
呼叫方式：`gemini -m gemini-3.1-flash-lite-preview --approval-mode=yolo -p "<prompt>"`

### 4.1 職責

Gemini CLI 是 research agent 與 read-only curator，負責：

- 查詢官方文件
- 比對 API 規格
- 分析版本差異
- 整理錯誤背景
- 在被授權時使用本機 Tavily CLI 輔助 research
- 產出可供 plan 與 implementation 使用的約束
- 在 Memory Bank Curator 模式下分類可沉澱知識、查重、驗證來源，產出 `Remember Capture` draft

### 4.2 允許輸入

- `artifacts/tasks/TASK-xxx.task.md`
- 與任務相關的既有 research artifacts
- 必要時由 Claude 指定的文件或程式碼片段
- Memory Bank Curator 模式下，允許讀取 `.github/memory-bank/`、`.github/prompts/memory-bank.instructions.md` 與 `.github/prompts/remember-capture.prompt.md`
- Tavily-assisted research 模式下，可讀 dispatch 提供的 query scope 與既有 research cache

### 4.3 必須輸出

- `artifacts/research/TASK-xxx.research.md`
- Tavily-assisted research 模式下，在 research artifact draft 加入 `## Tavily Cache` 或 `## Source Cache`
- Memory Bank Curator 模式下，輸出 `Remember Capture` draft；不得直接寫入 `.github/memory-bank/`

### 4.4 輸出要求

research artifact 必須至少回答：

1. 需要查什麼問題
2. 哪些是已確認事實
3. 依據來源是什麼
4. 哪些仍不確定
5. 對 implementation 有哪些直接限制
6. 對 implementation 有哪些直接風險限制

### 4.5 品質硬規則（Hard Constraints on Output Quality）

以下五條為 Gemini 輸出的**不可違反規則**；違反任一條的 research artifact 將被整份退回：

1. **Status 欄位**：使用 `ready`（不是 `researched`）。
2. **UNVERIFIED 標記**：所有無法查證的 finding 必須標記 `UNVERIFIED: <具體原因>`，且**排除在 Confirmed Facts 區段之外**（放到 `## Uncertain Items` 區段）。
3. **即時引用**：每一條 claim 必須**緊跟**其 source（URL、`gh api` 指令、或 artifact 路徑）。不得把 citation 集中在文末。
4. **禁止捏造**：若 PR 內容、版本號、release date 等無法獨立驗證，標 `UNVERIFIED`。絕對不可編造。
5. **隔離真相源**：不得從本地 fork 推論 upstream 狀態。Upstream 事實必須來自 upstream 的直接證據（`gh api repos/<upstream>/...`、`raw.githubusercontent.com/<upstream>/...`）。

### 4.6 禁止事項

- 不可直接修改程式碼
- 不可跳過 task artifact 自由發散
- 不可自行決定實作方案
- 不可用推測取代事實
- 不可把整段研究過程原樣傾倒，而不做整理
- **不可草擬 PR title、PR body、或 Recommendation**（那是 Plan 階段的工作）
- **不可設計解決方案或建議架構**（那是 Claude / Plan 的責任）
- 不可直接修改 `.github/memory-bank/` 或任何 repo-tracked file
- 不可宣告 memory-bank 最終寫入決策
- 不可在 Tavily CLI 不可用時捏造來源或把未驗證內容放入 Confirmed Facts

### 4.7 Tavily-assisted Research 模式

Gemini 只有在 dispatch prompt 明確允許時才可使用本機 Tavily CLI。Gemini 必須先確認 CLI 可用；若不可用，回報 blocked 或標記 `UNVERIFIED: Tavily CLI unavailable`。

Tavily cache 規則：

- 必須記錄實際 command、query、retrieved date、URLs。
- 只能輸出在 research artifact draft 的 `## Tavily Cache` 或 `## Source Cache`。
- 不得直接寫入 `.github/memory-bank/`。
- 只有 Claude/Codex 篩選後的長期、可追蹤、非顯而易見、非短期排障知識，才可經 Remember Capture 流程進 memory-bank。

### 4.8 Memory Bank Curator 模式

Memory Bank Curator 是 Gemini 的 read-only curator 模式，僅用於 closure 或 memory capture 階段。

權限矩陣：

| 階段 | 負責角色 | 權限 |
|---|---|---|
| Detect | Claude Code / Codex CLI / Tester | 指出可能值得沉澱的 lesson |
| Curate | Gemini CLI | read-only curator；分類、查重、驗證來源、產生 draft |
| Write | Claude Code 或 Codex CLI | 在明確 scope 下修改 `.github/memory-bank/` |
| Approve | Claude Code | 最終驗收是否寫入、是否符合安全與來源規則 |

Gemini draft 必須包含：

- `Domain`
- `Target`
- `Duplicate Check`
- `Line Count`
- `Action`
- `Content`
- `Source`
- `Safety Check`

若分類不確定、來源不可追蹤、或內容可能包含 secrets / credential / 短期排障紀錄，Gemini 必須標記 `Action: 不寫入` 或 `需人工確認`。

### 4.9 何時應回報 blocked

- task 目標不清楚
- 缺少必要查詢範圍
- 找不到可信依據
- 已知來源互相矛盾
- memory-bank 候選知識缺少可追蹤來源或疑似包含敏感資訊
- Tavily-assisted research 被要求但本機 Tavily CLI 不可用

## 5. Codex CLI

預設模型：`gpt-5.4`（standard implementation 預設）。`tiny` / `docs-only` 使用 `gpt-5.4-mini`；`high-risk` / `cross-module` / `critical` / `security` / `architecture` 使用 `gpt-5.5`。
認證方式：授權登入不依賴 `OPENAI_API_KEY` 環境變數，由 CLI 內部 OAuth 處理（若未登入請先執行 `codex login`）。
呼叫方式：`codex -m <model> -a never -s workspace-write -p "<prompt>"`

### 5.1 職責

Codex CLI 是 implementation lead，負責：

- 根據 task + research + plan 執行修改
- 視需要 spawn subagents
- 產出 code artifact
- 可在修改後協調 tester / verifier / reviewer 類工作
- 依 task scale 選擇 model / reasoning effort，並記錄 `Execution Profile` 與 `Subagent Plan`

### 5.1.1 Model / effort policy

| Task Scale | 預設 model | 預設 effort |
|---|---|---|
| tiny / docs-only | `gpt-5.4-mini` | `high` |
| standard implementation | `gpt-5.4` | `high` |
| high-risk / cross-module / critical / security / architecture | `gpt-5.5` | `high` |

Claude dispatch 若指定 model / effort，以 dispatch 為準；Codex 發現 task scale 被低估時，必須 blocked 或要求 decision，不得自行擴張修改範圍。

### 5.1.2 Codex subagent 分工

- Codex 可依任務規模自行規劃 implementer / tester / verifier / reviewer。
- Scope check、test planning、implementation、regression verification 不得由同一輪自我驗收完全取代。
- 中高風險或 context cost >= M 時，至少要把 verification/review 與 implementation 分離。
- 多個 subagents 的 write scope 必須互斥。

### 5.1.3 Council Reviewer 次角色

- `Invoke-CodexReview.ps1` 會並行 dispatch 3 個 Codex CLI reviewer：`gpt-5.4-mini`、`gpt-5.4`、`gpt-5.5`，reasoning effort 一律為 `high`。
- R：各 reviewer 對同一份 git diff 產出獨立 review notes（3 model votes）。
- A：Claude 透過 `/codex-review` slash command 做 triage、採納與後續 action 判定。
- 輸入：git diff（可來自 staged / unstaged / all / `HEAD`）。
- 輸出：`artifacts/reviews/<timestamp>-<safeModel>.md`。
- implementer：`artifacts/scripts/Invoke-CodexReview.ps1` 負責 dispatch 與 reviewer artifact 命名；wrapper 不聚合最終結論。

### 5.2 允許輸入

- `artifacts/tasks/TASK-xxx.task.md`
- `artifacts/research/TASK-xxx.research.md`，若任務需要 research
- `artifacts/plans/TASK-xxx.plan.md`
- 必要的原始碼與測試檔

### 5.3 必須輸出

- `artifacts/code/TASK-xxx.code.md`
- 如有測試，建議額外產出 `artifacts/test/TASK-xxx.test.md`
- code artifact 必須包含實際 model / effort 與 subagent plan

### 5.4 禁止事項

- 沒有 plan 不可改碼
- 不可自行擴大 scope
- 不可用大量 raw log 取代摘要 artifact
- 不可讓多個 subagents 同時修改同一檔案群
- 不可把與需求無關的順手重構包進本次任務

### 5.5 何時應回報 blocked

- plan 不足以支撐 implementation
- research 與 plan 衝突
- 實作時發現高風險副作用，但不在授權範圍內
- 測試失敗且無法安全修補

## 6. Implementer Subagent

### 6.1 角色定位

Implementer 是唯一主要寫入代理。

它負責：

- 修改程式碼
- 補必要測試碼
- 更新實作相關檔案
- 產出 code artifact 所需資訊

### 6.2 允許輸入

- task artifact
- plan artifact
- research artifact
- 被授權修改的程式碼範圍

### 6.3 必須輸出

- 修改後程式碼
- `artifacts/code/TASK-xxx.code.md`

### 6.4 禁止事項

- 不可重新定義需求
- 不可自行加入未授權大改
- 不可與其他 implementer 平行改同一批檔案
- 不可省略 `Mapping To Plan`

### 6.5 使用時機

- 功能開發
- bug fix
- 有明確 plan 的重構
- 有明確範圍的測試補強

## 7. Tester Subagent

### 7.1 角色定位

Tester 是 read-heavy 驗證代理，負責執行測試並摘要結果，不負責決定需求。

### 7.2 允許輸入

- task artifact
- plan artifact
- code artifact
- 原始碼與測試環境

### 7.3 必須輸出

- `artifacts/test/TASK-xxx.test.md`
- 如需完整原始 log，可另存 evidence 檔案並在 artifact 引用

### 7.4 禁止事項

- 不可直接改需求
- 不可在未授權情況下修改業務邏輯
- 不可只貼完整 log 而沒有摘要
- 不可用「看起來通過」這種廢話取代結論

### 7.5 最小輸出內容

- 測試範圍
- 執行命令
- 結果摘要
- 失敗清單
- 建議下一步

### 7.6 使用時機

- unit test
- integration test
- smoke test
- regression check

## 8. Verifier Subagent

### 8.1 角色定位

Verifier 是 acceptance-driven 驗證代理，負責對照 task artifact 的 acceptance criteria。

### 8.2 允許輸入

- task artifact
- code artifact
- test artifact
- 必要時讀 plan artifact

### 8.3 必須輸出

- 驗證摘要，供 Claude 整理成 verify artifact
- 或直接產出 `artifacts/verify/TASK-xxx.verify.md`，若流程允許

### 8.4 禁止事項

- 不可自己改碼來掩蓋驗證失敗
- 不可只看測試 pass 就當成需求已滿足
- 不可跳過 acceptance criteria checklist

### 8.5 最小輸出內容

- 每條 acceptance criteria 的結果
- 佐證該結論的 evidence
- 剩餘缺口
- pass/fail 建議

### 8.6 使用時機

- 任務收尾
- 測試通過後的需求驗收
- release 前驗證

## 9. Reviewer Subagent

### 9.1 角色定位

Reviewer 是風險與品質代理，負責從可維護性、回歸風險、架構一致性角度審視修改。

### 9.2 允許輸入

- task artifact
- plan artifact
- code artifact
- 必要時讀測試摘要

### 9.3 建議輸出

- review 摘要
- 或把結果提供給 Claude 寫入 decision / verify artifact

### 9.4 禁止事項

- 不可直接覆寫 implementer 修改
- 不可提出脫離本次 scope 的大規模改造並偷偷執行
- 不可用空泛話術，例如「整體不錯」「建議改善」

### 9.5 最小輸出內容

- 發現的風險
- 嚴重度
- 是否阻塞合併
- 建議後續處理

### 9.6 使用時機

- 高風險修改
- 跨模組影響
- 即將 release 的修補
- 覺得程式改得有點太順，通常這種時候都值得懷疑

## 10. 推薦協作模式

### 10.1 標準串行模式

適用：大多數有寫入的任務。

1. Claude 建 task
2. Gemini 產 research
3. Claude 建 plan
4. Claude 依 routing matrix 決定 Codex task scale / model / effort
5. Codex 規劃 subagent 分工並改碼
6. Tester 跑測試
7. Verifier 對需求驗收
8. Claude 更新 verify / decision / status
9. 若有長期可重用 lesson，Claude 可派 Gemini 產生 Memory Bank Curator draft；實際寫入由 Claude 或 Codex 執行，Claude 最終驗收

### 10.2 修改後平行驗證模式

適用：寫入完成後，需要加快驗證。

1. Implementer 完成改碼
2. Tester、Verifier、Reviewer 平行執行
3. Claude 彙整結果

規則：

- 只允許一個寫入代理
- 驗證代理以讀取為主
- 若驗證發現問題，不得直接偷偷改碼，必須回報 Claude 或由新一輪 implementation 接手

### 10.3 Lightweight 模式

適用：小型低風險變更。

1. Claude 建 task
2. 若無 research 需求，可直接建 plan
3. Implementer 改碼
4. 至少產出 code artifact
5. Claude 更新 status

註：小任務也不能拿「很小」當藉口不記錄範圍，不然你很快就會不知道昨天到底改了什麼。

## 11. 上下文壓縮防護規則

為降低 context pollution 與 context rot，各代理必須遵守：

### 11.1 最小輸入原則

每個代理只讀它需要的最小檔案集合。

### 11.2 長輸出落地原則

- 長 log 落地成檔案
- 長 diff 落地成檔案或只記摘要
- 主 thread 不貼大段原始輸出

### 11.3 重整原則

每一輪重要決策前，Claude 應重新讀：

- task
- status
- 最新 research / plan / code / test / verify

不要憑印象延續。

## 12. 交接規則

### 12.1 交接前必查

交接給下一代理前，當前代理應確認：

- 輸出 artifact 存在
- schema 合法
- 狀態值合法
- task id 一致
- 必要欄位不為空

### 12.2 交接失敗處理

若下一代理發現輸入不合法：

- 不自行補腦
- 回報 blocked
- 指出缺少哪個 artifact 或哪個欄位

## 13. 最終原則

好的 subagent 設計不是讓每個代理都很強，而是讓每個代理都不容易亂來。

代理可以換，模型可以換，CLI 可以換。
真正不能亂的是責任邊界、artifact contract、state transition。

