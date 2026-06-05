# Red Team Backlog

本文件記錄紅隊演練後應追蹤的缺口。每一項都必須能對應到具體規則、guard、文件或樣本。

## BKL-001 歷史 diff 重建仍未完全自動化

- 目前狀態：`guard_status_validator.py` 現在除了 dirty worktree 的 git-backed changed-files 比對外，也支援以 pinned `Base Commit` / `Head Commit`、`Changed Files Snapshot` 與 `Snapshot SHA256` 重放 clean task 的 `commit-range` historical diff；若 local git replay 失敗且附有合法 `Archive Path` / `Archive SHA256`，也可改走 archive fallback；若 task 記錄 `Evidence Type: github-pr`，則可透過 GitHub PR files API 重建 changed files。
- 殘餘風險：若 task 沒有記錄 diff evidence、沒有準備 archive file、需要 GitHub 以外的 provider、遭遇 provider auth / rate-limit 問題、或 PR files 超過 GitHub endpoint 上限，guard 仍可能無法自動重建歷史 changed files；目前 ref drift 也只會告警，不會直接阻斷。
- 建議補強：下一輪可加入其他 provider（GitLab / Azure / Bitbucket）、provider response 的長期封存策略、或把特定 ref drift / provider precondition 提升為 policy-driven hard fail。

## BKL-002 Contract guard 的 exact-sync 清單需人工維護

- 目前狀態：`guard_contract_validator.py` 以明確檔案清單驗證 root / template 同步。
- 風險：新增 workflow 文件或腳本時，若忘記把檔案加進 exact-sync 清單，就可能產生未受監控的漂移。
- 建議補強：增加 workflow docs registry，或將 `docs/` 內特定命名慣例自動納入 sync 驗證。

## BKL-003 Red-team runner 目前聚焦 repo 內建案例

- 目前狀態：`run_red_team_suite.py` 主要驗證 research contract、premortem、Gate E 與 contract drift。
- 風險：外部工具憑證失效、上游 repo 變動、或第三方 CLI 行為異常等情境仍需額外 drill。
- 建議補強：第二輪加入 environment-precondition drills 與 external dependency drills。

## BKL-004 Scorecard 的最終分數仍需人工判讀

- 目前狀態：runner 可驗證案例是否符合預期，但五個維度的成熟度分數仍需主持人與記錄者填寫。
- 風險：不同演練輪次之間，評分標準可能漂移。
- 建議補強：建立固定評語範本與「0 / 1 / 2」範例，降低主觀差異。
