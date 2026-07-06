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
    public async Task HealthEndpoint_ReturnsStructuredResponse()
    {
        var resp = await _client.GetAsync("/api/health");

        // The status code is either 200 (all healthy) or 503 (partial — ML is
        // unreachable in the test environment). Both are acceptable here; we only
        // verify that the response has the expected structure and that backend +
        // database are reported as healthy.
        Assert.True(
            resp.StatusCode == HttpStatusCode.OK ||
            resp.StatusCode == HttpStatusCode.ServiceUnavailable,
            $"Unexpected status {resp.StatusCode}");

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.TryGetProperty("status", out _),       "Missing 'status' field");
        Assert.True(body.TryGetProperty("components", out var components), "Missing 'components' field");
        Assert.Equal("healthy", components.GetProperty("backend").GetProperty("status").GetString());
        Assert.Equal("healthy", components.GetProperty("database").GetProperty("status").GetString());
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

        var resp = await _client.GetAsync($"/api/anomaly?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("count").GetInt32() >= 1);
        Assert.Equal("missed_bolus", body.GetProperty("anomalies")[0].GetProperty("anomaly_type").GetString());
    }

    [Fact]
    public async Task GetAnomalies_ReturnsAllSortedBySeverity()
    {
        var patient = await SeedPatientAsync("P_ANOMALY_FILTER", "AF Patient");

        await using var db = CreateDb();
        db.Anomalies.AddRange(
            new Anomaly { PatientId = patient.Id, AnomalyType = "missed_bolus", Confidence = 0.9, Severity = 2.0 },
            new Anomaly { PatientId = patient.Id, AnomalyType = "late_bolus",   Confidence = 0.8, Severity = 4.0 },
            new Anomaly { PatientId = patient.Id, AnomalyType = "missed_bolus", Confidence = 0.95, Severity = 6.0 }
        );
        await db.SaveChangesAsync();

        // Query anomalies.
        var resp = await _client.GetAsync($"/api/anomaly?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(3, body.GetProperty("count").GetInt32());

        // Ordered by severity descending → strongest (6σ) first.
        var list = body.GetProperty("anomalies");
        Assert.Equal(6.0, list[0].GetProperty("severity").GetDouble(), 3);
        Assert.Equal(4.0, list[1].GetProperty("severity").GetDouble(), 3);
        Assert.Equal(2.0, list[2].GetProperty("severity").GetDouble(), 3);
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

        var resp = await _client.PostAsync($"/api/anomaly/acknowledge?patientId={patient.Id}&anomalyId={anomaly.Id}", null);
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("is_acknowledged").GetBoolean());
    }

    [Fact]
    public async Task AcknowledgeAnomaly_NotFound_Returns404()
    {
        var patient = await SeedPatientAsync("P_ACK_NF", "ACK NF Patient");
        var resp = await _client.PostAsync($"/api/anomaly/acknowledge?patientId={patient.Id}&anomalyId=99999", null);
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    [Fact]
    public async Task AcknowledgeAnomaly_WrongPatient_Returns404()
    {
        var patient1 = await SeedPatientAsync("P_ACK_WP1", "ACK WP Patient 1");
        var patient2 = await SeedPatientAsync("P_ACK_WP2", "ACK WP Patient 2");

        await using var db = CreateDb();
        var anomaly = new Anomaly
        {
            PatientId = patient1.Id,
            AnomalyType = "missed_bolus",
            Confidence = 0.9
        };
        db.Anomalies.Add(anomaly);
        await db.SaveChangesAsync();

        // Trying to acknowledge patient1's anomaly as patient2 → must return 404.
        var resp = await _client.PostAsync($"/api/anomaly/acknowledge?patientId={patient2.Id}&anomalyId={anomaly.Id}", null);
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

        var resp = await _client.GetAsync($"/api/history?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("count").GetInt32() >= 1);
        var hist = body.GetProperty("histories")[0];
        Assert.Equal(5.5f, hist.GetProperty("glucose").GetSingle());
        Assert.Equal(2.0f, hist.GetProperty("insulin").GetSingle());
        Assert.Equal(45.0f, hist.GetProperty("meal").GetSingle());
    }

    [Fact]
    public async Task GetHistory_WithTimeRangeAndLast_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_HISTORY_FILTER", "History Filter Patient");
        var now = DateTime.UtcNow;

        await using var db = CreateDb();
        db.Histories.AddRange(
            new History { PatientId = patient.Id, Timestamp = now.AddMinutes(-180), Glucose = 5.0f }, // ~2.2h before latest (Excluded by last=2h)
            new History { PatientId = patient.Id, Timestamp = now.AddMinutes(-110), Glucose = 6.0f }, // ~1.0h before latest (Included)
            new History { PatientId = patient.Id, Timestamp = now.AddMinutes(-50),  Glucose = 7.0f }  // latest (Included)
        );
        await db.SaveChangesAsync();

        // 1. Test last
        var respLast = await _client.GetAsync($"/api/history?id={patient.Id}&last=2h");
        Assert.Equal(HttpStatusCode.OK, respLast.StatusCode);
        var bodyLast = await respLast.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyLast.GetProperty("count").GetInt32());
        var listLast = bodyLast.GetProperty("histories");
        Assert.Equal(7.0f, listLast[0].GetProperty("glucose").GetSingle());
        Assert.Equal(6.0f, listLast[1].GetProperty("glucose").GetSingle());

        // 2. Test start and end filter
        var startStr = now.AddHours(-2.5).ToString("O");
        var endStr = now.AddHours(-0.5).ToString("O");
        var respFilter = await _client.GetAsync($"/api/history?id={patient.Id}&start={startStr}&end={endStr}");
        Assert.Equal(HttpStatusCode.OK, respFilter.StatusCode);
        var bodyFilter = await respFilter.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyFilter.GetProperty("count").GetInt32());
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

        var resp = await _client.GetAsync($"/api/insulin?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("count").GetInt32() >= 1);
        var ins = body.GetProperty("insulins")[0];
        Assert.Equal(3.5f, ins.GetProperty("units").GetSingle());
        Assert.Equal("bolus", ins.GetProperty("event_type").GetString());
    }

    [Fact]
    public async Task GetInsulins_WithTimeRangeAndLast_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_INSULIN_FILTER", "Insulin Filter Patient");
        var now = DateTime.UtcNow;

        await using var db = CreateDb();
        db.Insulins.AddRange(
            new Insulin { PatientId = patient.Id, Timestamp = now.AddMinutes(-180), Units = 1.0f, EventType = "basal" }, // ~2.2h before latest (Excluded by last=2h)
            new Insulin { PatientId = patient.Id, Timestamp = now.AddMinutes(-110), Units = 2.0f, EventType = "bolus" }, // ~1.0h before latest (Included)
            new Insulin { PatientId = patient.Id, Timestamp = now.AddMinutes(-50),  Units = 3.0f, EventType = "bolus" }  // latest (Included)
        );
        await db.SaveChangesAsync();

        // 1. Test last
        var respLast = await _client.GetAsync($"/api/insulin?id={patient.Id}&last=2h");
        Assert.Equal(HttpStatusCode.OK, respLast.StatusCode);
        var bodyLast = await respLast.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyLast.GetProperty("count").GetInt32());
        var listLast = bodyLast.GetProperty("insulins");
        Assert.Equal(3.0f, listLast[0].GetProperty("units").GetSingle());
        Assert.Equal(2.0f, listLast[1].GetProperty("units").GetSingle());

        // 2. Test start and end filter
        var startStr = now.AddHours(-2.5).ToString("O");
        var endStr = now.AddHours(-0.5).ToString("O");
        var respFilter = await _client.GetAsync($"/api/insulin?id={patient.Id}&start={startStr}&end={endStr}");
        Assert.Equal(HttpStatusCode.OK, respFilter.StatusCode);
        var bodyFilter = await respFilter.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyFilter.GetProperty("count").GetInt32());
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

        var resp = await _client.GetAsync($"/api/meal?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("count").GetInt32() >= 1);
        var meal = body.GetProperty("meals")[0];
        Assert.Equal(60.0f, meal.GetProperty("carbs").GetSingle());
        Assert.Equal("lunch", meal.GetProperty("meal_type").GetString());
    }

    [Fact]
    public async Task GetMeals_WithTimeRangeAndLast_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_MEAL_FILTER", "Meal Filter Patient");
        var now = DateTime.UtcNow;

        await using var db = CreateDb();
        db.Meals.AddRange(
            new Meal { PatientId = patient.Id, Timestamp = now.AddMinutes(-180), Carbs = 10.0f, MealType = "snack" }, // ~2.2h before latest (Excluded by last=2h)
            new Meal { PatientId = patient.Id, Timestamp = now.AddMinutes(-110), Carbs = 20.0f, MealType = "lunch" }, // ~1.0h before latest (Included)
            new Meal { PatientId = patient.Id, Timestamp = now.AddMinutes(-50),  Carbs = 30.0f, MealType = "dinner" } // latest (Included)
        );
        await db.SaveChangesAsync();

        // 1. Test last
        var respLast = await _client.GetAsync($"/api/meal?id={patient.Id}&last=2h");
        Assert.Equal(HttpStatusCode.OK, respLast.StatusCode);
        var bodyLast = await respLast.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyLast.GetProperty("count").GetInt32());
        var listLast = bodyLast.GetProperty("meals");
        Assert.Equal(30.0f, listLast[0].GetProperty("carbs").GetSingle());
        Assert.Equal(20.0f, listLast[1].GetProperty("carbs").GetSingle());

        // 2. Test start and end filter
        var startStr = now.AddHours(-2.5).ToString("O");
        var endStr = now.AddHours(-0.5).ToString("O");
        var respFilter = await _client.GetAsync($"/api/meal?id={patient.Id}&start={startStr}&end={endStr}");
        Assert.Equal(HttpStatusCode.OK, respFilter.StatusCode);
        var bodyFilter = await respFilter.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyFilter.GetProperty("count").GetInt32());
    }
    // ── HbA1c ─────────────────────────────────────────────────────────────────

    [Fact]
    public async Task GetHbA1c_Returns200WithCorrectFields()
    {
        var patient = await SeedPatientAsync("P_HBA1C_BASIC", "HbA1c Patient");

        await using var db = CreateDb();
        db.Glucoses.Add(new Glucose
        {
            PatientId    = patient.Id,
            Timestamp    = DateTime.UtcNow,
            GlucoseMmoll = 8.0   // avg = 8.0 mmol/L → 144.1 mg/dL → eA1c% ≈ 6.97
        });
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/hba1c?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(patient.Id, body.GetProperty("patient_id").GetInt32());
        // Both unit fields must be present and positive
        Assert.True(body.GetProperty("percent").GetDouble() > 0);
        Assert.True(body.GetProperty("mmol_per_mol").GetDouble() > 0);
    }

    [Fact]
    public async Task GetHbA1c_ReturnsCorrectFormula()
    {
        var patient = await SeedPatientAsync("P_HBA1C_MATH", "HbA1c Math Patient");

        // Use a single known value so we can verify the formula exactly.
        // avg = 7.0 mmol/L → avg_mg = 7.0 × 18.018 = 126.126 mg/dL
        // eA1c% = (46.7 + 126.126) / 28.7 ≈ 6.0
        // mmol/mol = (6.0 - 2.152) / 0.09148 ≈ 42
        await using var db = CreateDb();
        db.Glucoses.Add(new Glucose
        {
            PatientId    = patient.Id,
            Timestamp    = DateTime.UtcNow,
            GlucoseMmoll = 7.0
        });
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/hba1c?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body   = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        double pct = body.GetProperty("percent").GetDouble();
        double mpm = body.GetProperty("mmol_per_mol").GetDouble();

        // Allow ±0.2% rounding tolerance
        Assert.InRange(pct, 5.8, 6.2);
        Assert.InRange(mpm, 40, 44);
    }

    [Fact]
    public async Task GetHbA1c_NotFound_Returns404()
    {
        var resp = await _client.GetAsync("/api/glucose/hba1c?id=99999");
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    [Fact]
    public async Task GetHbA1c_InvalidLastParam_Returns400()
    {
        var patient = await SeedPatientAsync("P_HBA1C_BAD", "HbA1c Bad Patient");
        // "5x" ends in 'x', which is not a recognised suffix → route guard returns 400
        var resp = await _client.GetAsync($"/api/glucose/hba1c?id={patient.Id}&last=5x");
        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
    }

    [Fact]
    public async Task GetHbA1c_WithLastFilter_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_HBA1C_LAST", "HbA1c Last Patient");
        var now     = DateTime.UtcNow;

        await using var db = CreateDb();
        // Old reading (beyond 2w) → a high value (12.0 mmol/L)
        // Recent reading (within 2w default) → a low value (5.0 mmol/L)
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = now.AddDays(-20), GlucoseMmoll = 12.0 },
            new Glucose { PatientId = patient.Id, Timestamp = now,              GlucoseMmoll = 5.0  }
        );
        await db.SaveChangesAsync();

        // Default (last=2w from latest → excludes the 20-day-old reading)
        // avg = 5.0 mmol/L → lower HbA1c
        var respDefault = await _client.GetAsync($"/api/glucose/hba1c?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, respDefault.StatusCode);
        var pctDefault = (await respDefault.Content.ReadFromJsonAsync<JsonElement>(JsonOpts))
                            .GetProperty("percent").GetDouble();

        // last=3w → includes the 12.0 reading → higher average → higher HbA1c
        var respWide = await _client.GetAsync($"/api/glucose/hba1c?id={patient.Id}&last=3w");
        Assert.Equal(HttpStatusCode.OK, respWide.StatusCode);
        var pctWide = (await respWide.Content.ReadFromJsonAsync<JsonElement>(JsonOpts))
                         .GetProperty("percent").GetDouble();

        Assert.True(pctWide > pctDefault, $"Expected wider window HbA1c ({pctWide}) > default ({pctDefault})");
    }

    [Fact]
    public async Task GetHbA1c_WithStartEndFilter_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_HBA1C_SE", "HbA1c StartEnd Patient");
        var now     = DateTime.UtcNow;

        await using var db = CreateDb();
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = now.AddHours(-5), GlucoseMmoll = 12.0 }, // excluded
            new Glucose { PatientId = patient.Id, Timestamp = now.AddHours(-2), GlucoseMmoll = 5.0  }, // included
            new Glucose { PatientId = patient.Id, Timestamp = now.AddHours(-1), GlucoseMmoll = 5.0  }  // included
        );
        await db.SaveChangesAsync();

        var startStr = now.AddHours(-3).ToString("O");
        var endStr   = now.ToString("O");
        var resp = await _client.GetAsync($"/api/glucose/hba1c?id={patient.Id}&start={startStr}&end={endStr}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        // avg = 5.0 → eA1c% = (46.7 + 5.0×18.018) / 28.7 ≈ 4.77 — much lower than if 12.0 were included
        double pct = body.GetProperty("percent").GetDouble();
        Assert.True(pct < 6.0, $"Expected HbA1c < 6.0 when high reading excluded, got {pct}");
    }

    // ── GMI ───────────────────────────────────────────────────────────────────

    [Fact]
    public async Task GetGmi_Returns200WithCorrectFields()
    {
        var patient = await SeedPatientAsync("P_GMI_BASIC", "GMI Patient");

        await using var db = CreateDb();
        db.Glucoses.Add(new Glucose
        {
            PatientId    = patient.Id,
            Timestamp    = DateTime.UtcNow,
            GlucoseMmoll = 8.0
        });
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/gmi?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(patient.Id, body.GetProperty("patient_id").GetInt32());
        Assert.True(body.GetProperty("gmi").GetDouble() > 0);
    }

    [Fact]
    public async Task GetGmi_ReturnsCorrectFormula()
    {
        var patient = await SeedPatientAsync("P_GMI_MATH", "GMI Math Patient");

        // avg = 7.0 mmol/L → avg_mg = 7.0 × 18.018 = 126.126 mg/dL
        // GMI% = 3.31 + (0.02392 × 126.126) ≈ 6.33
        await using var db = CreateDb();
        db.Glucoses.Add(new Glucose
        {
            PatientId    = patient.Id,
            Timestamp    = DateTime.UtcNow,
            GlucoseMmoll = 7.0
        });
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/gmi?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var gmi = (await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts))
                      .GetProperty("gmi").GetDouble();

        // Allow ±0.2 rounding tolerance
        Assert.InRange(gmi, 6.1, 6.5);
    }

    [Fact]
    public async Task GetGmi_NotFound_Returns404()
    {
        var resp = await _client.GetAsync("/api/glucose/gmi?id=99999");
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    [Fact]
    public async Task GetGmi_InvalidLastParam_Returns400()
    {
        var patient = await SeedPatientAsync("P_GMI_BAD", "GMI Bad Patient");
        // "5x" ends in 'x', which is not a recognised suffix → route guard returns 400
        var resp = await _client.GetAsync($"/api/glucose/gmi?id={patient.Id}&last=5x");
        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
    }

    [Fact]
    public async Task GetGmi_WithLastFilter_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_GMI_LAST", "GMI Last Patient");
        var now     = DateTime.UtcNow;

        await using var db = CreateDb();
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = now.AddDays(-20), GlucoseMmoll = 12.0 }, // beyond 2w window
            new Glucose { PatientId = patient.Id, Timestamp = now,              GlucoseMmoll = 5.0  }  // within 2w window
        );
        await db.SaveChangesAsync();

        // Default last=2w → only 5.0 → lower GMI
        var respDefault = await _client.GetAsync($"/api/glucose/gmi?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, respDefault.StatusCode);
        var gmiDefault = (await respDefault.Content.ReadFromJsonAsync<JsonElement>(JsonOpts))
                             .GetProperty("gmi").GetDouble();

        // last=3w → includes 12.0 → higher average → higher GMI
        var respWide = await _client.GetAsync($"/api/glucose/gmi?id={patient.Id}&last=3w");
        Assert.Equal(HttpStatusCode.OK, respWide.StatusCode);
        var gmiWide = (await respWide.Content.ReadFromJsonAsync<JsonElement>(JsonOpts))
                          .GetProperty("gmi").GetDouble();

        Assert.True(gmiWide > gmiDefault, $"Expected wider window GMI ({gmiWide}) > default ({gmiDefault})");
    }

    [Fact]
    public async Task GetGmi_WithStartEndFilter_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_GMI_SE", "GMI StartEnd Patient");
        var now     = DateTime.UtcNow;

        await using var db = CreateDb();
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = now.AddHours(-5), GlucoseMmoll = 12.0 }, // excluded
            new Glucose { PatientId = patient.Id, Timestamp = now.AddHours(-2), GlucoseMmoll = 5.0  }, // included
            new Glucose { PatientId = patient.Id, Timestamp = now.AddHours(-1), GlucoseMmoll = 5.0  }  // included
        );
        await db.SaveChangesAsync();

        var startStr = now.AddHours(-3).ToString("O");
        var endStr   = now.ToString("O");
        var resp = await _client.GetAsync($"/api/glucose/gmi?id={patient.Id}&start={startStr}&end={endStr}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var gmi = (await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts))
                      .GetProperty("gmi").GetDouble();

        // avg = 5.0 mmol/L → GMI = 3.31 + (0.02392 × 90.09) ≈ 5.46
        // Without the 12.0 reading: GMI should be well below 6.0
        Assert.True(gmi < 6.0, $"Expected GMI < 6.0 when high reading excluded, got {gmi}");
    }

    [Fact]
    public async Task GetGmi_HigherGlucose_YieldsHigherGmi()
    {
        // Verifies monotonicity: higher average glucose → higher GMI
        var pLow  = await SeedPatientAsync("P_GMI_LOW_G",  "GMI Low Glucose");
        var pHigh = await SeedPatientAsync("P_GMI_HIGH_G", "GMI High Glucose");

        await using var db = CreateDb();
        db.Glucoses.AddRange(
            new Glucose { PatientId = pLow.Id,  Timestamp = DateTime.UtcNow, GlucoseMmoll = 5.5 },
            new Glucose { PatientId = pHigh.Id, Timestamp = DateTime.UtcNow, GlucoseMmoll = 11.0 }
        );
        await db.SaveChangesAsync();

        var rLow  = await _client.GetAsync($"/api/glucose/gmi?id={pLow.Id}");
        var rHigh = await _client.GetAsync($"/api/glucose/gmi?id={pHigh.Id}");
        Assert.Equal(HttpStatusCode.OK, rLow.StatusCode);
        Assert.Equal(HttpStatusCode.OK, rHigh.StatusCode);

        var gmiLow  = (await rLow.Content.ReadFromJsonAsync<JsonElement>(JsonOpts)).GetProperty("gmi").GetDouble();
        var gmiHigh = (await rHigh.Content.ReadFromJsonAsync<JsonElement>(JsonOpts)).GetProperty("gmi").GetDouble();

        Assert.True(gmiHigh > gmiLow, $"Expected gmiHigh ({gmiHigh}) > gmiLow ({gmiLow})");
    }

    // ── Scatterplot ───────────────────────────────────────────────────────────

    [Fact]
    public async Task GetScatterplot_Returns200WithCorrectShape()
    {
        var patient = await SeedPatientAsync("P_SCATTER_BASIC", "Scatter Basic Patient");
        var now = DateTime.UtcNow;

        await using var db = CreateDb();
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = now.Date.AddHours(8),  GlucoseMmoll = 5.0 },
            new Glucose { PatientId = patient.Id, Timestamp = now.Date.AddHours(12), GlucoseMmoll = 7.0 },
            new Glucose { PatientId = patient.Id, Timestamp = now.Date.AddHours(20), GlucoseMmoll = 9.0 }
        );
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/scatterplot?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(patient.Id, body.GetProperty("patient_id").GetInt32());
        Assert.True(body.GetProperty("count").GetInt32() >= 1);

        var point = body.GetProperty("points")[0];
        // All three fields must be present
        Assert.True(point.TryGetProperty("date", out _));
        Assert.True(point.TryGetProperty("average", out _));
        Assert.True(point.TryGetProperty("min", out _));
        Assert.True(point.TryGetProperty("max", out _));
    }

    [Fact]
    public async Task GetScatterplot_ReturnsCorrectDailyStats()
    {
        var patient = await SeedPatientAsync("P_SCATTER_STATS", "Scatter Stats Patient");
        var today = DateTime.UtcNow.Date;

        await using var db = CreateDb();
        // Three readings on the same day: avg=7.0, min=5.0, max=9.0
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = today.AddHours(6),  GlucoseMmoll = 5.0 },
            new Glucose { PatientId = patient.Id, Timestamp = today.AddHours(12), GlucoseMmoll = 7.0 },
            new Glucose { PatientId = patient.Id, Timestamp = today.AddHours(20), GlucoseMmoll = 9.0 }
        );
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/scatterplot?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        // Should be exactly 1 point (all same day)
        Assert.Equal(1, body.GetProperty("count").GetInt32());

        var point = body.GetProperty("points")[0];
        Assert.Equal(7.0, point.GetProperty("average").GetDouble(), precision: 1);
        Assert.Equal(5.0, point.GetProperty("min").GetDouble(), precision: 1);
        Assert.Equal(9.0, point.GetProperty("max").GetDouble(), precision: 1);
        Assert.Equal(today.ToString("yyyy-MM-dd"), point.GetProperty("date").GetString());
    }

    [Fact]
    public async Task GetScatterplot_GroupsByDay_MultiplePoints()
    {
        var patient = await SeedPatientAsync("P_SCATTER_MULTI", "Scatter Multi Day Patient");
        var today = DateTime.UtcNow.Date;

        await using var db = CreateDb();
        // Day 1: two readings; Day 2 (yesterday): one reading
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = today.AddHours(8),       GlucoseMmoll = 6.0 },
            new Glucose { PatientId = patient.Id, Timestamp = today.AddHours(18),      GlucoseMmoll = 8.0 },
            new Glucose { PatientId = patient.Id, Timestamp = today.AddDays(-1).AddHours(12), GlucoseMmoll = 5.0 }
        );
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/scatterplot?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        // 2 distinct calendar days → 2 points
        Assert.Equal(2, body.GetProperty("count").GetInt32());

        // Points should be in ascending date order
        var pts = body.GetProperty("points");
        var date0 = pts[0].GetProperty("date").GetString();
        var date1 = pts[1].GetProperty("date").GetString();
        Assert.True(string.Compare(date0, date1, StringComparison.Ordinal) < 0, "Points should be ordered ascending by date");

        // Yesterday's point: single reading 5.0 → avg=min=max=5.0
        Assert.Equal(5.0, pts[0].GetProperty("average").GetDouble(), precision: 1);
        Assert.Equal(5.0, pts[0].GetProperty("min").GetDouble(), precision: 1);
        Assert.Equal(5.0, pts[0].GetProperty("max").GetDouble(), precision: 1);

        // Today's point: avg of 6.0 and 8.0 = 7.0
        Assert.Equal(7.0, pts[1].GetProperty("average").GetDouble(), precision: 1);
        Assert.Equal(6.0, pts[1].GetProperty("min").GetDouble(), precision: 1);
        Assert.Equal(8.0, pts[1].GetProperty("max").GetDouble(), precision: 1);
    }

    [Fact]
    public async Task GetScatterplot_DefaultFilterIsLast2Weeks()
    {
        var patient = await SeedPatientAsync("P_SCATTER_DEFAULT", "Scatter Default Patient");
        var now = DateTime.UtcNow;

        await using var db = CreateDb();
        // Old reading (beyond 2w) and a recent one (within 2w from latest)
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = now.AddDays(-20), GlucoseMmoll = 12.0 }, // excluded
            new Glucose { PatientId = patient.Id, Timestamp = now,              GlucoseMmoll = 6.0  }  // included
        );
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/scatterplot?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        // Only the recent reading should appear
        Assert.Equal(1, body.GetProperty("count").GetInt32());
        Assert.Equal(6.0, body.GetProperty("points")[0].GetProperty("average").GetDouble(), precision: 1);
    }

    [Fact]
    public async Task GetScatterplot_WithLastFilter_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_SCATTER_LAST", "Scatter Last Patient");
        var now = DateTime.UtcNow;

        await using var db = CreateDb();
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = now.AddDays(-20), GlucoseMmoll = 12.0 }, // outside 3d
            new Glucose { PatientId = patient.Id, Timestamp = now.AddDays(-2),  GlucoseMmoll = 5.0  }, // inside 3d
            new Glucose { PatientId = patient.Id, Timestamp = now,              GlucoseMmoll = 7.0  }  // inside 3d (latest)
        );
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/scatterplot?id={patient.Id}&last=3d");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        // 2 days within last 3d window
        Assert.Equal(2, body.GetProperty("count").GetInt32());
    }

    [Fact]
    public async Task GetScatterplot_WithStartEndFilter_FiltersCorrectly()
    {
        var patient = await SeedPatientAsync("P_SCATTER_SE", "Scatter StartEnd Patient");
        // Base off noon UTC to guarantee all generated offsets fall on the same calendar day
        var noon = DateTime.UtcNow.Date.AddHours(12);

        await using var db = CreateDb();
        db.Glucoses.AddRange(
            new Glucose { PatientId = patient.Id, Timestamp = noon.AddHours(-5), GlucoseMmoll = 12.0 }, // excluded
            new Glucose { PatientId = patient.Id, Timestamp = noon.AddHours(-2), GlucoseMmoll = 5.0  }, // included
            new Glucose { PatientId = patient.Id, Timestamp = noon.AddHours(-1), GlucoseMmoll = 7.0  }  // included
        );
        await db.SaveChangesAsync();

        var startStr = noon.AddHours(-3).ToString("O");
        var endStr   = noon.ToString("O");
        var resp = await _client.GetAsync($"/api/glucose/scatterplot?id={patient.Id}&start={startStr}&end={endStr}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        // Both within the window fall on the same day → 1 point, avg = 6.0
        Assert.Equal(1, body.GetProperty("count").GetInt32());
        Assert.Equal(6.0, body.GetProperty("points")[0].GetProperty("average").GetDouble(), precision: 1);
        Assert.Equal(5.0, body.GetProperty("points")[0].GetProperty("min").GetDouble(), precision: 1);
        Assert.Equal(7.0, body.GetProperty("points")[0].GetProperty("max").GetDouble(), precision: 1);
    }

    [Fact]
    public async Task GetScatterplot_NotFound_Returns404()
    {
        var resp = await _client.GetAsync("/api/glucose/scatterplot?id=99999");
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    [Fact]
    public async Task GetScatterplot_InvalidLastParam_Returns400()
    {
        var patient = await SeedPatientAsync("P_SCATTER_BAD", "Scatter Bad Param Patient");
        var resp = await _client.GetAsync($"/api/glucose/scatterplot?id={patient.Id}&last=5x");
        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
    }

    // ── Anomaly Detect ────────────────────────────────────────────────────────

    [Fact]
    public async Task Detect_PatientNotFound_Returns404()
    {
        var resp = await _client.PostAsync("/api/anomaly/detect?id=99999", null);
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    [Fact]
    public async Task Detect_WithNoData_ReturnsEmpty()
    {
        var patient = await SeedPatientAsync("P_DETECT_EMPTY", "Detect Empty Patient");
        var resp = await _client.PostAsync($"/api/anomaly/detect?id={patient.Id}", null);
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(0, body.GetProperty("count").GetInt32());
        Assert.Empty(body.GetProperty("anomalies").EnumerateArray());
    }

    [Fact]
    public async Task Detect_InvalidLastParam_Returns400()
    {
        var patient = await SeedPatientAsync("P_DETECT_BAD", "Detect Bad Param Patient");
        // Seed at least one glucose reading so we don't return early on "no data"
        await using (var db = CreateDb())
        {
            db.Glucoses.Add(new Glucose { PatientId = patient.Id, Timestamp = DateTime.UtcNow, GlucoseMmoll = 6.0 });
            await db.SaveChangesAsync();
        }

        var resp = await _client.PostAsync($"/api/anomaly/detect?id={patient.Id}&last=invalid", null);
        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
    }

    [Fact]
    public async Task Detect_RunsInferenceSuccessfully()
    {
        var patient = await SeedPatientAsync("P_DETECT_OK", "Detect OK Patient");
        var now = DateTime.UtcNow;

        // Seed data to populate build channel rows
        await using (var db = CreateDb())
        {
            db.Glucoses.AddRange(
                new Glucose { PatientId = patient.Id, Timestamp = now.AddMinutes(-30), GlucoseMmoll = 6.5 },
                new Glucose { PatientId = patient.Id, Timestamp = now.AddMinutes(-15), GlucoseMmoll = 7.0 }
            );
            db.Insulins.Add(new Insulin { PatientId = patient.Id, Timestamp = now.AddMinutes(-20), Units = 2.0f, EventType = "bolus" });
            db.Meals.Add(new Meal { PatientId = patient.Id, Timestamp = now.AddMinutes(-25), Carbs = 45.0f });
            await db.SaveChangesAsync();
        }

        var resp = await _client.PostAsync($"/api/anomaly/detect?id={patient.Id}", null);
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(1, body.GetProperty("count").GetInt32());

        var anomaly = body.GetProperty("anomalies")[0];
        Assert.Equal("missed_bolus", anomaly.GetProperty("anomaly_type").GetString());
        Assert.Equal("Mocked anomaly description", anomaly.GetProperty("description").GetString());
        Assert.Equal(3.5, anomaly.GetProperty("severity").GetDouble(), precision: 1);
        Assert.Equal(0.75, anomaly.GetProperty("confidence").GetDouble(), precision: 2); // 75.0 / 100.0

        // Verify it was saved to the database
        await using (var db = CreateDb())
        {
            var dbAnomaly = await db.Anomalies.SingleAsync(a => a.PatientId == patient.Id);
            Assert.Equal("missed_bolus", dbAnomaly.AnomalyType);
            Assert.Equal(3.5, dbAnomaly.Severity);
            Assert.Equal(0.75, dbAnomaly.Confidence);
            Assert.Equal("Mocked anomaly description", dbAnomaly.Description);
        }
    }
}
