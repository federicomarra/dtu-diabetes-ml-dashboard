using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.Services;

namespace DiabetesApi.Routes;

/// <summary>Full-stack health check — backend, database, and ML service.</summary>
[ApiController]
[Route("api")]
public class Health(AppDbContext db, MlInferenceService ml) : ControllerBase
{
    /// <summary>
    /// Returns the health status of every stack component.
    /// </summary>
    /// <remarks>
    /// Probes each component independently:
    /// - **backend**: always healthy if this endpoint responds.
    /// - **database**: calls <c>CanConnectAsync</c> to verify Postgres is reachable.
    /// - **ml_service**: calls the ML container's `/health` endpoint and surfaces
    ///   the model name and compute device it reports.
    ///
    /// Returns **200 OK** when all components are healthy, **503 Service Unavailable**
    /// when at least one component is degraded.
    /// </remarks>
    [HttpGet("health")]
    [ProducesResponseType(typeof(HealthResponse), StatusCodes.Status200OK)]
    [ProducesResponseType(typeof(HealthResponse), StatusCodes.Status503ServiceUnavailable)]
    public async Task<IActionResult> GetHealth(CancellationToken ct = default)
    {
        // ── Database probe ────────────────────────────────────────────────────
        string dbStatus;
        try
        {
            var canConnect = await db.Database.CanConnectAsync(ct);
            dbStatus = canConnect ? "healthy" : "unhealthy";
        }
        catch (Exception)
        {
            dbStatus = "unhealthy";
        }

        // ── ML service probe ──────────────────────────────────────────────────
        string mlStatus;
        string? mlDetector = null;
        string? mlDevice   = null;
        try
        {
            var mlHealthy = await ml.IsHealthyAsync(ct);
            mlStatus = mlHealthy ? "healthy" : "loading";
            if (mlHealthy)
            {
                var detail = await ml.GetHealthDetailAsync(ct);
                mlDetector = detail?.Detector;
                mlDevice   = detail?.Device;
            }
        }
        catch (Exception)
        {
            mlStatus = "unhealthy";
        }

        // ── Assemble response ─────────────────────────────────────────────────
        bool allHealthy = dbStatus == "healthy" && mlStatus == "healthy";
        var response = new HealthResponse(
            Status: allHealthy ? "healthy" : "unhealthy",
            Components: new Components(
                Backend:   new ComponentStatus("healthy"),
                Database:  new ComponentStatus(dbStatus),
                MlService: new MlComponentStatus(mlStatus, mlDetector, mlDevice)
            )
        );

        return allHealthy ? Ok(response) : StatusCode(StatusCodes.Status503ServiceUnavailable, response);
    }

    // ── DTOs ──────────────────────────────────────────────────────────────────
    private record HealthResponse(string Status, Components Components);
    private record Components(ComponentStatus Backend, ComponentStatus Database, MlComponentStatus MlService);
    private record ComponentStatus(string Status);
    private record MlComponentStatus(string Status, string? Detector, string? Device) : ComponentStatus(Status);
}
