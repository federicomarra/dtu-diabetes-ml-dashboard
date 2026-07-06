using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Xunit;

namespace DiabetesApi.Tests;

public class HealthTests(CustomWebApplicationFactory factory) : TestBase(factory)
{
    [Fact]
    public async Task HealthEndpoint_ReturnsStructuredResponse()
    {
        var resp = await Client.GetAsync("/api/health");

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
}
