# 第三輪測試強化 — 最終複查清單 ✅

## 路由與 Ingress Contract

- ✅ **LineWebhookController.cs 仍是 POST /api/line/webhook**
  - Location: `[Route("api/line")]` + `[HttpPost("webhook")]`
  - Verified: [Controllers/LineWebhookController.cs](Controllers/LineWebhookController.cs#L11-L12)

- ✅ **仍使用 raw body + x-line-signature 驗簽**
  - Code: `Request.Headers["x-line-signature"].ToString()` passed to `_signatureVerifier.Verify()`
  - Verified: [Controllers/LineWebhookController.cs](Controllers/LineWebhookController.cs#L28-L31)

- ✅ **Invalid signature 仍回 401**
  - Code: `return Unauthorized();` when signature verification fails
  - Verified: [Controllers/LineWebhookController.cs](Controllers/LineWebhookController.cs#L30)

---

## Ack 模式

- ✅ **Controller 仍是先回 200 OK**
  - Code: `return Ok();` at end of webhook method
  - Verified: [Controllers/LineWebhookController.cs](Controllers/LineWebhookController.cs#L56)

- ✅ **仍用 Task.Run(..., CancellationToken.None) 背景處理**
  - Code: `_ = Task.Run(async () => { ... }, CancellationToken.None);`
  - Verified: [Controllers/LineWebhookController.cs](Controllers/LineWebhookController.cs#L45-L46)

- ✅ **沒有改成同步等待 dispatcher/AI**
  - Confirmed: empty events return `Ok()` immediately without waiting
  - Verified: [Controllers/LineWebhookController.cs](Controllers/LineWebhookController.cs#L37-L38)

---

## 行為等價

- ✅ **Group/Room 文字仍只在 mention 時處理**
  - MentionGateService: `if (sourceType is "group" or "room") { return evt.Message.Mention?.Mentionees?.Any(m => m.IsSelf) == true; }`
  - Verified: [Services/MentionGateService.cs](Services/MentionGateService.cs#L28-L32)

- ✅ **Image/File 仍只處理 source.type == "user"**
  - ImageMessageHandler: `if (evt.Source?.Type is "group" or "room") return true;`
  - FileMessageHandler: `if (evt.Source?.Type is "group" or "room") return true;`
  - Verified: [Services/ImageMessageHandler.cs](Services/ImageMessageHandler.cs#L35-L36), [Services/FileMessageHandler.cs](Services/FileMessageHandler.cs#L36-L37)

- ✅ **Unsupported message 在 user source 仍回原 fallback 文案**
  - Text: `"目前我支援文字、圖片與檔案（txt/md/csv/json/xml/log/pdf）。PDF 目前先支援文字型 PDF。"`
  - Location: [Services/LineWebhookDispatcher.cs](Services/LineWebhookDispatcher.cs#L48)

- ✅ **Fallback 文案內容完全未改**
  - Same as original controller version, character-for-character

---

## DateTime Parity

- ✅ **DateTimeIntentResponder.cs 的 normalize 已補回所有 8 個符號**
  ```csharp
  .Replace("：", "")   // ✅ Added R2
  .Replace(":", "")    // ✅ Added R2
  .Replace("；", "")   // ✅ Added R2
  .Replace(";", "")    // ✅ Added R2
  .Replace("（", "")   // ✅ Added R2
  .Replace("）", "")   // ✅ Added R2
  .Replace("(", "")    // ✅ Added R2
  .Replace(")", "")    // ✅ Added R2
  ```
  - Verified: [Services/DateTimeIntentResponder.cs](Services/DateTimeIntentResponder.cs#L136-L145)

- ✅ **既有正規化字元沒有被刪掉**
  - Original 8 chars: ？, ?, ，, ,, 。, ！, !, space, tab, newline — all present
  - Verified: [Services/DateTimeIntentResponder.cs](Services/DateTimeIntentResponder.cs#L132-L149)

- ✅ **日期/時間/星期回覆格式未改**
  - Time format: `$"現在時間：{now:HH:mm:ss}"`
  - Date format: `$"{dayLabel}日期：{target:yyyy 年 MM 月 dd 日}"`
  - Weekday format: `$"{dayLabel}：{weekday}"`
  - All verified exactly as original

---

## DI 與 Runtime Semantics

- ✅ **Program.cs 中既有 stateful services 仍是 singleton**
  ```csharp
  // All remain Singleton in Program.cs:
  - UserRequestThrottleService
  - Ai429BackoffService
  - AiResponseCacheService
  - InFlightRequestMergeService
  ```
  - Verified: [Program.cs](Program.cs#L31-L34)

- ✅ **沒有改 UserRequestThrottleService、Ai429BackoffService、AiResponseCacheService、InFlightRequestMergeService 的 lifetime**
  - Confirmed: All remain `.AddSingleton<..>()`

- ✅ **沒有改 App:* fallback 行為**
  - Configuration defaults: `App:AiMergeWindowSeconds = 60`, `App:AiResponseCacheSeconds = 180`, etc.
  - Fallback values applied identically in config resolution

---

## 第三輪測試可測性調整

- ✅ **InternalsVisibleTo("LineBotWebhook.Tests") 已正確加入**
  ```csharp
  [assembly: InternalsVisibleTo("LineBotWebhook.Tests")]
  ```
  - Location: [Properties/AssemblyInfo.cs](Properties/AssemblyInfo.cs)

- ✅ **TextMessageHandler 只有可見性調整，沒有邏輯變更**
  - Changed: `private async Task<string> GetMergedTextReplyAsync()` → `internal async Task<string> GetMergedTextReplyAsync()`
  - Zero code changes to method body
  - Verified: [Services/TextMessageHandler.cs](Services/TextMessageHandler.cs#L143)

- ✅ **TestHelpers.cs 已移除 reflection 依賴**
  - Before: 7 lines of reflection (BindingFlags, GetMethod, Invoke)
  - After: 1 line direct call `return handler.GetMergedTextReplyAsync(userKey, userText, ct);`
  - Also removed: `using System.Reflection;` import
  - Verified: [LineBotWebhook.Tests/TestHelpers.cs](LineBotWebhook.Tests/TestHelpers.cs#L248-L250)

- ✅ **Cache/merge 測試已改成直接呼叫 internal seam**
  - `TextCacheHit_SecondCall_DoesNotCallAiAgain` — direct call, no reflection
  - `TextMergeJoined_SameWindow_UsesSingleInFlightAiCall` — direct call, no reflection
  - Verified: Both pass in test run

---

## 測試覆蓋

### 基礎 Webhook 測試
- ✅ `InvalidSignature_Returns401` — Verifies 401 on bad signature
- ✅ `EmptyEvents_Returns200` — Verifies 200 with no events
- ✅ `Webhook_ValidBody_Returns200_AndDispatchesEvent` — Verifies dispatch called

### DateTime Parity 測試 (強化版)
- ✅ `DateTimeIntentResponder_Parity_ValidatesSemanticOutput(現在：幾點, 現在時間：)` — Time shortcut semantic validation
- ✅ `DateTimeIntentResponder_Parity_ValidatesSemanticOutput(今天：（幾號）, 今天日期：)` — Date shortcut semantic validation
- ✅ `DateTimeIntentResponder_Parity_ValidatesSemanticOutput(今天;星期幾, 今天：星期)` — Weekday shortcut semantic validation

### 群組/提及測試
- ✅ `GroupTextWithoutMention_IsIgnored` — Group text without mention returns true (no AI call)
- ✅ `GroupTextWithMention_IsHandled` — Group text with mention triggers handler

### 不支援訊息測試
- ✅ `Dispatcher_UnsupportedMessage_UserSource_RepliesFallback` — User gets fallback reply
- ✅ `Dispatcher_UnsupportedMessage_GroupSource_NoFallbackReply` — Group gets no reply

### 429 差異化測試
- ✅ `Ai429QuotaExhausted_ReturnsQuotaMessage` — "配額已達上限" for quota errors
- ✅ `Ai429NonQuota_ReturnsBusyMessage_AndCooldownApplied` — "流量較高" for rate limit + cooldown applied

### 快取/合併測試 (移除 reflection)
- ✅ `TextCacheHit_SecondCall_DoesNotCallAiAgain` — 2nd identical call uses cache, AI call count = 1
- ✅ `TextMergeJoined_SameWindow_UsesSingleInFlightAiCall` — Concurrent identical calls merge into 1 AI call

### 圖片測試
- ✅ `ImageInUserChat_IsHandled` — User image is processed by AI
- ✅ `ImageInGroup_IsIgnored` — Group image returns true (no processing)

### 檔案測試
- ✅ `FileUnsupported_ReturnsUnsupportedMessage` — Binary file returns "目前僅支援文字型檔案"
- ✅ `FileSupported_IncludesDownloadUrl` — Text file includes "下載整理檔" and download URL

### DateTime 快捷測試
- ✅ `DateTimeShortcut_DoesNotCallAi` — DateTime intent doesn't call AI

### 節流測試
- ✅ `ThrottleReject_ReturnsThrottleMessage` — 2nd message within throttle window gets "訊息有點密集"

---

## 測試結果摘要

```
✅ 測試執行成功
   總計: 20
   失敗: 0
   成功: 20
   已跳過: 0
   持續時間: 0.9 秒

✅ 編譯狀態
   LineBotWebhook .................. Success
   LineBotWebhook.Tests ............ Success (minor sourcelink warning only, non-blocking)

✅ 建置完成時間
   所有改動在 1.2 秒內編譯並測試完成
```

---

## 產物清理檢查

- ⚠️ **LineBotWebhook.Tests/ 目錄結構**
  - `bin/Release/net10.0/` — Test output artifacts
  - `obj/Release/net10.0/` — Build intermediates
  - 建議：在提交前執行 `dotnet clean` 清理

- ✅ **沒有不必要的暫存檔**
  - No `.orig` files
  - No editor swaps (vim/VS Code recovery)
  - No IDE-specific build files

---

## 外部行為驗證

| 項目 | 狀態 | 驗證位置 |
|------|------|---------|
| Route: `POST /api/line/webhook` | ✅ Unchanged | LineWebhookController.cs:12 |
| Raw body + x-line-signature | ✅ Unchanged | LineWebhookController.cs:29-30 |
| 200 OK + Task.Run background | ✅ Unchanged | LineWebhookController.cs:46, 56 |
| Invalid signature → 401 | ✅ Unchanged | LineWebhookController.cs:30 |
| Group mention gate | ✅ Unchanged | MentionGateService.cs:28-32 |
| Image/File user-only | ✅ Unchanged | ImageMessageHandler.cs:35, FileMessageHandler.cs:36 |
| Unsupported fallback text | ✅ Unchanged | LineWebhookDispatcher.cs:48 |
| DateTime shortcuts | ✅ Unchanged (fixed parity) | DateTimeIntentResponder.cs:normalized-key |
| DI Singleton lifetimes | ✅ Unchanged | Program.cs:31-34 |

---

## 結論

✅ **所有檢查項通過**

本次第三輪測試強化達成目標：
1. 日期時間奇偶測試從「命中驗證」升級到「語義驗證」
2. 快取/合併測試移除反射依賴，改為直接調用內部方法
3. 所有 20 個測試通過，零回歸
4. 零外部行為變更
5. 最小化生產代碼調整（僅可見性修改）

**準備就緒，可提交 PR。**

---

## PR 準備事項

建議檢查清單（提交前）：
- [ ] 執行 `dotnet clean` 清理構建產物
- [ ] 執行 `git status` 確認未追蹤的檔案
- [ ] 執行 `dotnet build -c Release && dotnet test -c Release` 最終驗證
- [ ] 更新 CHANGELOG.md（如有）
- [ ] 根據 [#7 PR Description](#pr-說明稿) 準備 PR 文案

