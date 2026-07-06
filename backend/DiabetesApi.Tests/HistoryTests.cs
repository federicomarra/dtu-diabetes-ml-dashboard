using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using DiabetesApi.Models;
using Xunit;

namespace DiabetesApi.Tests;

public class HistoryTests(CustomWebApplicationFactory factory) : TestBase(factory)
{
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

        var resp = await Client.GetAsync($"/api/history?id={patient.Id}");
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
        var respLast = await Client.GetAsync($"/api/history?id={patient.Id}&last=2h");
        Assert.Equal(HttpStatusCode.OK, respLast.StatusCode);
        var bodyLast = await respLast.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyLast.GetProperty("count").GetInt32());
        var listLast = bodyLast.GetProperty("histories");
        Assert.Equal(7.0f, listLast[0].GetProperty("glucose").GetSingle());
        Assert.Equal(6.0f, listLast[1].GetProperty("glucose").GetSingle());

        // 2. Test start and end filter
        var startStr = now.AddHours(-2.5).ToString("O");
        var endStr = now.AddHours(-0.5).ToString("O");
        var respFilter = await Client.GetAsync($"/api/history?id={patient.Id}&start={startStr}&end={endStr}");
        Assert.Equal(HttpStatusCode.OK, respFilter.StatusCode);
        var bodyFilter = await respFilter.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyFilter.GetProperty("count").GetInt32());
    }

    [Fact]
    public async Task GetHistory_InvalidLastParam_Returns400()
    {
        var patient = await SeedPatientAsync("P_HISTORY_BAD", "History Bad Param Patient");
        var resp = await Client.GetAsync($"/api/history?id={patient.Id}&last=5x");
        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
    }
}
