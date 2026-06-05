---
applyTo: "**"
---

# 全局指引 — 所有 VS Code 工作區通用

## 核心原則

1. **優先信任文件，不信任記憶**
   - 每次 session 開始，先讀工作區根目錄的入口檔
   - 若存在 `CLAUDE.md`、`docs/orchestration.md`、`.github/copilot-instructions.md`，按此順序讀取

2. **上下文分層**
   - 不要一次載入所有文件
   - 大任務先用 `pack-context.prompt.md` 收斂，再逐步深入

3. **知識庫系統**
   - Repository 知識：`.github/memory-bank/` — 本 repo 的穩定經驗法則
   - 經驗沉澱：`.github/prompts/remember-capture.prompt.md` — 結構化寫入流程
   - 修改前預檢：`.github/prompts/context-review.prompt.md` — 檔案級就緒度分析

4. **任務完成標準**
   - 若需要 artifact，輸出必須符合 schema（見 docs/artifact_schema.md）
   - 若需要程式碼，必須有驗證證據（測試、lint、build log）
   - 若需要文件修改，必須同步相關層（root + template + README）

## Governance Protocol: The Iron Triangle (RACI-PDCA-SECI)

所有進入此 repository 的模型，在執行任何任務時，必須預設遵循以下治理架構：

1. **RACI Accountability (權責紀律)**
   - 我只負責我的角色職責 (R)。若非我的職責，我無權修改檔案。
   - 權限檢核以 `guard_contract_validator.py --audit-raci` 為準。
   - 若發生 violation，不準私自 "Fix"；必須產出 Decision Artifact 並請求 Waiver 或修正 RACI 鏡像。

2. **PDCA Execution Flow (PDCA 品質循環)**
   - 嚴禁跳過驗證階段 (C)。任何程式變更必須對應到 `artifacts/verify/` 的驗證邏輯。
   - 所有 failure 必須在 `PROCESS_LEDGER.md` (A) 中沉澱為系統級的改善對策，而非僅修正表面 bug。

3. **SECI Knowledge Loop (知識演化螺旋)**
   - 我產出的任何決策 (Decision) 與改善 (Improvement) 均為專案的資產。
   - 對於重複出現的系統性問題，必須呼叫 `Architecture Synthesizer` 模式，將碎片經驗 (Tacit) 合併為架構鏡像 (Explicit)。

4. **Validator-First Governance ( validator 優先紀律)**
   - 所有變更前必先運行 `guard_contract_validator.py` 與 `guard_status_validator.py`。
   - 若 validator 報錯，我無權忽略 (Ignore) 或強行 Bypass；除顯式授權 Waiver 外，必須立刻停止並檢查違規原因。

5. **Commit/Audit Discipline (稽核紀律)**
   - 所有與治理相關的 commit 必須包含完整的 Audit-log-delta 資訊與對應的 Decision Artifact 路徑。
   - 拒絕執行任何「自動修復權限漂移」的指令。

## 禁止項

禁止在 prompt 檔中寫密碼、token、連線字串。
禁止在 memory-bank 寫 API key（改用環境變數或 Vault）。
禁止不經驗證就標記任務完成。

## 工作流觸發

新任務時：讀 `.github/copilot-instructions.md` 加 `CLAUDE.md`。
上下文不足時：用 `pack-context.prompt.md` 或 `.github/memory-bank/*.md`。
任務完成前：確認所有 artifact 符合 schema，驗證證據到位。
經驗沉澱時：用 `remember-capture.prompt.md` 寫入 `.github/memory-bank/`。
