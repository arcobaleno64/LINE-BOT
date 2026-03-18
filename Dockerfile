FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

COPY ["LineBotWebhook.csproj", "./"]
RUN dotnet restore "LineBotWebhook.csproj"

COPY . .
RUN dotnet publish "LineBotWebhook.csproj" -c Release -o /app/publish /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS final
WORKDIR /app
COPY --from=build /app/publish .

ENV ASPNETCORE_URLS=http://+:10000
EXPOSE 10000

ENTRYPOINT ["dotnet", "LineBotWebhook.dll"]
