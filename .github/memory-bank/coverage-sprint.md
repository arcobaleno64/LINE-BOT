# Coverage Sprint — 測試覆蓋率衝刺經驗筆記

**Reference**: artifacts/scripts/test_guard_units.py, artifacts/scripts/test_security_scans.py, .coveragerc  
**Last Updated**: 2026-04-18T00:19:32+08:00  
**Commits**: 3efb833 → c7cc8a7（master）

## 成果摘要

- 13 個 Python 模組，3118 stmts，0 miss，959 tests
- CI gate：`--cov-fail-under=100`
- 從 51% 分 6 階段推到 100%（51→64→83→90→95→97→100）

## 階段策略

| 階段 | 覆蓋率 | CI 門檻 | 策略 |
|---|---|---|---|
| Phase 1 | 51%→64% | 60% | 低垂果實：pure functions、utility modules |
| Phase 2 | 64%→83% | 80% | 中等複雜度：validators with subprocess mocking |
| Phase 3 | 83%→90% | 90% | guard_status_validator 主體（最大模組 1253 stmts） |
| Phase 4 | 90%→97% | 90% | GSV 剩餘分支 + 其他 validators 收尾 |
| Phase 5 | 97%→99% | 100% | 新模組（discover_templates、update_repository_profile） |
| Phase 6 | 99%→100% | 100% | 大模組（repo_health_dashboard、run_red_team_suite 553 stmts） |

## 關鍵測試技巧

### monkeypatch 優先於 mock
- `monkeypatch.setattr(module, "CONSTANT", value)` 控制常數
- `monkeypatch.setattr(module, "function", lambda *a: ...)` 控制依賴
- 比 `unittest.mock.patch` 更簡潔、更明確

### subprocess mocking 模式
```python
def fake_run(*args, **kwargs):
    cp = subprocess.CompletedProcess(args[0], 0, stdout="...", stderr="")
    return cp
monkeypatch.setattr(subprocess, "run", fake_run)
```

### importlib.reload 測試 import-time guards
```python
monkeypatch.setattr(shutil, "which", lambda _: None)
with pytest.raises(SystemExit):
    importlib.reload(module)
```

### argparse exclusion 模式
`.coveragerc` 排除 argparse 樣板行，因為 100% 覆蓋 argparse 定義無意義：
```
exclude_lines =
    def main\(
    parser\.add_argument
    parser = argparse
    args = parser\.parse
    return parser\.parse
```

### HTTP server context manager
```python
with run_server(handler_class, port) as server:
    # test against localhost:port
```
用於測試需要 HTTP 回應的函式（如 `github_pr_files_server`）

## 踩坑紀錄

### 1. Python 3.14 行為變更
- `importlib.util.spec_from_file_location()` 對不存在的路徑拋 `FileNotFoundError`，舊版拋 `RuntimeError`
- 解法：`pytest.raises((RuntimeError, FileNotFoundError))`

### 2. REQUIRED_TOPICS 與 topic 上限衝突
- `update_repository_profile` 有 6 個 `REQUIRED_TOPICS` + 使用者 topics，GitHub 上限 20（normalize 後 ≤12）
- 測試中給 8 個 base topics + 6 required = 14 > 12，導致斷言失敗
- 解法：測試 topics 與 REQUIRED_TOPICS 重疊（如 `list(REQUIRED_TOPICS)[:4] + ["extra"]`）
- 測 `too_few` 需 monkeypatch `REQUIRED_TOPICS = set()`，因為有 required topics 時 normalize 永遠 ≥6

### 3. argparse 行的覆蓋
- `return parser.parse_args(argv)` 不被 `args = parser\.parse` 匹配
- 需額外加 `return parser\.parse` 到 `.coveragerc`

### 4. PowerShell cwd 問題
- Terminal 若在 `artifacts/scripts/`，`.venv\Scripts\python` 路徑會找不到
- 解法：每次命令前先 `cd` 到 project root

### 5. 測試不應重新實作邏輯
- `test_detect_repo_root_no_match` 最初在 test 中重寫了函式邏輯，而非呼叫原函式
- 正確做法：monkeypatch 環境後呼叫原函式，驗證預期行為

## 模組難度排序（由易到難）

1. `workflow_constants.py` — 4 stmts，純常數
2. `validate_scorecard_deltas.py` — 40 stmts，簡單 YAML 比對
3. `discover_templates.py` — 45 stmts，檔案系統掃描
4. `update_repository_profile.py` — 47 stmts，GitHub API mock 需注意 topic 邏輯
5. `aggregate_red_team_scorecard.py` — 66 stmts，Markdown / scorecard 聚合
6. `prompt_regression_validator.py` — 128 stmts，hash 比對
7. `guard_contract_validator.py` — 133 stmts，多檔案同步檢查
8. `repo_health_dashboard.py` — 158 stmts，argparse + status 檔掃描
9. `build_decision_registry.py` — 158 stmts，Markdown parsing
10. `repo_security_scan.py` — 160 stmts，secret / static heuristic scanning
11. `validate_context_stack.py` — 192 stmts，YAML + 多層驗證
12. `run_red_team_suite.py` — 688 stmts，23 RT cases + HTTP server + subprocess
13. `guard_status_validator.py` — 1299 stmts，最複雜，涵蓋所有 artifact 狀態機

## CI 設定

```yaml
# .github/workflows/workflow-guards.yml
- run: |
        python -m pytest artifacts/scripts/test_guard_units.py artifacts/scripts/test_security_scans.py -v \
            --cov \
            --cov-config=.coveragerc \
            --cov-report=term-missing \
            --cov-report=html:coverage-report \
            --cov-fail-under=100
```

## Template 同步提醒

每次修改 `.coveragerc`、`test_guard_units.py` 或 `test_security_scans.py` 後，必須同步到 `template/`：
```powershell
Copy-Item .coveragerc template/.coveragerc
Copy-Item artifacts/scripts/test_guard_units.py template/artifacts/scripts/test_guard_units.py
Copy-Item artifacts/scripts/test_security_scans.py template/artifacts/scripts/test_security_scans.py
```
