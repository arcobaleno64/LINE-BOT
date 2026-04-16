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
WORKDIR /app

# 建立非 root 用戶以提高安全性
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

COPY --from=build /app/publish .

# 切換至非 root 用戶
USER appuser

EXPOSE 10000

ENTRYPOINT ["/bin/sh", "-c", "ASPNETCORE_URLS=http://0.0.0.0:${PORT:-10000} exec dotnet LineBotWebhook.dll"]
