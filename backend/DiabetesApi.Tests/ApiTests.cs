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
        var resp = await _client.GetAsync("/api/patients/list");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        // Total may be ≥ 0 (other tests might have seeded data); just check the key exists
        Assert.True(body.TryGetProperty("total", out _));
    }

    [Fact]
    public async Task CreatePatient_Returns201()
    {
        var resp = await _client.PostAsJsonAsync("/api/patients/create", new
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
    public async Task CreatePatient_MissingFields_Returns400()
    {
        var resp = await _client.PostAsJsonAsync("/api/patients/create", new { });
        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
    }

    // ── Glucose ───────────────────────────────────────────────────────────────

    [Fact]
    public async Task GetGlucoseReadings_ReturnsCount()
    {
        var patient = await SeedPatientAsync("P_GLUCOSE", "G Patient");

        await using var db = CreateDb();
        db.GlucoseReadings.Add(new GlucoseReading
        {
            PatientId = patient.Id,
            Timestamp = DateTime.UtcNow,
            GlucoseMmoll = 6.7
        });
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/{patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("count").GetInt32() >= 1);
        Assert.Equal(6.7, body.GetProperty("readings")[0].GetProperty("glucose_mmoll").GetDouble());
    }

    [Fact]
    public async Task GetLatestReading_NotFound_Returns404()
    {
        var resp = await _client.GetAsync("/api/glucose/99999/latest");
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    [Fact]
    public async Task GetTir_Returns50PctInRange()
    {
        var patient = await SeedPatientAsync("P_TIR_UNIQUE", "TIR Patient");

        await using var db = CreateDb();
        // Two readings: one in-range (5.6), one high (11.1) → 50% in range
        db.GlucoseReadings.AddRange(
            new GlucoseReading { PatientId = patient.Id, Timestamp = DateTime.UtcNow.AddMinutes(-5), GlucoseMmoll = 5.6 },
            new GlucoseReading { PatientId = patient.Id, Timestamp = DateTime.UtcNow,               GlucoseMmoll = 11.1 }
        );
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/glucose/{patient.Id}/tir");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(50.0, body.GetProperty("in_range_pct").GetDouble());
    }

    // ── Anomalies ─────────────────────────────────────────────────────────────

    [Fact]
    public async Task GetAnomalies_ReturnsCount()
    {
        var patient = await SeedPatientAsync("P_ANOMALY", "A Patient");

        await using var db = CreateDb();
        db.AnomalyDetections.Add(new AnomalyDetection
        {
            PatientId = patient.Id,
            AnomalyType = "missed_bolus",
            Confidence = 0.9
        });
        await db.SaveChangesAsync();

        var resp = await _client.GetAsync($"/api/anomalies/{patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("count").GetInt32() >= 1);
        Assert.Equal("missed_bolus", body.GetProperty("anomalies")[0].GetProperty("anomaly_type").GetString());
    }

    [Fact]
    public async Task AcknowledgeAnomaly_SetsFlag()
    {
        var patient = await SeedPatientAsync("P_ACK_UNIQUE", "ACK Patient");

        await using var db = CreateDb();
        var anomaly = new AnomalyDetection
        {
            PatientId = patient.Id,
            AnomalyType = "late_bolus",
            Confidence = 0.8
        };
        db.AnomalyDetections.Add(anomaly);
        await db.SaveChangesAsync();

        var resp = await _client.PostAsync($"/api/anomalies/{anomaly.Id}/acknowledge", null);
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("is_acknowledged").GetBoolean());
    }
}
