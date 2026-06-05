# PREMORTEM RULES

本文件定義在進入 Implementation（coding）之前，必須執行的事前驗屍（premortem）檢查，以及對 premortem 內容品質的 guard 規則。

目標：
1. 在動手之前，預測最可能失敗的原因，並將風險顯性化，而不是事後補救。
2. 確保 plan artifact 中的風險分析不是形式填空，而是可行動、可檢查、可作為 gate 的輸入。

## 1. 何時必須執行 premortem

以下情況必須執行：

- 進入 coding state 前（planned → coding）
- 任務涉及外部依賴（NuGet / API / upstream）
- 任務涉及安全性修補（security fix）
- 任務涉及 upstream PR
- 任務涉及多模組或跨 repo 修改
- 任務涉及不熟悉框架、版本或環境
- 無法 100% 確認變更影響範圍

若符合上述任一條件，plan artifact 的 `## Risks` 區段不得為空，且必須通過本文件的 guard 規則。

## 2. 輸出位置

Premortem 必須寫入：

- plan artifact 的 `## Risks` 區段
或
- decision artifact（若風險影響重大）

## 3. 必填內容（最小集合）

每一條風險必須至少包含以下五個欄位：

- **Risk**: 最可能失敗原因（不是理想情況，是最糟情況）
- **Trigger**: 什麼情況會觸發
- **Detection**: 如何知道它已發生
- **Mitigation**: 發生後如何止血或降低影響（不是預防，是止血）
- **Severity**: `blocking` 或 `non-blocking`

建議格式：

```
R1
- Risk: <具體失敗原因>
- Trigger: <可觀察觸發條件>
- Detection: <可驗證偵測方式>
- Mitigation: <可執行緩解動作>
- Severity: blocking | non-blocking
```

## 4. 品質規則（Guard Rules）

### P1. 必須具名
每條風險必須有唯一編號（R1, R2, R3...）。沒有編號者視為不合法。

### P2. 不可只有抽象名詞
以下內容單獨出現時視為不合格：

- 相容性風險
- 效能問題
- 有可能失敗
- 注意版本
- 需再確認
- 風險低
- 應該沒問題

若使用上述詞彙，必須補上具體 trigger、detection、mitigation。

### P3. Trigger 必須可觀察
Trigger 必須描述一個可辨識事件，不可只寫：

- 升級時
- 執行時
- 某些情況下
- 可能會

可接受例子：

- 當 upstream 使用 MailKit 與 MimeKit lockstep 版本時
- 當 `dotnet restore` 解析出版本衝突時
- 當 UWP head 在 build 時載入不相容 API 時

### P4. Detection 必須可驗證
Detection 必須指出可觀察證據來源，例如：

- build error
- test failure
- runtime exception
- `dotnet list package --vulnerable`
- CI log
- PR review feedback

只寫「觀察結果」或「再看看」視為不合格。

### P5. Mitigation 必須可執行
Mitigation 必須是具體動作，不可只寫：

- 注意處理
- 視情況調整
- 再討論
- 必要時修正

可接受例子：

- 回退到前一版本並同步更新 plan artifact
- 將任務標記 blocked，先補 research artifact
- 改為 upstream clean branch 重做最小 PR
- 將 MailKit 與 MimeKit 一起升級

### P6. Severity 必須明確
每條風險必須標記 `blocking` 或 `non-blocking`。不得使用 medium / maybe / TBD / 視情況。

### P7. 至少一條 blocking risk
若任務屬於 security、dependency upgrade、upstream PR、跨 repo 變更，則 premortem 中至少要有一條 blocking risk。若沒有，視為過度樂觀，guard 失敗。

### P8. 不可用結論代替 premortem
以下內容視為無效：

- 已驗證通過
- 看起來沒有問題
- 預期可接受
- 應該不會影響

premortem 是預測失敗，不是宣告成功。

## 5. 違規等級

### Level 1: Warning
適用：有風險條目但缺少 1 個欄位；用語略模糊但仍可推測意圖。
處置：不允許進入 coding，要求補寫 plan artifact 的 `## Risks`。

### Level 2: Blocked
適用：風險條目缺少 Trigger / Detection / Mitigation；全部風險都無 Severity；高風險任務卻沒有 blocking risk；風險內容完全抽象。
處置：task state = blocked，blocked_reason = "Premortem quality check failed"，回到 planning。

### Level 3: Fail
適用：明知高風險仍跳過 premortem gate 進入 coding；以假造或未驗證內容填寫；將成功結論偽裝成風險分析。
處置：立即停止流程，必須建立 decision artifact，人工審核後才能重新推進。

## 6. 最低數量要求

最低數量要求由 `Adaptive Classification` 決定：validator 會依 task title 自動套用 `min_risks` 與 `min_critical`。實際對照表見 §7。

## 7. Adaptive Classification

`guard_status_validator.py` 會讀取 task artifact 第一行標題（`# Task: ...`），依下表的 `keyword_regex` 判定 premortem task type，並動態調整最低門檻：

| task_type | keyword_regex | min_risks | min_critical |
|---|---|---|---|
| hotfix | `\bhotfix\b|\bpatch\b` | 1 | 0 |
| research | `\bresearch\b|\banalysis\b` | 2 | 1 |
| planning | `\bplan\b|\bdesign\b` | 3 | 1 |
| code | `(default)` | 3 | 1 |

規則補充：

- 比對目標只看 task title，不看 plan title。
- 若沒有任何 regex 命中，預設使用 `code`。
- `min_critical` 對應至少幾條 `Severity: blocking` 風險。
- `override` 不得跳過 premortem missing；`## Risks` 缺失或空白仍視為 fail。

## 8. 範例

R1
- Risk: MailKit 與 MimeKit 版本不同步，導致 restore 或 runtime 相依衝突
- Trigger: upstream `Directory.Packages.props` 仍要求 lockstep family version
- Detection: `dotnet restore` 失敗或應用解析 MIME 時拋出相依錯誤
- Mitigation: 改為 MailKit 與 MimeKit 同步升級，並更新 research / plan artifact
- Severity: blocking

R2
- Risk: upstream 維護者偏好 Dependabot 或不接受手動 dependency bump PR
- Trigger: repo 有既有 PR policy、bot workflow 或 review comment 要求不同提交流程
- Detection: CONTRIBUTING.md、PR template、maintainer review comment
- Mitigation: 保持 PR 極小化，PR body 明確附上 advisory、驗證證據與最小變更範圍
- Severity: non-blocking

## 9. 禁止語句清單

以下語句若未補具體內容，直接判定 guard 失敗：

- 風險低 / 應該沒問題 / 可能有風險 / 視情況而定
- 再觀察 / 注意一下 / 需評估 / 有待確認
- 相容性問題 / 效能問題

## 10. 與 workflow 的關係

- premortem 不合格 = 不可進入 coding
- premortem 缺失 = 不可進入 coding
- blocking risk 未處理 = 必須先 decision 或補 research
- risk 實際發生 = 回退到最近合法 state

## 11. 最終原則

Premortem 的目的不是讓人安心，而是讓錯誤提前發生在紙上，而不是發生在 production。

premortem 的價值不在於悲觀，而在於把失敗變成可命名、可偵測、可止血的對象。

如果一條風險不能讓下一位代理知道「怎麼發現、怎麼處理」，那它就不算合格。
