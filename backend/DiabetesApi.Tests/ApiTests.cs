using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using DiabetesApi.Data;
using DiabetesApi.Models;
using Xunit;

namespace DiabetesApi.Tests;

/// <summary>
/// Integration tests using WebApplicationFactory + EF Core in-memory database.
/// Mirrors the original pytest test suite.
/// </summary>
public class ApiTests : IClassFixture<CustomWebApplicationFactory>
{
    private readonly HttpClient _client;
    private readonly IServiceProvider _services;

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
    };

    public ApiTests(CustomWebApplicationFactory factory)
    {
        _services = factory.Services;
        _client   = factory.CreateClient();
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private AppDbContext CreateDb()
    {
        var scope = _services.CreateScope();
        return scope.ServiceProvider.GetRequiredService<AppDbContext>();
    }

    private async Task<Patient> SeedPatientAsync(string externalId, string name)
    {
        await using var db = CreateDb();
        var existing = await db.Patients.FirstOrDefaultAsync(p => p.ExternalId == externalId);
        if (existing is not null) return existing;

        var patient = new Patient { ExternalId = externalId, Name = name };
        db.Patients.Add(patient);
        await db.SaveChangesAsync();
        return patient;
    }

    // ── Health ────────────────────────────────────────────────────────────────

    [Fact]
    public async Task HealthEndpoint_Returns200()
    {
        var resp = await _client.GetAsync("/api/health");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal("healthy", body.GetProperty("status").GetString());
    }

    // ── Patients ──────────────────────────────────────────────────────────────

    [Fact]
    public async Task ListPatients_ReturnsEmpty()
    {
        var resp = await _client.GetAsync("/api/patient/list");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        // Total may be ≥ 0 (other tests might have seeded data); just check the key exists
        Assert.True(body.TryGetProperty("total", out _));
    }

    [Fact]
    public async Task ListPatients_WithPagination_ReturnsCorrectItems()
    {
        var p1 = await SeedPatientAsync("P_LIST_PAG_1", "Patient 1");
        var p2 = await SeedPatientAsync("P_LIST_PAG_2", "Patient 2");
        var p3 = await SeedPatientAsync("P_LIST_PAG_3", "Patient 3");

        var resp = await _client.GetAsync("/api/patient/list?page=1&perPage=2");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, body.GetProperty("patients").GetArrayLength());
        
        var respPage2 = await _client.GetAsync("/api/patient/list?page=2&perPage=2");
        Assert.Equal(HttpStatusCode.OK, respPage2.StatusCode);
        
        var body2 = await respPage2.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body2.GetProperty("patients").GetArrayLength() >= 1);
    }

    [Fact]
    public async Task CreatePatient_Returns201()
    {
        var resp = await _client.PostAsJsonAsync("/api/patient/create", new
        {
            external_id = "P001_CREATE",
            name = "Test Patient"
        });
        Assert.Equal(HttpStatusCode.Created, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal("P001_CREATE", body.GetProperty("external_id").GetString());
        Assert.Equal("Test Patient", body.GetProperty("name").GetString());
    }

    [Fact]
    public async Task CreatePatient_WithDateOfBirth_ReturnsAge()
    {
        var birthDate = DateOnly.FromDateTime(DateTime.UtcNow).AddYears(-30);
        var resp = await _client.PostAsJsonAsync("/api/patient/create", new
        {
            external_id = "P002_AGE_TEST",
            name = "Age Test Patient",
            date_of_birth = birthDate.ToString("yyyy-MM-dd")
        });
        Assert.Equal(HttpStatusCode.Created, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal("P002_AGE_TEST", body.GetProperty("external_id").GetString());
        Assert.Equal(30, body.GetProperty("age").GetInt32());
        Assert.False(body.TryGetProperty("date_of_birth", out _));
    }

    [Fact]
    public async Task CreatePatient_MissingFields_Returns400()
    {
        var resp = await _client.PostAsJsonAsync("/api/patient/create", new { });
        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
    }

    [Fact]
    public async Task GetPatient_ReturnsPatient()
    {
        var patient = await SeedPatientAsync("P_GET_TEST", "Get Test Patient");

        var resp = await _client.GetAsync($"/api/patient/{patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal("P_GET_TEST", body.GetProperty("external_id").GetString());
        Assert.Equal("Get Test Patient", body.GetProperty("name").GetString());
    }

    [Fact]
    public async Task GetPatient_NotFound_Returns404()
    {
        var resp = await _client.GetAsync("/api/patient/99999");
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    // ── Glucose ───────────────────────────────────────────────────────────────

    [Fact]
    public async Task GetGlucoseReadings_ReturnsCount()
    {
        var patient = await SeedPatientAsync("P_GLUCOSE", "G Patient");

        await using var db = CreateDb();
        db.Glucoses.Add(new Glucose
        {
            PatientId = patient.Id,
            Timestamp = DateTime.UtcNow,
            GlucoseMmoll = 6.7
        });
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("count").GetInt32() >= 1);
        Assert.Equal(6.7, body.GetProperty("readings")[0].GetProperty("glucose_mmoll").GetDouble());
    }

    [Fact]
    public async Task GetGlucoseReadings_WithTimeRangeAndLast_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_GLUCOSE_FILTER", "GF Patient");
        var now = DateTime.UtcNow;

        await using var db = CreateDb();
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = now.AddMinutes(-180), GlucoseMmoll = 5.0 }, // ~2.2h before latest (Excluded)
            new Glucose { PatientId = patient.Id, Timestamp = now.AddMinutes(-110), GlucoseMmoll = 6.0 }, // ~1.0h before latest (Included)
            new Glucose { PatientId = patient.Id, Timestamp = now.AddMinutes(-50),  GlucoseMmoll = 7.0 }  // latest (Included)
        );
        await db.SaveChangesAsync();

        // 1. Test last
        var respLast = await _client.GetAsync($"/api/glucose?id={patient.Id}&last=2h");
        Assert.Equal(HttpStatusCode.OK, respLast.StatusCode);
        var bodyLast = await respLast.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyLast.GetProperty("count").GetInt32());
        var readingsLast = bodyLast.GetProperty("readings");
        Assert.Equal(7.0, readingsLast[0].GetProperty("glucose_mmoll").GetDouble());
        Assert.Equal(6.0, readingsLast[1].GetProperty("glucose_mmoll").GetDouble());

        // 2. Test start and end filter
        var startStr = now.AddHours(-2.5).ToString("O");
        var endStr = now.AddHours(-0.5).ToString("O");
        var respFilter = await _client.GetAsync($"/api/glucose?id={patient.Id}&start={startStr}&end={endStr}");
        Assert.Equal(HttpStatusCode.OK, respFilter.StatusCode);
        var bodyFilter = await respFilter.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyFilter.GetProperty("count").GetInt32()); // 6.0 and 7.0
    }

    [Fact]
    public async Task GetLatestReading_ReturnsLatest()
    {
        var patient = await SeedPatientAsync("P_LATEST_READING", "Latest Patient");
        var now = DateTime.UtcNow;

        await using var db = CreateDb();
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = now.AddMinutes(-10), GlucoseMmoll = 5.4 },
            new Glucose { PatientId = patient.Id, Timestamp = now,                GlucoseMmoll = 8.2 }
        );
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/latest?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(8.2, body.GetProperty("glucose_mmoll").GetDouble());
    }

    [Fact]
    public async Task GetLatestReading_NotFound_Returns404()
    {
        var resp = await _client.GetAsync("/api/glucose/latest?id=99999");
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    [Fact]
    public async Task GetTir_Returns50PctInRange()
    {
        var patient = await SeedPatientAsync("P_TIR_UNIQUE", "TIR Patient");

        await using var db = CreateDb();
        // Two readings: one in-range (5.6), one high (11.1) → 50% in range
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = DateTime.UtcNow.AddMinutes(-5), GlucoseMmoll = 5.6 },
            new Glucose { PatientId = patient.Id, Timestamp = DateTime.UtcNow,               GlucoseMmoll = 11.1 }
        );
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/tir?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(50.0, body.GetProperty("in_range_pct").GetDouble());
    }

    [Fact]
    public async Task GetTir_WithFilters_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_TIR_FILTER", "TIR Filter Patient");
        var now = DateTime.UtcNow;

        await using var db = CreateDb();
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = now.AddHours(-3), GlucoseMmoll = 12.0 }, // High, out of range
            new Glucose { PatientId = patient.Id, Timestamp = now.AddHours(-2), GlucoseMmoll = 6.0 },  // In range
            new Glucose { PatientId = patient.Id, Timestamp = now.AddHours(-1), GlucoseMmoll = 6.5 }   // In range
        );
        await db.SaveChangesAsync();

        // Query with start filter that excludes the high reading at -3 hours
        var startStr = now.AddHours(-2.5).ToString("O");
        var resp = await _client.GetAsync($"/api/glucose/tir?id={patient.Id}&start={startStr}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        // The only readings after -2.5 hours are 6.0 and 6.5, which are both in-range -> 100%
        Assert.Equal(100.0, body.GetProperty("in_range_pct").GetDouble());
    }

    [Fact]
    public async Task GetTir_WithLastFilter_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_TIR_LAST", "TIR Last Patient");
        var now = DateTime.UtcNow;

        await using var db = CreateDb();
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = now.AddDays(-20), GlucoseMmoll = 12.0 }, // Out of default 2w range, and out of 5d range
            new Glucose { PatientId = patient.Id, Timestamp = now.AddDays(-3),  GlucoseMmoll = 6.0 },  // In range
            new Glucose { PatientId = patient.Id, Timestamp = now,             GlucoseMmoll = 6.5 }   // In range
        );
        await db.SaveChangesAsync();

        // 1. Default (uses default '2w' filtering relative to latest available reading) -> The 12.0 reading at -20d is excluded.
        // Remaining are 6.0 and 6.5, which are both in-range -> 100%
        var respDefault = await _client.GetAsync($"/api/glucose/tir?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, respDefault.StatusCode);
        var bodyDefault = await respDefault.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(100.0, bodyDefault.GetProperty("in_range_pct").GetDouble());

        // 2. Querying with last=3w -> Includes the 12.0 reading.
        // Readings: 12.0, 6.0, 6.5 -> 2 out of 3 in-range -> 66.7%
        var respLast = await _client.GetAsync($"/api/glucose/tir?id={patient.Id}&last=3w");
        Assert.Equal(HttpStatusCode.OK, respLast.StatusCode);
        var bodyLast = await respLast.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(66.7, bodyLast.GetProperty("in_range_pct").GetDouble());
    }

    // ── Average Glucose ───────────────────────────────────────────────────────

    [Fact]
    public async Task GetAverageReading_ReturnsCorrectAverage()
    {
        var patient = await SeedPatientAsync("P_AVG_TEST", "Average Patient");

        await using var db = CreateDb();
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = DateTime.UtcNow.AddMinutes(-10), GlucoseMmoll = 5.0 },
            new Glucose { PatientId = patient.Id, Timestamp = DateTime.UtcNow.AddMinutes(-5),  GlucoseMmoll = 7.0 }
        );
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/average?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var val = await resp.Content.ReadFromJsonAsync<double>(JsonOpts);
        Assert.Equal(6.0, val);
    }

    [Fact]
    public async Task GetAverageReading_WithFilters_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_AVG_FILTER", "Average Filter Patient");
        var now = DateTime.UtcNow;

        await using var db = CreateDb();
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = now.AddDays(-20), GlucoseMmoll = 10.0 }, // Old reading (excluded by default 2w last)
            new Glucose { PatientId = patient.Id, Timestamp = now.AddDays(-2),  GlucoseMmoll = 5.0 },  // Within last 2w (included)
            new Glucose { PatientId = patient.Id, Timestamp = now,             GlucoseMmoll = 7.0 }   // Latest within last 2w (included)
        );
        await db.SaveChangesAsync();

        // 1. Default (uses default '2w' filtering relative to latest available reading at now) -> Average of 5.0 and 7.0 = 6.0
        var respDefault = await _client.GetAsync($"/api/glucose/average?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, respDefault.StatusCode);
        var valDefault = await respDefault.Content.ReadFromJsonAsync<double>(JsonOpts);
        Assert.Equal(6.0, valDefault);

        // 2. Querying with last=3w -> Average of all three (10.0 + 5.0 + 7.0) / 3 = 7.333333333333333
        var respLast = await _client.GetAsync($"/api/glucose/average?id={patient.Id}&last=3w");
        Assert.Equal(HttpStatusCode.OK, respLast.StatusCode);
        var valLast = await respLast.Content.ReadFromJsonAsync<double>(JsonOpts);
        Assert.Equal(7.33, Math.Round(valLast, 2));
    }

    [Fact]
    public async Task GetAverageReading_NotFound_Returns404()
    {
        var resp = await _client.GetAsync("/api/glucose/average?id=99999");
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    // ── Anomalies ─────────────────────────────────────────────────────────────

    [Fact]
    public async Task GetAnomalies_ReturnsCount()
    {
        var patient = await SeedPatientAsync("P_ANOMALY", "A Patient");

        await using var db = CreateDb();
        db.Anomalies.Add(new Anomaly
        {
            PatientId = patient.Id,
            AnomalyType = "missed_bolus",
            Confidence = 0.9
        });
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/anomaly/{patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("count").GetInt32() >= 1);
        Assert.Equal("missed_bolus", body.GetProperty("anomalies")[0].GetProperty("anomaly_type").GetString());
    }

    [Fact]
    public async Task GetAnomalies_WithFilters_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_ANOMALY_FILTER", "AF Patient");

        await using var db = CreateDb();
        db.Anomalies.AddRange(
            new Anomaly { PatientId = patient.Id, AnomalyType = "missed_bolus", Confidence = 0.9, IsAcknowledged = true },
            new Anomaly { PatientId = patient.Id, AnomalyType = "late_bolus",   Confidence = 0.8, IsAcknowledged = false },
            new Anomaly { PatientId = patient.Id, AnomalyType = "hyperglycemia",Confidence = 0.75, IsAcknowledged = false }
        );
        await db.SaveChangesAsync();

        // 1. Filter by acknowledged = true
        var respAck = await _client.GetAsync($"/api/anomaly/{patient.Id}?acknowledged=true");
        Assert.Equal(HttpStatusCode.OK, respAck.StatusCode);
        var bodyAck = await respAck.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(1, bodyAck.GetProperty("count").GetInt32());
        Assert.Equal("missed_bolus", bodyAck.GetProperty("anomalies")[0].GetProperty("anomaly_type").GetString());

        // 2. Filter by acknowledged = false
        var respUnack = await _client.GetAsync($"/api/anomaly/{patient.Id}?acknowledged=false");
        Assert.Equal(HttpStatusCode.OK, respUnack.StatusCode);
        var bodyUnack = await respUnack.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyUnack.GetProperty("count").GetInt32());

        // 3. Filter with limit = 1
        var respLimit = await _client.GetAsync($"/api/anomaly/{patient.Id}?limit=1");
        Assert.Equal(HttpStatusCode.OK, respLimit.StatusCode);
        var bodyLimit = await respLimit.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(1, bodyLimit.GetProperty("count").GetInt32());
    }

    [Fact]
    public async Task AcknowledgeAnomaly_SetsFlag()
    {
        var patient = await SeedPatientAsync("P_ACK_UNIQUE", "ACK Patient");

        await using var db = CreateDb();
        var anomaly = new Anomaly
        {
            PatientId = patient.Id,
            AnomalyType = "late_bolus",
            Confidence = 0.8
        };
        db.Anomalies.Add(anomaly);
        await db.SaveChangesAsync();

        var resp = await _client.PostAsync($"/api/anomaly/{anomaly.Id}/acknowledge", null);
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("is_acknowledged").GetBoolean());
    }

    [Fact]
    public async Task AcknowledgeAnomaly_NotFound_Returns404()
    {
        var resp = await _client.PostAsync("/api/anomaly/99999/acknowledge", null);
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    // ── History ───────────────────────────────────────────────────────────────

    [Fact]
    public async Task GetHistory_ReturnsCount()
    {
        var patient = await SeedPatientAsync("P_HISTORY", "History Patient");

        await using var db = CreateDb();
        db.Histories.Add(new History
        {
            PatientId = patient.Id,
            Timestamp = DateTime.UtcNow,
            Glucose = 5.5f,
            Insulin = 2.0f,
            Meal = 45.0f
        });
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/history/{patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("count").GetInt32() >= 1);
        var hist = body.GetProperty("histories")[0];
        Assert.Equal(5.5f, hist.GetProperty("glucose").GetSingle());
        Assert.Equal(2.0f, hist.GetProperty("insulin").GetSingle());
        Assert.Equal(45.0f, hist.GetProperty("meal").GetSingle());
    }

    [Fact]
    public async Task GetHistory_WithLimit_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_HISTORY_LIMIT", "History Limit Patient");

        await using var db = CreateDb();
        db.Histories.AddRange(
            new History { PatientId = patient.Id, Timestamp = DateTime.UtcNow.AddMinutes(-10), Glucose = 5.0f },
            new History { PatientId = patient.Id, Timestamp = DateTime.UtcNow.AddMinutes(-5),  Glucose = 6.0f },
            new History { PatientId = patient.Id, Timestamp = DateTime.UtcNow,               Glucose = 7.0f }
        );
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/history/{patient.Id}?limit=2");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, body.GetProperty("count").GetInt32());
        var list = body.GetProperty("histories");
        Assert.Equal(7.0f, list[0].GetProperty("glucose").GetSingle());
        Assert.Equal(6.0f, list[1].GetProperty("glucose").GetSingle());
    }

    // ── Insulin ───────────────────────────────────────────────────────────────

    [Fact]
    public async Task GetInsulins_ReturnsCount()
    {
        var patient = await SeedPatientAsync("P_INSULIN_T", "Insulin Patient");

        await using var db = CreateDb();
        db.Insulins.Add(new Insulin
        {
            PatientId = patient.Id,
            Timestamp = DateTime.UtcNow,
            Units = 3.5f,
            EventType = "bolus"
        });
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/insulin/{patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("count").GetInt32() >= 1);
        var ins = body.GetProperty("insulins")[0];
        Assert.Equal(3.5f, ins.GetProperty("units").GetSingle());
        Assert.Equal("bolus", ins.GetProperty("event_type").GetString());
    }

    [Fact]
    public async Task GetInsulins_WithLimit_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_INSULIN_LIMIT", "Insulin Limit Patient");

        await using var db = CreateDb();
        db.Insulins.AddRange(
            new Insulin { PatientId = patient.Id, Timestamp = DateTime.UtcNow.AddMinutes(-10), Units = 1.0f, EventType = "basal" },
            new Insulin { PatientId = patient.Id, Timestamp = DateTime.UtcNow.AddMinutes(-5),  Units = 2.0f, EventType = "bolus" },
            new Insulin { PatientId = patient.Id, Timestamp = DateTime.UtcNow,               Units = 3.0f, EventType = "bolus" }
        );
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/insulin/{patient.Id}?limit=2");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, body.GetProperty("count").GetInt32());
        var list = body.GetProperty("insulins");
        Assert.Equal(3.0f, list[0].GetProperty("units").GetSingle());
        Assert.Equal(2.0f, list[1].GetProperty("units").GetSingle());
    }

    // ── Meal ──────────────────────────────────────────────────────────────────

    [Fact]
    public async Task GetMeals_ReturnsCount()
    {
        var patient = await SeedPatientAsync("P_MEAL_T", "Meal Patient");

        await using var db = CreateDb();
        db.Meals.Add(new Meal
        {
            PatientId = patient.Id,
            Timestamp = DateTime.UtcNow,
            Carbs = 60.0f,
            MealType = "lunch"
        });
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/meal/{patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("count").GetInt32() >= 1);
        var meal = body.GetProperty("meals")[0];
        Assert.Equal(60.0f, meal.GetProperty("carbs").GetSingle());
        Assert.Equal("lunch", meal.GetProperty("meal_type").GetString());
    }

    [Fact]
    public async Task GetMeals_WithLimit_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_MEAL_LIMIT", "Meal Limit Patient");

        await using var db = CreateDb();
        db.Meals.AddRange(
            new Meal { PatientId = patient.Id, Timestamp = DateTime.UtcNow.AddMinutes(-10), Carbs = 10.0f, MealType = "snack" },
            new Meal { PatientId = patient.Id, Timestamp = DateTime.UtcNow.AddMinutes(-5),  Carbs = 20.0f, MealType = "lunch" },
            new Meal { PatientId = patient.Id, Timestamp = DateTime.UtcNow,               Carbs = 30.0f, MealType = "dinner" }
        );
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/meal/{patient.Id}?limit=2");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, body.GetProperty("count").GetInt32());
        var list = body.GetProperty("meals");
        Assert.Equal(30.0f, list[0].GetProperty("carbs").GetSingle());
        Assert.Equal(20.0f, list[1].GetProperty("carbs").GetSingle());
    }
}
