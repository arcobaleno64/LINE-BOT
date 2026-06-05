# Process Ledger

本檔是冷啟動入口，用來快速回顧最近幾次流程實際做了什麼、哪裡浪費、哪裡容易出錯。

建議閱讀順序：

1. 先看這份 ledger。
2. 再看最近 3 份 `TASK-XXX.improvement.md`。
3. 需要細節時，再回跳對應的 `verify` / `decision` / `status` artifact。

維護規則：

- 每個 task 只寫一行。
- 不貼 raw log，只寫結論與短證據方向。
- `Applied?` 表示對應修正是否已落地為文件、prompt、guard 或 template 變更。

| Date | Task | Outcome | Top Waste | Top Risk | Fix Candidate | Applied? |
|---|---|---|---|---|---|---|
| YYYY-MM-DD | [TASK-XXX](TASK-XXX.improvement.md) | 簡述這次流程最後收斂到什麼結果 | 這次最浪費的一步 | 最可能重犯的錯誤或誤判 | 應改 template / prompt / guard / 操作說明 何者 | no |
