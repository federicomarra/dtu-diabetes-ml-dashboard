using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.Services;

var builder = WebApplication.CreateBuilder(args);

// ── Database ──────────────────────────────────────────────────────────────────
var useInMemory = builder.Configuration["USE_INMEMORY_DB"] == "true";

if (useInMemory)
{
    // Test mode: use EF Core in-memory database
    var dbName = builder.Configuration["INMEMORY_DB_NAME"] ?? "DiabetesTestDb";
    builder.Services.AddDbContext<AppDbContext>(opts =>
        opts.UseInMemoryDatabase(dbName));
}
else
{
    var connectionString = builder.Configuration["DATABASE_URL"]
        ?? builder.Configuration.GetConnectionString("DefaultConnection")
        ?? "Host=localhost;Port=5432;Database=diabetes_db;Username=postgres;Password=postgres";

    // Convert postgres:// URL format (Railway) to Npgsql format if needed
    if (connectionString.StartsWith("postgres://") || connectionString.StartsWith("postgresql://"))
    {
        var uri = new Uri(connectionString.Replace("postgres://", "postgresql://"));
        var userInfo = uri.UserInfo.Split(':');
        connectionString = $"Host={uri.Host};Port={uri.Port};Database={uri.AbsolutePath.TrimStart('/')};Username={userInfo[0]};Password={userInfo[1]}";
    }

    builder.Services.AddDbContext<AppDbContext>(opts =>
        opts.UseNpgsql(connectionString));
}

// ── Application Services ──────────────────────────────────────────────────────
builder.Services.AddScoped<GlucoseService>();
builder.Services.AddScoped<PatientService>();
builder.Services.AddScoped<UploadService>();

// ML inference microservice client (reaches the `ml` container at $ML_URL; localhost = the
// backend's own container, so this MUST be the compose service DNS). Inference is a
// sliding-window pass — weeks of data take a while — so the timeout is generous (gunicorn
// side is 300 s); bound the demo window to keep the synchronous call snappy.
var mlUrl = builder.Configuration["ML_URL"] ?? "http://ml:5001";
builder.Services.AddHttpClient<MlInferenceService>(c =>
{
    c.BaseAddress = new Uri(mlUrl);
    c.Timeout = TimeSpan.FromSeconds(120);
});

// ── Controllers ───────────────────────────────────────────────────────────────
builder.Services.AddControllers()
    .AddJsonOptions(opts =>
    {
        opts.JsonSerializerOptions.PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.SnakeCaseLower;
    });

// ── CORS ──────────────────────────────────────────────────────────────────────
var corsOrigins = builder.Configuration["CORS_ORIGINS"] ?? "*";
builder.Services.AddCors(opts =>
{
    opts.AddDefaultPolicy(policy =>
    {
        if (corsOrigins == "*")
            policy.AllowAnyOrigin().AllowAnyMethod().AllowAnyHeader();
        else
            policy.WithOrigins(corsOrigins.Split(','))
                  .AllowAnyMethod().AllowAnyHeader();
    });
});

// ── Swagger / OpenAPI ─────────────────────────────────────────────────────────
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new Microsoft.OpenApi.OpenApiInfo
    {
        Title       = "DTU Diabetes ML Dashboard API",
        Version     = "v1",
        Description = "REST API for continuous glucose monitoring, insulin tracking, and ML-powered anomaly detection.",
    });
    // Include XML doc comments for richer Swagger descriptions
    var xmlFile = $"{System.Reflection.Assembly.GetExecutingAssembly().GetName().Name}.xml";
    var xmlPath = Path.Combine(AppContext.BaseDirectory, xmlFile);
    if (File.Exists(xmlPath))
        c.IncludeXmlComments(xmlPath);
});

// ── Build ─────────────────────────────────────────────────────────────────────
var app = builder.Build();

app.UseCors();

// Swagger available in all environments (including Docker)
app.UseSwagger();
app.UseSwaggerUI(c =>
{
    c.SwaggerEndpoint("/swagger/v1/swagger.json", "DTU Diabetes API v1");
    c.RoutePrefix = "swagger";
    c.DocumentTitle = "DTU Diabetes ML Dashboard — API Docs";
});

app.UseAuthorization();
app.MapControllers();

app.Run();

// Expose for WebApplicationFactory in tests
public partial class Program { }
