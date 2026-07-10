using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using System.Net;
using System.Net.Http.Json;
using System.Threading;
using System.Threading.Tasks;
using DiabetesApi.Data;
using DiabetesApi.Services;

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

        builder.ConfigureServices(services =>
        {
            // Intercept any outbound HTTP calls to the ML service to prevent network
            // noise, socket timeouts, and error traces in CI logs.
            services.RemoveAll<MlInferenceService>();
            services.AddScoped<MlInferenceService>(sp =>
            {
                var client = new HttpClient(new FakeMlHttpMessageHandler())
                {
                    BaseAddress = new Uri("http://mock-ml-service/")
                };
                return new MlInferenceService(client);
            });
        });
    }

    private class FakeMlHttpMessageHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (request.RequestUri?.PathAndQuery == "/health")
            {
                var content = JsonContent.Create(new
                {
                    status = "ok",
                    detector = "mock_detector_best.pt",
                    device = "cpu"
                });
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = content });
            }

            if (request.RequestUri?.PathAndQuery == "/infer")
            {
                var content = JsonContent.Create(new
                {
                    patient_id = 1,
                    n_windows = 1,
                    anomalies = new[]
                    {
                        new {
                            start = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                            end = DateTime.UtcNow.AddMinutes(30).ToString("yyyy-MM-ddTHH:mm:ssZ"),
                            start_minute = 0,
                            duration_min = 30,
                            anomaly_type = "missed_bolus",
                            description = "Mocked anomaly description",
                            rule_confirmed = true,
                            severity = 7.0,
                            anomaly_strength = 75.0,
                            score = 1.2
                        },
                        // Below the 6σ persist floor — detect must drop this one.
                        new {
                            start = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                            end = DateTime.UtcNow.AddMinutes(30).ToString("yyyy-MM-ddTHH:mm:ssZ"),
                            start_minute = 0,
                            duration_min = 30,
                            anomaly_type = "late_bolus",
                            description = "Sub-threshold anomaly",
                            rule_confirmed = true,
                            severity = 4.0,
                            anomaly_strength = 50.0,
                            score = 0.8
                        }
                    }
                });
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = content });
            }

            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
        }
    }
}
