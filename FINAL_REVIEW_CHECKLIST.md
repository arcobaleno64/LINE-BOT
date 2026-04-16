# 最終複查清單

> 文件類型：發布前檢核清單  
> 目的：確保上線前的安全性、正確性、可維運性一致。

## A. Webhook 與安全
- [ ] `POST /api/line/webhook` 路由未被破壞
- [ ] 驗簽在任何處理前執行
- [ ] 無效簽章回傳 `401`
- [ ] 日誌未輸出 token、API key、完整 request body

## B. 事件與處理流程
- [ ] 事件由有界背景佇列接收
- [ ] hosted worker 正常消化佇列
- [ ] dispatcher 可正確路由 text/image/file/postback
- [ ] 群組文字 mention gate 規則未被繞過

## C. AI 與保護機制
- [ ] throttle/backoff/cache/merge 保護邏輯可用
- [ ] failover 順序與條件符合預期
- [ ] 配額耗盡與 429 的回應策略可觀測

## D. 檔案與下載
- [ ] 檔案格式支援描述與實作一致
- [ ] 下載連結短效行為與文件一致
- [ ] 不支援格式回覆訊息一致且明確

## E. 部署與驗證
- [ ] CI 在建置前執行 `dotnet test`
- [ ] 觸發部署後可執行 smoke verify
- [ ] `/health` 回 `200`
- [ ] 無效簽章 webhook 測試回 `401`

## F. 文件一致性
- [ ] README / README.zh-TW 敘述一致
- [ ] USER_GUIDE 與實作行為一致
- [ ] DEPLOYMENT_MANUAL 與 CI 流程一致
- [ ] 規劃與評估文件使用時間點或快照語氣
- [ ] 無個人姓名、單位或個人化識別描述
