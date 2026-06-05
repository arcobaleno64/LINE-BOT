# Artifact Spec: research

> 本檔由 `docs/artifact_schema.md` §5.2 拆分而來；schema literal、欄位定義、字串契約皆與原檔逐字對齊。

## 5.2 Research Artifact Schema

> PDCA Stage: P (Plan，規劃前之事實準備)

檔名：`artifacts/research/TASK-001.research.md`

用途：將外部知識、規格、版本差異與實作約束落地。

必填區段：

```md
# Research: TASK-001

## Metadata
- Task ID:
- Artifact Type: research
- Owner:
- Status:
- Last Updated:

## Research Questions

## Confirmed Facts

## Relevant References

## Sources

## Uncertain Items

## Constraints For Implementation
```

可選區段（research/cache draft 專用）：

```md
## Source Cache

## Tavily Cache
```

欄位規則：

- `Research Questions`: 至少一條。
- `Confirmed Facts`: 必須是可採用於規劃或實作的事實。
- `Relevant References`: 需標明來源名稱或文件名稱。
- `Sources`: 每行格式必須為 `[N] Author/Org. "Title." URL (YYYY-MM-DD retrieved)`。
- `Sources`: 至少 2 筆。
- `Source Cache`: 選填。保存 research 過程中可重用但尚未沉澱到 memory-bank 的來源摘錄；不得取代 `## Sources`。
- `Tavily Cache`: 選填。僅在 Gemini 被明確允許使用本機 Tavily CLI 時使用；每筆必須記錄實際 command、query、retrieved date、URLs 與結果摘要。
- `Sources` failure_grade:
  - `CRITICAL`: 缺少 `## Sources` 區段，或 0 筆來源。
  - `MAJOR`: 格式違規（例如缺少 URL、整體格式不符）。
  - `MINOR`: 日期缺失或只提供 partial date。
- `Uncertain Items`: 沒有時要寫 `None`。
- `Constraints For Implementation`: 要可直接被 plan 使用。
- research artifact 是 fact-only 契約，不得包含 `Recommendation`、implementation approach、PR title/body，或任何 solution 設計建議。

最低驗收標準：

- 不可只有連結或文件名，必須有整理後結論。
- 不可把推測寫進 `Confirmed Facts`。
- `Confirmed Facts` 的每一條 claim 都必須在同一條目內附上 inline citation（URL、`gh api` 指令或 artifact / doc path）。合法 inline citation 形態：(a) backtick-wrapped path 例如 `` `docs/X.md:42` ``；(b) 中文括號 wrap 例如 `（source: docs/X.md）`；(c) ASCII 括號 wrap 例如 `(see artifacts/scripts/Y.py)`；(d) 裸 `path:line` 例如 `per artifacts/scripts/Y.py:100`；(e) URL 例如 `https://...`；(f) `gh api repos/...` 指令。`Sources` 段亦可採 repo path 替代 URL，例如 `[3] council-forge. "research spec." docs/schemas/artifact-spec-research.md (2026-05-08 retrieved)`。
- `Uncertain Items` 若非 `None`，每條都必須以 `UNVERIFIED:` 開頭並說明原因。
- Tavily CLI 不可用、來源擷取失敗或日期不明時，不得用未驗證內容補洞；必須寫入 `Uncertain Items`，例如 `UNVERIFIED: Tavily CLI unavailable`。
- `Source Cache` / `Tavily Cache` 只是 research artifact draft cache；Claude/Codex 篩選後才可透過 Remember Capture 流程進入 `.github/memory-bank/`。
- 至少要有一個可供 implementation 使用的約束。

---
