using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using DiabetesApi.Models;
using Xunit;

namespace DiabetesApi.Tests;

public class MealTests(CustomWebApplicationFactory factory) : TestBase(factory)
{
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

        var resp = await Client.GetAsync($"/api/meal?id={patient.Id}");
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
        var respLast = await Client.GetAsync($"/api/meal?id={patient.Id}&last=2h");
        Assert.Equal(HttpStatusCode.OK, respLast.StatusCode);
        var bodyLast = await respLast.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyLast.GetProperty("count").GetInt32());
        var listLast = bodyLast.GetProperty("meals");
        Assert.Equal(30.0f, listLast[0].GetProperty("carbs").GetSingle());
        Assert.Equal(20.0f, listLast[1].GetProperty("carbs").GetSingle());

        // 2. Test start and end filter
        var startStr = now.AddHours(-2.5).ToString("O");
        var endStr = now.AddHours(-0.5).ToString("O");
        var respFilter = await Client.GetAsync($"/api/meal?id={patient.Id}&start={startStr}&end={endStr}");
        Assert.Equal(HttpStatusCode.OK, respFilter.StatusCode);
        var bodyFilter = await respFilter.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, bodyFilter.GetProperty("count").GetInt32());
    }

    [Fact]
    public async Task GetMeal_InvalidLastParam_Returns400()
    {
        var patient = await SeedPatientAsync("P_MEAL_BAD", "Meal Bad Param Patient");
        var resp = await Client.GetAsync($"/api/meal?id={patient.Id}&last=5x");
        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
    }
}
