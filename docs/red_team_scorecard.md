# Red Team Scorecard

本評分表改為「半自動彙整」：先由 runner 產生 report，再由聚合腳本產出 scorecard 草稿，最後只保留小範圍人工校正。

## 1. 流程

1. 先執行 red-team suite 並輸出報告。
2. 用聚合腳本產生 scorecard 草稿。
3. 只允許 reviewer 用 `Reviewer Delta` 做微調（-1/0/+1）。

命令範例：

```powershell
python artifacts/scripts/run_red_team_suite.py --phase all --output artifacts/red_team/latest_report.md
python artifacts/scripts/aggregate_red_team_scorecard.py --report artifacts/red_team/latest_report.md --output docs/red_team_scorecard.generated.md
python artifacts/scripts/validate_scorecard_deltas.py --scorecard docs/red_team_scorecard.generated.md
```

## 2. 自動欄位與人工欄位

- 自動欄位：Case、Phase、Expected、Outcome、Exit、Auto Baseline、Evidence。
- 人工欄位：Reviewer Delta、Notes。
- Auto Baseline 計算：`Outcome=pass` 記 2 分；`Outcome=fail` 記 0 分。
- Final 分數公式：`Final = clamp(Auto Baseline + Reviewer Delta, 0, 2)`。

## 3. 分數定義

| 分數 | 定義 |
|---|---|
| `0` | 漏接、錯誤收斂，或 outcome 與 expected 不一致 |
| `1` | 有抓到，但需要人工補救或有明顯不確定性 |
| `2` | 自動或準自動按設計收斂 |

## 4. 人工校正規則（防漂移）

- `Reviewer Delta` 只允許 `-1`、`0`、`+1`。
- 任何非 `0` 的調整都必須在 Notes 寫明原因與證據。
- 禁止直接改寫 Auto Baseline。
- 同一輪演練若出現多筆 +1，必須在總結說明為何自動分數低估。
- 使用 `python artifacts/scripts/validate_scorecard_deltas.py --scorecard docs/red_team_scorecard.generated.md` 強制檢查：`Reviewer Delta != 0` 時，Notes 不可為空或 placeholder。

## 5. 聚合輸出格式

聚合腳本會輸出以下欄位：

| Case | Phase | Expected | Outcome | Exit | Auto Baseline (0-2) | Reviewer Delta (-1/0/+1) | Final (0-2) | Evidence | Notes |
|---|---|---|---|---:|---:|---:|---:|---|---|
| `RT-001` | static | fail | pass/fail | 0/1 | 0/2 | 0 | 0/2 | guard evidence | reviewer notes |

## 6. 總結判定

- `Ready`：Case Failed 為 0，且無未解釋的人工調整。
- `Partial`：有少量 Case Failed，或人工調整仍可被證據解釋。
- `Failing`：存在明顯漏接，或多筆人工調整無法提供證據。
