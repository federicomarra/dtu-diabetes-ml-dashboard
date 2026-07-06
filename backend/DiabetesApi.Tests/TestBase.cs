using System.Net.Http;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using DiabetesApi.Data;
using DiabetesApi.Models;
using Xunit;

namespace DiabetesApi.Tests;

public class TestBase : IClassFixture<CustomWebApplicationFactory>
{
    protected readonly HttpClient Client;
    protected readonly IServiceProvider Services;

    protected static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
    };

    public TestBase(CustomWebApplicationFactory factory)
    {
        Services = factory.Services;
        Client   = factory.CreateClient();
    }

    protected AppDbContext CreateDb()
    {
        var scope = Services.CreateScope();
        return scope.ServiceProvider.GetRequiredService<AppDbContext>();
    }

    protected async Task<Patient> SeedPatientAsync(string externalId, string name)
    {
        await using var db = CreateDb();
        var existing = await db.Patients.FirstOrDefaultAsync(p => p.ExternalId == externalId);
        if (existing is not null) return existing;

        var patient = new Patient { ExternalId = externalId, Name = name };
        db.Patients.Add(patient);
        await db.SaveChangesAsync();
        return patient;
    }
}
