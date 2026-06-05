## Summary

<!-- 1-3 句說明此 PR 之動機與成效；對應 task §Objective -->

## Linked Task

<!-- 對應 council-forge artifact-first lifecycle；缺則此 PR 屬 lightweight 路徑且須於下方說明 -->

- Task: TASK-XXXX
- Plan: artifacts/plans/TASK-XXXX.plan.md
- Verify: artifacts/verify/TASK-XXXX.verify.md

## Conventional Commits Type

<!-- 勾選一項；commit message 應與此一致 -->

- [ ] `feat`：新功能
- [ ] `fix`：缺陷修復
- [ ] `docs`：文件變更
- [ ] `refactor`：結構重組（無行為變更）
- [ ] `test`：測試新增 / 修補
- [ ] `chore`：建置 / CI / 工具
- [ ] `perf`：效能調整
- [ ] `breaking`：含 breaking change（請於下方 Risk 段重述）

## Files Changed

<!-- ⊆ plan §Files Likely Affected；逐行附一句用途；source template repo 須注意 root↔template 鏡像 -->

## Verification Evidence

- [ ] `python artifacts/scripts/guard_status_validator.py --task-id TASK-XXXX` 回 `[OK]`
- [ ] `python artifacts/scripts/guard_contract_validator.py` 與 `--check-readme` 兩條皆 `[OK]`
- [ ] `python artifacts/scripts/prompt_regression_validator.py --root .` 全部 PR-* 通過
- [ ] CI Workflow Guards 綠燈（push 後 `gh run list --limit 3` 確認）
- [ ] 對應 verify artifact 之 Build Guarantee 段已附 commit hash 與 evidence

## Risk

<!-- plan §Risks 之最高 severity 條目摘要；blocking risk 必列；本 PR 是否含 breaking change -->

---

> 與 council-forge 既有 artifact spec 之關係：本範本為 GitHub UI surface，內容引用既有 task / plan / code / verify artifact。完整變更紀錄以對應 artifact 為單一來源；本檔僅為 PR 提交時之 checklist。
