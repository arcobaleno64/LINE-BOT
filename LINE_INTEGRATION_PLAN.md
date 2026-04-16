# LINE Messaging API 整合規劃

> 文件類型：產品整合藍圖  
> 文件目的：描述目前整合現況、可擴充能力、與後續實作優先序。  
> 更新原則：以當前程式碼行為為準，避免個人化或特定身份敘述。

---

## 一、目前整合現況（已落地）

### 核心流程
- Webhook 驗簽：`x-line-signature` 驗證後才進入處理流程
- 事件處理：有界背景佇列 + hosted worker
- 分派模式：dispatcher 路由到 text/image/file/postback
- 回覆機制：文字回覆、Flex 回覆、Quick Reply

### 已實作能力（重點）
| 能力 | 狀態 | 備註 |
|---|---|---|
| 文字訊息處理 | 已實作 | group/room 需 mention gate |
| 圖片訊息處理 | 已實作 | 群組預設忽略圖片 |
| 檔案訊息處理 | 已實作 | 支援 txt/md/csv/json/xml/log/pdf/docx/xlsx/pptx |
| Postback 事件路由 | 已實作 | 已可接收與解析資料 |
| Loading Indicator | 已實作 | 已整合於訊息流程 |
| Flex Message 輸出 | 已實作 | 摘要與搜尋結果可卡片化 |
| 多供應商 AI failover | 已實作 | 具備冷卻、快取、合併保護 |
| 健康檢查與 readiness | 已實作 | `/health`、`/ready` |
| 部署後驗證 | 已實作 | `/health` + 無效簽章 `401` 檢查 |

---

## 二、相容性與行為邊界

### 群組 / room 行為
| 類型 | 目前行為 |
|---|---|
| 文字 | 僅在 mention bot 時處理 |
| 圖片 | 預設略過 |
| 檔案 | 可由 `App:AllowGroupFileHandling` 控制（預設開啟） |
| postback | 可接收並路由 |

### 已知限制
- 掃描型 PDF 與純圖片 PDF 仍不支援
- process-local 狀態不會跨實例共享
- 下載連結為短效 token，重新部署後可能失效

---

## 三、分階段優化藍圖

### Phase 1（高優先）
- 完善 postback action 對應（目前已接入路由，需補齊業務 action）
- 擴充 Quick Reply action 類型（postback/uri/datetimepicker/location）
- 建立群組檔案處理策略文件（開關、風險、預設值）

### Phase 2（中優先）
- 加入 Follow/Join 等事件型導覽訊息（中性品牌語氣）
- 擴充 Template/Flex 的共用 builder 規格
- 補齊 sticker/location 事件解析策略

### Phase 3（長期）
- 導入跨實例共享狀態（Redis）
- 建立 webhook 與回覆流程觀測儀表板
- 建立 ADR 與 API 參考文件

---

## 四、設計護欄

### 必守原則
- 不可繞過簽章驗證
- 不可繞過群組 mention gate（文字）
- 不可記錄敏感 token、key、完整錯誤 body
- 不可在高風險路徑引入 request-thread fire-and-forget

### 建議規範
- 統一使用結構化日誌欄位
- 所有新訊息樣板皆需 `altText`
- 新事件類型需補邊界測試與回歸測試

---

## 五、技術調整清單（待辦）

| 項目 | 優先度 | 目標 |
|---|---|---|
| Postback action 實作 | 高 | 建立穩定互動流程 |
| Quick Reply action 擴充 | 高 | 提升操作效率 |
| 群組檔案策略測試 | 高 | 降低群組誤觸風險 |
| 事件型訊息樣板標準化 | 中 | 提升維護性 |
| 共享狀態評估 | 中 | 提升多實例一致性 |

---

## 六、文件維護規範

- 本文件屬規劃文件，內容以「現況 + 路線」為主
- 不記載個人姓名、個人頭像、單位稱謂等資訊
- 每次功能上線後，需同步更新「一、目前整合現況」與「二、相容性與行為邊界」
