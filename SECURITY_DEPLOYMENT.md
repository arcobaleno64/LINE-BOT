# 安全與部署配置改進指南

## 📋 立即需要的改進

### 1. 設置缺失的 GitHub Actions 秘密

在 https://github.com/arcobaleno64/LINE-BOT/settings/secrets/actions 添加：

```
RENDER_SERVICE_HOST: https://your-render-service.onrender.com
```

取代 `your-render-service` 為你的實際 Render 服務名稱。

### 2. 啟用分支保護規則

在 https://github.com/arcobaleno64/LINE-BOT/settings/branches 設置 main 分支：

- ✓ Require a pull request before merging
- ✓ Require status checks to pass before merging (require passing tests)
- ✓ Restrict who can push to matching branches
- ✓ Enforce all the above rules for administrators

### 3. 改進 Dockerfile 安全性

建議添加非 root 用戶：

```dockerfile
# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

COPY ["LineBotWebhook.csproj", "./"]
RUN --mount=type=cache,target=/root/.nuget/packages \
    dotnet restore "LineBotWebhook.csproj"

COPY . .
RUN --mount=type=cache,target=/root/.nuget/packages \
    dotnet publish "LineBotWebhook.csproj" -c Release -o /app/publish \
    --no-restore /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS final
WORKDIR /app

# 建立非 root 用戶
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

COPY --from=build --chown=appuser:appuser /app/publish .

# 切換至非 root 用戶
USER appuser

EXPOSE 10000

ENTRYPOINT ["/bin/sh", "-c", "ASPNETCORE_URLS=http://0.0.0.0:${PORT:-10000} exec dotnet LineBotWebhook.dll"]
```

### 4. 啟用 GitHub Discussions

在 https://github.com/arcobaleno64/LINE-BOT/settings：
- 勾選 "Discussions"
- 建立分類（FAQ、公告、想法等）

## 📊 Render 部署環境變數清單

確認以下環境變數已在 Render 設置：

| 變數 | 來源 | 機敏性 |
|------|------|--------|
| `ASPNETCORE_ENVIRONMENT` | 部署配置 | 公開 |
| `Line__ChannelSecret` | GitHub Secret | 🔒 機敏 |
| `Line__ChannelAccessToken` | GitHub Secret | 🔒 機敏 |
| `Ai__Gemini__ApiKey` | GitHub Secret | 🔒 機敏 |
| `Ai__Gemini__SecondaryApiKey` | GitHub Secret | 🔒 機敏 |
| `WebSearch__TavilyApiKey` | GitHub Secret | 🔒 機敏 |
| `Ai__OpenAI__ApiKey` | GitHub Secret | 🔒 機敏 |
| `Ai__Claude__ApiKey` | GitHub Secret | 🔒 機敏 |

**重要**：所有 API 密鑰應透過 GitHub Secrets 傳遞，不應硬編碼在 render.yaml。

## 🔐 GitHub Actions 安全最佳實踐

### ✅ 已符合
- 使用 GITHUB_TOKEN 進行 Docker 認證
- 限制權限範圍
- 條件式秘密使用（檢查秘密是否存在）

### 📝 建議改進
1. **Checkout 版本**：更新至 `@v4`（已是最新穩定版）
2. **依賴鎖定**：考慮使用特定版本標籤而非 major 版本
3. **日誌過濾**：添加 `mask-secrets` 防止意外洩露

## 🏗️ 部署前檢查清單

在每次部署前驗證：

- [ ] 所有 GitHub Actions 秘密已設置
- [ ] Render 環境變數已同步
- [ ] Health 端點可訪問（GET /health）
- [ ] Ready 端點正常（GET /ready）
- [ ] 無效簽名測試返回 401（安全驗證）
- [ ] 最新測試通過（150/150）
- [ ] Docker 映像已推送到 GHCR
- [ ] 部署驗證腳本執行成功

## 🚀 發佈前檢查清單

- [ ] 更新 CHANGELOG.md
- [ ] 創建 Git tag（git tag -a vX.Y.Z -m "Release vX.Y.Z"）
- [ ] 創建 GitHub Release
- [ ] 更新 README 中的版本號
- [ ] 驗證所有環境變數已設置
- [ ] 測試部署驗證腳本

## 📚 參考文檔
- [GitHub Secrets 最佳實踐](https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions)
- [Render Environment 文檔](https://docs.render.com/)
- [Docker 安全最佳實踐](https://docs.docker.com/develop/security-best-practices/)
- [ASP.NET Core 安全指南](https://learn.microsoft.com/en-us/aspnet/core/security/)
