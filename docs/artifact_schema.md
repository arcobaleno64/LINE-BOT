# ARTIFACT_SCHEMA

本文件定義 artifact-first workflow 的檔案命名、欄位、狀態、驗證規則與最小品質要求。

目標有三個：

1. 讓不同代理可透過固定 schema 接手工作。
2. 讓狀態可追蹤、可驗證、可重跑。
3. 避免 artifact 退化成不可機讀、不可審計的自由散文。

## 1. 通用規則

### 1.0 Artifact 為邊界物件（Boundary Objects framing）

本框架之 artifact 同時為跨代理（Claude / Gemini / Codex / subagents）之**邊界物件（Boundary Object, Star & Griesemer 1989）**：不同代理對同一 artifact 之解讀容許局部差異（如 implementer 視 code artifact 為 deliverable、verifier 視為 input），但 artifact 之嚴格欄位定義（schema）即跨代理之共同語言契約，使各代理對「任務已完成」「驗收已通過」等概念之認知對齊。

實作上之意涵：

- artifact schema 之嚴格定義不可隨意鬆動；欄位刪減須走 decision artifact 變更管制。
- 每一新增之 artifact 類型須先設 schema，再建實例；不得倒序。
- 跨代理之語義不對稱（如 implementer 假設「測試通過」與 verifier 之「驗收通過」之差異）由 schema 之欄位顯式區隔（如 `## Build Guarantee` 與 `## Acceptance Criteria Checklist` 分離）。
- PROCESS_LEDGER 與 status.json 為跨 PDCA 階段之邊界物件，承載 closure 與 next-task 入口。

### 1.1 命名規範

所有 artifacts 必須使用一致命名：

`TASK-<流水號>.<artifact-type>.<ext>`

範例：

- `TASK-001.task.md`
- `TASK-001.research.md`
- `TASK-001.plan.md`
- `TASK-001.code.md`
- `TASK-001.test.md`
- `TASK-001.verify.md`
- `TASK-001.decision.md`
- `TASK-001.status.json`

### 1.2 目錄規範

建議目錄：

```text
/artifacts
  /tasks
  /research
  /plans
  /code
  /test
  /verify
  /decisions
  /improvement
  /registry
  /metrics
  /status
```

`artifacts/status/` 只保留 `TASK-*.status.json` 與必要的狀態輔助檔；跨 task 匯總輸出應放到 `artifacts/registry/` 或 `artifacts/metrics/`。

`artifacts/test/legacy_verify_corpus/` 保留給 external legacy verify import 的共享 regression fixtures；unit tests 與 red-team drills 應優先共用這份 corpus，而不是各自維護平行樣本。

### 1.3 任務識別碼

- 任務識別碼格式：`TASK-001`、`TASK-002`。
- 一個任務可有多個關聯 artifacts，但只能有一個主 status artifact。
- 同一任務的 artifacts 必須使用相同 task id。

### 1.4 時間格式

- 所有時間使用 ISO 8601。
- 所有 workflow / template / root 長期維護 artifacts 的時間戳必須使用 `Asia/Taipei`，並帶 `+08:00`。
- 不接受只有日期或缺少時區的 `Last Updated`。
- 範例：`2026-04-09T14:30:00+08:00`

### 1.5 文件語言與風格

- artifact 以清晰、可驗證、可接手為原則。
- 用語必須具體，避免模糊詞如「可能沒問題」「應該可行」。
- 若不確定，必須明確標示 `uncertain` 或對應欄位中的未確認事項。

## 2. Artifact 類型總表

| 類型 | 副檔名 | 主要作者 | 目的 |
|---|---|---|---|
| task | `.task.md` | Claude | 定義任務目標、限制、驗收條件 |
| research | `.research.md` | Gemini | 提供規格依據、查詢結果、實作約束 |
| plan | `.plan.md` | Claude | 定義實作範圍、影響面、風險 |
| code | `.code.md` | Codex | 記錄修改內容、變更檔案、已做測試 |
| test | `.test.md` | Codex subagent 或 Claude | 記錄測試結果與失敗摘要 |
| verify | `.verify.md` | Claude 或 verifier | 對照驗收條件判定 pass/fail |
| decision | `.decision.md` | Claude | 記錄衝突、決策理由、取捨 |
| status | `.status.json` | Claude | 提供機讀狀態與下一步 |
| improvement | `.improvement.md` | Claude | PDCA 改進記錄：失敗分析、矯正與預防措施，以及 verify / done 後的輕量流程復盤 |

## 3. 必填通用欄位

所有 markdown 型 artifact 必須至少包含以下通用區段：

- `Task ID`
- `Artifact Type`
- `Owner`
- `Status`
- `Last Updated`

建議固定寫法：

```md
## Metadata
- Task ID: TASK-001
- Artifact Type: task
- Owner: Claude
- Status: drafted
- Last Updated: 2026-04-09T14:30:00+08:00
```

若缺少上述欄位，該 artifact 視為不合法。

## 4. 狀態值規範

### 4.1 通用狀態值

不同 artifact 可使用以下狀態值的子集合：

- `drafted`
- `in_progress`
- `ready`
- `approved`
- `blocked`
- `pass`
- `fail`
- `done`
- `superseded`

### 4.2 狀態使用原則

- task: `drafted`, `approved`, `blocked`, `done`
- research: `in_progress`, `ready`, `blocked`, `superseded`
- plan: `drafted`, `ready`, `approved`, `blocked`, `superseded`
- code: `in_progress`, `ready`, `blocked`, `superseded`
- test: `in_progress`, `pass`, `fail`, `blocked`, `superseded`
- verify: `pass`, `fail`, `blocked`, `superseded`
- decision: `done`
- improvement: `draft`, `approved`, `applied`

## 5. Artifact 類型詳細欄位

各 artifact type 之詳細欄位、必填項、規則範例見 `docs/schemas/`：

- §5.1 Task — see [docs/schemas/artifact-spec-task.md](schemas/artifact-spec-task.md)
- §5.2 Research — see [docs/schemas/artifact-spec-research.md](schemas/artifact-spec-research.md)
- §5.3 Plan — see [docs/schemas/artifact-spec-plan.md](schemas/artifact-spec-plan.md)
- §5.4 Code — see [docs/schemas/artifact-spec-code.md](schemas/artifact-spec-code.md)
- §5.5 Test — see [docs/schemas/artifact-spec-test.md](schemas/artifact-spec-test.md)
- §5.6 Verify — see [docs/schemas/artifact-spec-verify.md](schemas/artifact-spec-verify.md)
- §5.7 Decision — see [docs/schemas/artifact-spec-decision.md](schemas/artifact-spec-decision.md)
- §5.8 Status — see [docs/schemas/artifact-spec-status.md](schemas/artifact-spec-status.md)
- §5.9 Improvement — see [docs/schemas/artifact-spec-improvement.md](schemas/artifact-spec-improvement.md)
- 範例與 gallery — see [docs/schemas/artifact-gallery.md](schemas/artifact-gallery.md)

§5.10–§5.13 為 schema clarifications（lineage MVP / assurance resolver / verify floor / v2 governance），保留於本檔內聯。

## 5.10 Artifact Lineage MVP

用途：定義 artifact 間最小可查的 lineage 關係，供 registry 與後續自動化擴充使用。

最小 schema：

```yaml
lineage_entry:
  source_file: "artifacts/code/{task}.code.md"
  plan_item: "N.N"
  decision_refs:
    - "artifacts/decisions/{task}.decision.md"
  research_refs:
    - "artifacts/research/{task}.research.md"
  scope: "file-level only"
  generated_by: "build_decision_registry.py"
```

規則：

- `source_file`: 指向單一 code artifact，使用 repo-relative path。
- `plan_item`: 對應 code artifact `## Mapping To Plan` 的 `N.N` 項目。
- `decision_refs`: 指向相關 decision artifacts，使用 repo-relative path array。
- `research_refs`: 指向相關 research artifacts，使用 repo-relative path array。
- `scope`: 目前只支援 file-level only，不含行號、不含 commit hash。
- `generated_by`: 目前由 `build_decision_registry.py` 作為最小生成入口；未來可擴充其他 producer，但不得改變 MVP 的 file-level 邊界。

---

## 5.11 Assurance Resolver Pipeline（TASK-1008 schema clarification）

> Authoritative since: 2026-04-29 (TASK-1008). Decision ref: artifacts/decisions/TASK-1008.decision.md

### 5.11.1 Allowed Assurance Levels

Exactly three values are valid:

| Level | Meaning |
|---|---|
| `poc` | Proof-of-concept; minimal artifact requirements |
| `mvp` | Minimum viable product; standard governance gates |
| `production` | Full governance; requires manual review, build guarantee, and reviewer attestation |

`high` is **not** a valid assurance level and must be rejected by validators.

### 5.11.2 Resolver Pipeline

The assurance resolution follows this pipeline:

```
assurance baseline (task.md ## Assurance Level)
  → adapter override (PROJECT_ADAPTER_RULES artifact_overrides_by_state)
  → resolved policy (resolve_verification_policy)
```

Validators MUST read the **resolved policy** returned by `resolve_verification_policy(assurance_level, project_adapter)`, not re-derive requirements from artifact heuristics.

### 5.11.3 Strict Mode (root default)

Root strict mode applies to all new and modified artifacts after TASK-1008 baseline:

- **Missing assurance_level**: error (not warning). No silent default.
- **Unknown assurance_level**: explicit schema error. `high` and any value outside `{poc, mvp, production}` are schema violations.
- **task.md and status.json mismatch**: error. Both must declare the same value.
- **Forbidden**: silently defaulting unknown values to `poc`.

Implemented in:
- `guard_status_validator.py` → `validate_status_schema`: missing or invalid → error
- `guard_status_validator.py` → `validate_markdown_artifact` (task type): missing section → error; invalid raw value → error; mismatch with status.json → error
- `workflow_constants.py` → `validate_assurance_level_strict(value)`: raises `ValueError` on unknown or empty

### 5.11.4 Legacy Compatibility Mode (explicit invocation only)

Legacy mode exists only for historical or downstream artifacts that predate strict enforcement:

- **Invocation**: must call `workflow_constants.warn_and_default_assurance_level(value)` explicitly.
- **Silent default is forbidden**: code must never call this implicitly as a fallback.
- **Warning structure** (returned dict when defaulting occurs):
  - `defaulted_from`: the original invalid value
  - `selected_default`: the level that was substituted (`poc`)
  - `migration_debt`: human-readable message describing the required correction
- If the value is already valid, returns `(value, {})` with empty warning dict.

### 5.11.5 TASK-964 Policy Clarification

The historical TASK-964 governance drill is permanently classified as:

- **maturity**: `mvp + limited evidence`
- **reason**: the drill was correct in conclusion but was produced under a lower evidence floor than production-grade attestation requires.

Repaired future evidence MUST NOT retroactively upgrade TASK-964's historical maturity. Production-grade canonical drill ownership belongs to TASK-1010 (Prompt 4) or the manifest-designated equivalent.

## 5.12 Verify Floor Baseline Schema（TASK-1009 schema clarification）

> Authoritative since: 2026-05-03 (TASK-1009). Decision ref: artifacts/decisions/TASK-1009.decision.md

### 5.12.1 Purpose

`artifacts/governance/verify-floor-baseline.v3.4.json` is an **immutable snapshot** of all verify artifacts that existed **before** the TASK-1009 baseline was created. It classifies each entry by floor policy and enables split enforcement: historical artifacts remain advisory, while new and modified artifacts are immediately strict.

**Baseline semantics (critical)**:

- `baseline_verify_files` covers only verify artifacts that existed at baseline creation time.
- Verify artifacts created or modified **after** the baseline snapshot are **not** included in `baseline_verify_files`.
- `artifacts/verify/TASK-1009.verify.md` is intentionally absent from the baseline because it was created as part of TASK-1009 itself — after the baseline snapshot. It is classified as `strict` by `classify_verify_floor_policy`.
- Adding a post-baseline artifact to `baseline_verify_files` would incorrectly downgrade it from `strict` to `advisory_until_6d` — this MUST NOT be done.
- The baseline entry count (32) and the current total artifact count (33+) will diverge as new verify artifacts are created. This divergence is correct and expected.

### 5.12.2 Top-Level Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | string | yes | Must be `"verify-floor-baseline/v1"` |
| `plan_version` | string | yes | Must be `"v3.4"` |
| `created_at` | string | yes | Taipei timestamp; MUST come from a deterministic source |
| `created_at_source` | string | yes | Identifies the deterministic source (e.g. `"git:<sha>"`) |
| `created_by` | string | yes | Task ID that created this baseline |
| `sha256_method` | string | yes | Describes how sha256 was computed |
| `baseline_task_count` | integer | yes | Count of entries in `baseline_verify_files` |
| `policy` | object | yes | Policy constants (see §5.12.3) |
| `baseline_verify_files` | array | yes | One entry per baseline verify artifact |

### 5.12.3 Policy Object

| Field | Type | Description |
|---|---|---|
| `historical_unchanged` | string | Value: `"advisory_until_6d"` — baseline files with matching sha256 are advisory |
| `new_or_modified_after_baseline` | string | Value: `"strict"` — absent or sha256-changed files are strict |
| `full_enforcement_task` | string | Task ID for full repo enforcement (TASK-1015) |
| `full_enforcement_prompt` | string | Prompt label for full enforcement (`"6d"`) |

### 5.12.4 Baseline Entry Fields

Each object in `baseline_verify_files`:

| Field | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | Posix-style relative path from repo root |
| `sha256` | string | yes | SHA256 hex digest of raw file bytes at baseline time |
| `floor_status` | string | yes | One of: `"advisory_until_6d"`, `"strict"` |
| `baseline_known_debt` | string | no | Present when baseline entry carries known debt (e.g. `"limited_evidence"`) |
| `baseline_known_debt_ref` | string | no | Reference to artifact section documenting the debt |
| `baseline_known_debt_note` | string | no | Human-readable explanation of the debt |

### 5.12.5 Classification Logic

Implemented in `guard_status_validator.py` → `classify_verify_floor_policy(verify_path, baseline)`:

1. Search `baseline_verify_files` for entry whose `path` matches the verify artifact's posix path.
2. If not found → `strict` (new artifact after baseline).
3. If found, compute `sha256` of current file bytes.
4. If sha256 matches → `advisory_until_6d` (historical unchanged).
5. If sha256 differs → `strict` (modified after baseline).

Dry-run support: `guard_status_validator.py --verify-floor-dry-run` classifies and prints the policy without failing. Full enforcement is deferred to Prompt 6d / TASK-1015.

### 5.12.6 TASK-964 Baseline-Known-Debt Pattern

TASK-964 is the canonical example of a `baseline_known_debt` entry:

- `floor_status` remains `"advisory_until_6d"` (it is a historical unchanged artifact).
- `baseline_known_debt = "limited_evidence"` records the known evidence debt for traceability.
- This annotation does NOT modify TASK-964.verify.md or upgrade its maturity.
- Production canonical drill for TASK-964 scope belongs to TASK-1010 (Prompt 4).

## 5.13 v2 Governance Extension（TASK-1045 schema clarification）

> Authoritative since: 2026-05-05 (TASK-1045). Decision ref: artifacts/decisions/TASK-1045.decision.md

### 5.13.1 動機

v3.5.x governance repair chain 自 TASK-1037 起，task / plan / decision / verify artifacts 漸演成 v2 格式：task 用 `## Title` / `## Description` / `## Non Goals` 取代 `## Objective` / `## Constraints` / `## Out of Scope`；decision 帶 YAML frontmatter `schema_version: decision/v2`，用 `# Decision:` headline 與 `## Context` / `## Decision` / `## Consequences` H2，採 `governance-*` Decision Class，commit-anchored Expiry；verify 用 `- [x] AC-N: criterion text` inline 形式並允許多段落 evidence。v1 schema（§5.1 / §5.6 / §5.7）為原始基準；v2 為附加擴充，互不取代。validator 兼容雙版，artifact 作者可繼續以 v1 為預設並按需採 v2。

### 5.13.2 v2 Task Allowed Alternatives

| v1 必填 | v2 任一可代 |
|---|---|
| `## Objective` | `## Description` |
| `## Constraints` | `## Non Goals`、`## Authorized Production Surface` |

`## Acceptance Criteria` 仍為硬必填，不可省。其餘 v1 欄位（Background / Inputs / Dependencies / Out of Scope / Assurance Level / Project Adapter / Current Status Summary）建議保留；v2 task 通常以 `## Description` 提供 background 等敘事。

### 5.13.3 v2 Decision Allowed Alternatives

| v1 必填 | v2 任一可代 |
|---|---|
| `# Decision Log:` | `# Decision:` |
| `## Issue` | `## Context` |
| `## Chosen Option` | `## Decision`（h2，非 frontmatter title） |
| `## Reasoning` | `## Consequences` |
| `## Linked Artifacts` | `## Evidence Refs`、`## Follow Up`（governance class only） |

YAML frontmatter `schema_version: decision/v2` 為選填。若帶 frontmatter，validator 會自 frontmatter 抽取 `decision_class` 作為 `## Decision Class` H2 缺失時之來源；v1 H2 若同時存在則 H2 優先。

### 5.13.4 v2 Decision Class Family

`Decision Class` 接受兩類：

- **canonical 5 v1 classes**：`scope-drift-waiver` / `risk-acceptance` / `defer` / `reject` / `conflict-resolution`
- **governance-* family**：任一 `governance-` 前綴 + 非空 subclass token（例：`governance-attestation`、`governance-snapshot`、`governance-waiver-runtime-implementation`）

僅前綴而 subclass 為空（如 `governance-`）視為非法。

對 governance-* class，validator 放寬以下檢查：

- **Affected Gate**：可為 `None` / `N/A` / `Gate_X` / 任一非空字串；不強制 `Gate_A..Gate_E` 模式。
- **Expiry**：可為 commit-anchored 或 plan-version-anchored prose（如 `Decision is anchored at HEAD <sha>`），不強制 ISO 8601。
- **Linked Artifacts**：可由 `## Evidence Refs` 或 `## Follow Up` 取代。

對 canonical 5 classes 則維持 v1 嚴格檢查：Affected Gate 須符 `Gate_A..Gate_E`、Expiry 須 ISO 8601 +08:00、Linked Artifacts 須存在。

### 5.13.5 v2 Plan Allowed Alternatives

| v1 必填 | v2 任一可代 |
|---|---|
| `## Scope` | `## Goal` |
| `## Proposed Changes` | `## Approach` |
| `## Validation Strategy` | `## Premortem`、`## Build Guarantee`、`## TAO Trace` |
| `## Ready For Coding`（yes/no 宣告） | 偵測為 v2 plan 時放免；implementation authorisation 由 decision artifact 承載 |
| `## Verification Obligations`（mvp/production 必填） | 偵測為 v2 plan 時放免；驗證義務由 plan 之 Acceptance Criteria + Premortem + Build Guarantee 承載 |

`## Files Likely Affected` 與 `## Risks` 仍為硬必填。

v2 plan 偵測規則（任一成立即視為 v2）：

- 含 `## Authorization Boundary` H2
- 含 `## TAO Trace` H2
- 含 `## Premortem` H2 而不含 `## Validation Strategy` H2

### 5.13.6 v2 Verify Multi-Paragraph Evidence Parsing

v2 verify artifact 之 `## Acceptance Criteria Checklist` 採 `- [ ] AC-N:` / `- [x] AC-N:` line-anchored item-start 邊界（亦可用其他 `- [x] ID:` 風格）。每 item 可橫跨多段落 evidence；validator 以 item-start regex 為邊界切塊，避免空行誤分。若 section 內無任一 AC-N 起始 marker，validator fallback 至 v1 之空行邊界 splitter，確保歷史 verify 不破。

### 5.13.7 v2 Inline-Light AC Items

v2 verify 允許將 criterion 直接寫於 item 起始行：

```md
- [x] AC-1: TASK-XYZ lifecycle artifacts schema 一致
  - result: verified, reviewer: arcobaleno, timestamp: 2026-05-05T12:00:00+08:00
```

此 inline-light 形式中，`method` / `evidence` 為選填；criterion 行本身即作為 evidence anchor。validator 對 inline-light item 僅檢 `criterion`、`result` 與其餘 reviewer / timestamp 欄位（如 assurance level 要求）。非 inline-light item（即用 `- criterion:` 顯式分行）仍維持完整欄位要求。

### 5.13.8 v2 Governance Attestation Code Substitution

v2 governance attestation tasks（典型為 snapshot / closure / decision-only lifecycles）可不產 `code` artifact，改以 `decision` artifact 承載實作授權與證據。`docs-spec` adapter 在 `testing` / `verifying` / `done` state 釋 `code` 必要性；其他 adapter 仍依各自 profile 要求 code。

### 5.13.9 對既有 artifact 之相容性

- v1 artifact 不需任何修改即繼續通過 validator。所有 markers / fields / sections 皆 backward-compatible。
- v2 artifact 一旦採 alternates 後，validator 即依 §5.13 規則寬放對應檢查；混用 v1+v2 markers 之 hybrid artifact 亦合法。
- 文件作者偏好仍以 v1 為新 task 之預設範本；governance-attestation chain 始採 v2。

### 5.13.10 後續演進

未來 schema v3+ 應以同一原則處理：附加 marker tuples、prefix-family taxonomy、條件嚴格檢查、parser fallback。每一條 alternate 必於本 §5.13 顯式登錄；不得隱式擴張。

---

## 6. 合法性檢查規則

artifact 合法需同時符合：

1. 命名正確
2. 放在正確目錄
3. 包含必填欄位
4. 使用合法狀態值
5. 與上游 artifacts 的 task id 一致
6. 內容與角色責任一致
7. 沒有以模糊語句取代可驗證結論

若不合法，應：

- 視為缺件
- 不可作為下一步輸入
- 於 status artifact 記錄缺失

## 7. 版本與覆寫規則

- 同一 task 同一類型 artifact 原則上維持單一最新版本。
- 若需保留舊版，可另存備份，但主流程只認最新合法版本。
- 被新版本取代的 artifact，狀態應標記為 `superseded`。

## 8. 最小可用原則

對極小型任務可採 lightweight mode，但最少仍需：

- task artifact
- code artifact
- status artifact

若任務涉及外部知識，仍不可跳過 research artifact。
若任務需要驗收，仍不可跳過 verify artifact。

## 9. 禁止事項

以下 artifact 一律視為品質不合格：

- 只有標題沒有實質內容
- 用大量原始 log 取代摘要
- 把推測當成 confirmed fact
- 未列出 acceptance criteria
- 未列出 files changed
- 未列出風險或直接省略風險欄位
- status 與實際 artifacts 不一致

## 10. 最終原則

Artifact 的目的不是存檔，而是作為下一個代理的可用契約。

若某份 artifact 不能讓下一位代理不靠猜測就接手，那它就還不夠好。

