# Artifact Spec: status

> 本檔由 `docs/artifact_schema.md` §5.8 拆分而來；schema literal、欄位定義、字串契約皆與原檔逐字對齊。

## 5.8 Status Artifact Schema

> PDCA Stage: meta（meta-state，承載各階段機器可讀狀態，不屬任一單一階段）

檔名：`artifacts/status/TASK-001.status.json`

用途：提供機器可讀狀態，作為流程主控依據。

JSON schema 範例：

```json
{
  "task_id": "TASK-001",
  "state": "planned",
  "current_owner": "Claude",
  "next_agent": "Codex",
  "required_artifacts": ["task", "research", "plan"],
  "available_artifacts": ["task", "research", "plan"],
  "missing_artifacts": [],
  "assurance_level": "mvp",
  "project_adapter": "generic",
  "open_verification_debts": [],
  "blocked_reason": "",
  "last_updated": "2026-04-09T14:30:00+08:00"
}
```

### state 合法值

- `drafted`
- `researched`
- `planned`
- `coding`
- `testing`
- `verifying`
- `done`
- `blocked`

### 欄位規則

- `task_id`: 必須對應既有 task artifact。
- `state`: 必須符合 workflow state machine。
- `required_artifacts`: 此狀態進入下一步所需類型。
- `missing_artifacts`: 實際缺件清單。
- `assurance_level`: `poc`、`mvp`、`production` 之一。status guard 依此決定最低 required artifacts。
- `project_adapter`: `generic`、`web-app`、`backend-service`、`batch-etl`、`cli-tool`、`docs-spec`、`resource-constrained-ui` 之一。
- `open_verification_debts`: 尚未結清的 verify obligations；沒有時填 `[]`。
- `blocked_reason`: 若 state 為 `blocked`，不可空白。
- `Gate_E_passed` (新增)：Gate E 驗證是否通過。只有 state 為 `done` 且曾經歷 blocked 時才填寫。值為 `true` 或 `false`。
- `Gate_E_evidence` (新增)：proof of Gate E；當 `Gate_E_passed: true` 時必填。格式為 array of paths / artifact IDs（例如 `["artifacts/decisions/TASK-001.decision.md", "artifacts/improvement/TASK-001.improvement.md"]`）。
- `Gate_E_timestamp` (新增)：Gate E 驗證通過時間戳，採 ISO 8601+08:00 格式。當 `Gate_E_passed: true` 時必填。

### 完整範例（包含 Gate E）

```json
{
  "task_id": "TASK-001",
  "state": "done",
  "current_owner": "Claude",
  "next_agent": "Claude",
  "required_artifacts": ["code", "research", "status", "task", "verify"],
  "available_artifacts": ["code", "decision", "improvement", "plan", "research", "status", "task", "verify"],
  "missing_artifacts": [],
  "blocked_reason": "",
  "last_updated": "2026-04-11T11:10:00+08:00",
  "Gate_E_passed": true,
  "Gate_E_evidence": ["artifacts/decisions/TASK-001.decision.md", "artifacts/improvement/TASK-001.improvement.md"],
  "Gate_E_timestamp": "2026-04-11T11:10:00+08:00"
}
```

---
