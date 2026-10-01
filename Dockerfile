# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

COPY ["LineBotWebhook.csproj", "./"]
RUN --mount=type=cache,target=/root/.nuget/packages \
    dotnet restore "LineBotWebhook.csproj"

COPY . .
RUN --mount=type=cache,target=/root/.nuget/packages \
    dotnet publish "LineBotWebhook.csproj" -c Release -o /app/publish --no-restore /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS final
ARG BUILD_COMMIT_SHA=unknown
ENV App__BuildCommit=${BUILD_COMMIT_SHA}
WORKDIR /app

# 建立非 root 用戶以提高安全性
RUN groupadd --system appgroup && \
    useradd --system --create-home --gid appgroup appuser && \
    mkdir -p /app/data /app/generated-files && \
    chown appuser:appgroup /app/data /app/generated-files

COPY --from=build --chown=appuser:appgroup /app/publish .

# 切換至非 root 用戶
USER appuser
RUN test -w /app/generated-files

EXPOSE 10000

ENTRYPOINT ["/bin/sh", "-c", "ASPNETCORE_URLS=http://0.0.0.0:${PORT:-10000} exec dotnet LineBotWebhook.dll"]
