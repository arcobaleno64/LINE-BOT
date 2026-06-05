# Agentic Execution Layer — TAO/ReAct 契約

本文件定義代理人執行層之微觀循環 TAO（Thought-Action-Observation / ReAct），是 [orchestration.md §2.8](orchestration.md) 兩層架構之執行層 schema 規範。

> 兩層粒度：管理層 PDCA 跨任務（Intake → Closure）；執行層 TAO 單步（subagent 一次 dispatch 之內）。詳見 [orchestration.md §2.8](orchestration.md)。

## 1. 適用對象

TAO trace 適用於 [docs/subagent_roles.md](subagent_roles.md) 所列 subagent 之每一次 dispatch：

| Subagent | TAO 必要程度 | 落點 artifact |
|---|---|---|
| Implementer | **必填**（risk ≥ 3）；可省（risk ≤ 2 或 docs-only） | code artifact `## TAO Trace` |
| Verifier | **必填**（risk ≥ 3） | verify artifact `## TAO Trace` |
| Tester | 建議 | test artifact 或 code artifact `## TAO Trace` |
| Reviewer | 建議 | verify artifact 或 decision artifact `## TAO Trace` |
| Memory Curator | 免（curator 之內隱循環已在 [`.github/prompts/remember-capture.prompt.md`](../.github/prompts/remember-capture.prompt.md) 規範） | -- |

**Risk 門檻判定**：取自 plan artifact 之 `## Risks` 區段最大 Severity。任一條 `Severity: blocking` 即視為 risk ≥ 3。

**Lightweight 任務**：plan 之 `lightweight: true` 或無 plan 而走精簡流程之 task，TAO trace 全部可省。

## 2. Schema 必填欄位

每次 TAO 循環一個 step 須含以下四欄。一次 dispatch 可有 1-N 個 step，依 subagent 實際決策節點數而定。

```md
## TAO Trace

### Step 1
- Thought Log: <一段散文，描述讀入 plan / artifact 後對下一步的判斷與假設；至少 1 句、不超過 5 句>
- Action Step: <一句話描述具體動作；必含動詞與目標檔案 / 命令>
- Observation: <Action 之實際結果；含 stdout 摘要、檔案變動、test 結果之關鍵數值或例外>
- Next-Step Decision: <continue | halt | escalate；continue 須說明下一 step 假設依據；halt / escalate 須引用 mismatch 條件>

### Step 2
...
```

### 2.1 欄位約束

| 欄位 | 必須 | Expected Length | Required Keywords |
|---|---|---|---|
| `Thought Log` | yes | 1-5 句 | 至少包含「讀」、「判定」、「假設」、「驗」之一動詞 |
| `Action Step` | yes | 1 句 | 必含具體動詞（修、跑、寫、刪、移、查）+ 目標（檔名 / 命令 / 函式名） |
| `Observation` | yes | 1-3 句 | 必含可驗證證據（stdout 片段、test 結果、commit hash、行號等） |
| `Next-Step Decision` | yes | 一個 token + 短說明 | token ∈ {`continue`, `halt`, `escalate`}；非 `continue` 須附 `mismatch_reason:` |

### 2.2 Step 編號

- 必以 `### Step N` 為章節，N 從 1 起遞增、連續、不可跳號。
- 一次 dispatch 之 TAO Trace 之 step 數須 ≥ 1 且 ≤ 50；超過 50 視為 dispatch scope 過大，須拆分。

## 3. Mismatch 處理（Observation 與 Thought 預期不符）

當 subagent 之 `Observation` 與 `Thought Log` 中之假設不符時：

1. **不可硬撐**：subagent 不得自行修改假設、繼續執行、或重試多次。
2. **產出 mismatch 條目**：本 step 之 `Observation` 必須以 `Observation: mismatch — <對比>` 開頭，明示預期 vs. 實際。
3. **Next-Step Decision = halt 或 escalate**：
   - `halt`：subagent 結束本次 dispatch，產出局部 artifact 與 TAO Trace 至 mismatch step 為止，回報管理層。
   - `escalate`：管理層判定為 plan 不足，須建 decision artifact 或 improvement artifact 後再走 mini-PDCA 子循環（即 blocked → improvement → re-plan）。
4. **Claude 為唯一裁決者**：subagent 不得自行決定是否 `escalate`；只能標 `halt` 並待 Claude 處置。

mini-PDCA 子循環為 [orchestration.md §2.8](orchestration.md) 所定義之執行層 → 管理層 escalation 路徑，本 task 僅文件化觸發條件，不實作自動化。

## 4. 完整範例

### 4.1 範例 A：risk ≥ 3 之 implementer dispatch（必填）

```md
## TAO Trace

### Step 1
- Thought Log: 讀 plan §Phase 1.1，判定須在 docs/orchestration.md 既有 §2.7 與 §3 之間插入新 §2.8 兩層架構章節。假設 §2 為核心原則章節，已含 §2.1-2.7；新章節作為 §2.8 不需重新編號其他段落。
- Action Step: Edit docs/orchestration.md，於 §2.7 末尾段「若 routing 判斷與既有架構衝突...」與「## 3. 角色分工」之間插入 §2.8 章節。
- Observation: Edit 成功；diff 顯示 39 行新增，無其他段落變動；§3 章節編號未動。
- Next-Step Decision: continue（§2.8 已就位，下一 step 處理 §5 標籤）

### Step 2
- Thought Log: 讀 plan §Phase 1.2，判定須對 docs/schemas/artifact-spec-task.md §5.1-5.9 各章節加 PDCA 標籤。假設每節之首行下加一行 `> PDCA Stage: X` blockquote 即可。
- Action Step: 對 §5.1, §5.2, §5.3, §5.4, §5.5, §5.6, §5.7, §5.8, §5.9 共 9 節分別執行 Edit，加入對應 PDCA 標籤。
- Observation: 9 個 Edit 全成；grep 驗證 9 行 `> PDCA Stage:` 已加；既有欄位順序未動。
- Next-Step Decision: continue
```

### 4.2 範例 B：risk = 2 之 verifier dispatch（可省，但採用以提升追溯性）

```md
## TAO Trace

### Step 1
- Thought Log: 讀 verify obligation，判定須對 plan §Validation Strategy 第 1 條（人工讀文）做形式驗證。假設 PDCA 標籤完整即達標。
- Action Step: 跑 `grep -c "^> PDCA Stage:" docs/artifact_schema.md`。
- Observation: 輸出 `9`，符合預期（§5.1-5.9 共 9 節）。
- Next-Step Decision: continue
```

## 5. TAO Trace 之 artifact 落點

- **Code artifact (§5.4)**：implementer / tester dispatch 之 TAO Trace 寫於 `## TAO Trace` 區塊，位於 `## Known Risks` 之後、`## Blockers` 之前。
- **Verify artifact (§5.6)**：verifier / reviewer dispatch 之 TAO Trace 寫於 `## TAO Trace` 區塊，位於 `## Build Guarantee` 之後。
- **多 step dispatch**：一次 dispatch 之多個 step 串於同一 `## TAO Trace` 內，依 Step 編號排列。
- **多 dispatch 任務**：若一個 task 之 code artifact 對應多次 implementer dispatch（如 Phase 1 / Phase 2 分次執行），每次 dispatch 須 append 為新 `### Dispatch N — <短描述>` sub-block，內含其 Step 1-M。

## 6. 與 PDCA 之互動

執行層 TAO 內含於管理層 PDCA 之 D（Coding）階段。具體互動：

1. **D 階段啟動**：Claude 派 subagent，提供 plan + research artifact 為 input。
2. **TAO 微循環跑動**：subagent 在內部執行 1-N 個 TAO step，每 step 寫入 TAO Trace。
3. **D 階段結束**：subagent 產出 code artifact（含 TAO Trace），D 階段之 PDCA 落筆。
4. **Mismatch escalate**：若任一 TAO step 之 `Next-Step Decision: escalate`，D 階段提前結束，進入 mini-PDCA：標 task blocked → 寫 improvement artifact → re-plan → 重新 D 階段。

此設計確保 TAO 之微觀失敗不會繞過管理層之 PDCA gate。

## 7. Validator 規則（`--check-tao`，已實作，warning-only）

[guard_status_validator.py](../artifacts/scripts/guard_status_validator.py) 之 `--check-tao` 旗標（函式 `check_tao_trace`）：

- 啟用條件：task 於 [artifacts/registry/risk_classification.csv](../artifacts/registry/risk_classification.csv) 之 `risk_level` 欄為 `high-risk`（該 registry 以 `max_severity` 記錄各 task 風險，`blocking` 對應 `high-risk`，與 §1「`Severity: blocking` 即 risk ≥ 3」之模型一致）。csv 缺、或 task 未登錄，則發 warning 並略過該 task。
- 檢查：對應 code / verify artifact 須含 `## TAO Trace` 區塊。
- 失敗等級：warning-only（`--check-tao` 恆 exit 0，不 hard fail，避免阻塞既有 artifact）。
- 已知限制（follow-up 候選）：(a) 目前僅檢查 `## TAO Trace` 區塊是否存在，尚未強制 §2 之 `### Step N` step-level 結構；(b) 既有 high-risk artifact 之 TAO 回填仍待後續 backlog 處理。

## 8. 禁止事項

- 不得以「思考過程」「執行紀錄」等模糊欄位替代四欄 schema。
- 不得在 `Thought Log` 內附 chain-of-thought 之長段推理（>5 句）；若需詳述，獨立成 step 或寫入 decision artifact。
- 不得偽造 `Observation`（如未實跑命令而宣稱 stdout）。
- 不得將 `Next-Step Decision: escalate` 用於 subagent 自行決定 routing override；只能 `halt`，由 Claude 升級為 decision。

## 9. 與其他文件之交叉引用

- 兩層架構總覽：[docs/orchestration.md §2.8](orchestration.md)
- code artifact schema：[docs/schemas/artifact-spec-code.md §5.4](artifact_schema.md)
- verify artifact schema：[docs/schemas/artifact-spec-verify.md §5.6](artifact_schema.md)
- subagent 角色：[docs/subagent_roles.md](subagent_roles.md)
- subagent dispatch templates：[docs/subagent_task_templates.md](subagent_task_templates.md)
- premortem 與 mini-PDCA 觸發：[docs/premortem_rules.md](premortem_rules.md)
