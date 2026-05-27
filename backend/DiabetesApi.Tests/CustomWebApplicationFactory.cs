using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using DiabetesApi.Data;

namespace DiabetesApi.Tests;

/// <summary>
/// Shared test server factory. Sets the USE_INMEMORY_DB environment variable
/// so that Program.cs registers the InMemory provider instead of Npgsql.
/// </summary>
public class CustomWebApplicationFactory : WebApplicationFactory<Program>
{
    // Shared DB name so all test instances within the class share state
    public static readonly string DbName = "DiabetesTestDb_" + Guid.NewGuid();

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Testing");

        // Tell Program.cs to use InMemory (checked before AddDbContext)
        builder.UseSetting("USE_INMEMORY_DB", "true");
        builder.UseSetting("INMEMORY_DB_NAME", DbName);
    }
}
