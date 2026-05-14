# ── Build stage ───────────────────────────────────────────────────────────────
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

# Copy solution + project files first for layer caching
COPY DiabetesApi/DiabetesApi.csproj          DiabetesApi/
COPY DiabetesApi.Tests/DiabetesApi.Tests.csproj DiabetesApi.Tests/
COPY DiabetesApi.slnx .

RUN dotnet restore DiabetesApi.slnx

# Copy sources and publish
COPY DiabetesApi/ DiabetesApi/
RUN dotnet publish DiabetesApi/DiabetesApi.csproj \
    -c Release \
    -o /app/out

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS runtime
WORKDIR /app

COPY --from=build /app/out .

# Listen on port 8000
EXPOSE 8000
ENV ASPNETCORE_URLS=http://+:8000
ENV ASPNETCORE_ENVIRONMENT=Production

ENTRYPOINT ["dotnet", "DiabetesApi.dll"]
