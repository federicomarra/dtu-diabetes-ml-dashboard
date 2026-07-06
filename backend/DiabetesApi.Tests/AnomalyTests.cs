using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Models;
using Xunit;

namespace DiabetesApi.Tests;

public class AnomalyTests(CustomWebApplicationFactory factory) : TestBase(factory)
{
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

        var resp = await Client.GetAsync($"/api/anomaly?id={patient.Id}");
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
        var resp = await Client.GetAsync($"/api/anomaly?id={patient.Id}");
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

        var resp = await Client.PostAsync($"/api/anomaly/acknowledge?patientId={patient.Id}&anomalyId={anomaly.Id}", null);
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body.GetProperty("is_acknowledged").GetBoolean());
    }

    [Fact]
    public async Task AcknowledgeAnomaly_NotFound_Returns404()
    {
        var patient = await SeedPatientAsync("P_ACK_NF", "ACK NF Patient");
        var resp = await Client.PostAsync($"/api/anomaly/acknowledge?patientId={patient.Id}&anomalyId=99999", null);
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
        var resp = await Client.PostAsync($"/api/anomaly/acknowledge?patientId={patient2.Id}&anomalyId={anomaly.Id}", null);
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    [Fact]
    public async Task Detect_PatientNotFound_Returns404()
    {
        var resp = await Client.PostAsync("/api/anomaly/detect?id=99999", null);
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    [Fact]
    public async Task Detect_WithNoData_ReturnsEmpty()
    {
        var patient = await SeedPatientAsync("P_DETECT_EMPTY", "Detect Empty Patient");
        var resp = await Client.PostAsync($"/api/anomaly/detect?id={patient.Id}", null);
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

        var resp = await Client.PostAsync($"/api/anomaly/detect?id={patient.Id}&last=invalid", null);
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

        var resp = await Client.PostAsync($"/api/anomaly/detect?id={patient.Id}", null);
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
