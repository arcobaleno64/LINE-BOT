# Artifact Spec: code

> 本檔由 `docs/artifact_schema.md` §5.4 拆分而來；schema literal、欄位定義、字串契約皆與原檔逐字對齊。

## 5.4 Code Artifact Schema

> PDCA Stage: D (Do，實作執行)

檔名：`artifacts/code/TASK-001.code.md`

用途：記錄實作結果，避免主 thread 被 diff 與 log 淹沒。

必填區段：

```md
# Code Result: TASK-001

## Metadata
- Task ID:
- Artifact Type: code
- Owner:
- Status:
- Last Updated:

## Files Changed

## Execution Profile

## Subagent Plan

## Summary Of Changes

## Mapping To Plan

## Tests Added Or Updated

## Known Risks

## TAO Trace

## Blockers
```

可選區段（若需支援 historical diff reconstruction）：

```md
## Diff Evidence
- Evidence Type: commit-range
- Base Ref:
- Head Ref:
- Base Commit:
- Head Commit:
- Diff Command:
- Changed Files Snapshot:
- Snapshot SHA256:
- Archive Path:
- Archive SHA256:

## Diff Evidence
- Evidence Type: github-pr
- Repository:
- PR Number:
- API Base URL:
- Changed Files Snapshot:
- Snapshot SHA256:
```

欄位規則：

- `Files Changed`: 至少列出實際修改檔案，沒有修改時不可建立 code artifact。若 task 專屬 artifact 仍位於 dirty git worktree 中，`guard_status_validator.py` 會用實際 git changed files 自動驗證這個欄位；若為 clean task 且存在合法 diff evidence，也會在 historical replay 中驗證這個欄位。
- `Execution Profile`: 記錄實際使用的 Codex task scale、model policy、model 與 reasoning effort；若由 Claude 直接實作，必須記錄 routing override reason。
- `Subagent Plan`: 記錄 Codex 是否使用 subagent；未使用時寫 `None` 並說明理由，使用時列出各 subagent 的責任、write scope 與驗證分工。
- `Mapping To Plan`: 每行格式必須為 `- plan_item: {N.N}, status: done|partial|skipped, evidence: "{short description}"`。
- `Mapping To Plan`: 每個 plan item 都必須有對應一行；若無計畫對應則必須寫 `status: skipped, evidence: "not required by plan"`。
- `Tests Added Or Updated`: 沒有時寫 `None`。
- `Known Risks`: 沒有時寫 `None`。
- `TAO Trace`: risk ≥ 3（plan `## Risks` 任一條 `Severity: blocking`）之 implementer / verifier dispatch **必填**；risk ≤ 2 或 lightweight / docs-only 任務可寫 `None`。schema 與必填欄位見 [docs/agentic_execution_layer.md §2](agentic_execution_layer.md)。回填既有 artifact 時須以 `Reconstructed from artifact history` 開頭，不偽造當時即時思考。
- `Blockers`: 沒有時寫 `None`。
- `Diff Evidence`: 沒有時可省略或寫 `None`。目前 `guard_status_validator.py` 支援 `Evidence Type: commit-range` 與 `Evidence Type: github-pr`。
- `commit-range`: 要求 immutable commit pinning：`Base Commit` 與 `Head Commit` 必須是完整 40 字元 git commit SHA；`Base Ref` 與 `Head Ref` 是可選便利欄位，只用於偵測 ref drift。`Diff Command` 應對應實際 replay 命令。若擔心長期 git objects retention 不足，可額外提供 `Archive Path` 與 `Archive SHA256`；兩者必須一起出現，`Archive Path` 必須是 repo-relative、UTF-8、每行一個 normalized relative path、排序後、LF 換行的 text file，`Archive SHA256` 則是該 archive file 原始 bytes 的 SHA-256。guard 只會在 local git replay 失敗時改用 archive fallback，且 archive 內容仍必須與 `Changed Files Snapshot` 完全一致。
- `github-pr`: `Repository` 必須是 `owner/repo`，`PR Number` 必須是正整數；`API Base URL` 可省略，省略時預設 `https://api.github.com`，若使用 GitHub Enterprise Server 或本地 fixture，可覆寫成其他 http(s) endpoint。guard 會透過 GitHub PR files API 逐頁抓取 changed files，public repo 可不帶 token；private repo 或 rate-limited 環境則應提供 `GITHUB_TOKEN` 或 `GH_TOKEN`。
- `Changed Files Snapshot`: 必須列出 replayed diff 或 provider response 的完整檔案清單（以逗號分隔）。
- `Snapshot SHA256`: 必須是 `Changed Files Snapshot` 排序後以換行串接所得內容的 SHA-256。

最低驗收標準：

- 不能只寫「已完成修改」。
- 必須能看出改了哪裡、為何而改。
- 若超出 plan，必須明確標示並阻止 closure；在 task 專屬 dirty worktree 中，status guard 會直接用 git changed files 攔截未宣告 drift；在 clean task 且存在合法 diff evidence 時，status guard 會先驗證 `Changed Files Snapshot` 與 `Snapshot SHA256`，再用 pinned `commit-range`、archive fallback 或 `github-pr` provider response 重建 changed files 後攔截未宣告 drift。`--allow-scope-drift` 只可降級真正的 scope drift，不能覆蓋 diff evidence 損毀、archive 損毀或 provider evidence 錯誤。

---
