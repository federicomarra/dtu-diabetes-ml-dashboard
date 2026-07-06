using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using DiabetesApi.Models;
using Xunit;

namespace DiabetesApi.Tests;

public class InsulinTests(CustomWebApplicationFactory factory) : TestBase(factory)
{
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

        var resp = await Client.GetAsync($"/api/insulin?id={patient.Id}");
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
        var respLast = await Client.GetAsync($"/api/insulin?id={patient.Id}&last=2h");
        Assert.Equal(HttpStatusCode.OK, respLast.StatusCode);
        var bodyLast = await respLast.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyLast.GetProperty("count").GetInt32());
        var listLast = bodyLast.GetProperty("insulins");
        Assert.Equal(3.0f, listLast[0].GetProperty("units").GetSingle());
        Assert.Equal(2.0f, listLast[1].GetProperty("units").GetSingle());

        // 2. Test start and end filter
        var startStr = now.AddHours(-2.5).ToString("O");
        var endStr = now.AddHours(-0.5).ToString("O");
        var respFilter = await Client.GetAsync($"/api/insulin?id={patient.Id}&start={startStr}&end={endStr}");
        Assert.Equal(HttpStatusCode.OK, respFilter.StatusCode);
        var bodyFilter = await respFilter.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyFilter.GetProperty("count").GetInt32());
    }

    [Fact]
    public async Task GetInsulin_InvalidLastParam_Returns400()
    {
        var patient = await SeedPatientAsync("P_INSULIN_BAD", "Insulin Bad Param Patient");
        var resp = await Client.GetAsync($"/api/insulin?id={patient.Id}&last=5x");
        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
    }
}
