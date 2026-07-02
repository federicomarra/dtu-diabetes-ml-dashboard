using System.Net.Http.Json;
using System.Text.Json;
using DiabetesApi.Data;

namespace DiabetesApi.Services;

/// <summary>
/// Thin HTTP client for the stateless ML inference microservice (ml/inference/service.py).
/// Sends a patient's assembled 3 channels (glucose/insulin/announced-carb) to $ML_URL/infer
/// and returns the detector-surfaced anomalies. This is only the transport: it does not read
/// or write the DB. The Anomaly controller calls it, then writes the results to `anomalies`.
/// </summary>
public class MlInferenceService(HttpClient http)
{
    // ML uses snake_case on the wire (see ml/docs/ML_INFERENCE_CONTRACT.md); match it both ways.
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
    };

    /// <summary>POST /infer. Returns the detected anomalies (already sorted strongest-first).</summary>
    public async Task<MlInferResponse?> InferAsync(MlInferRequest req, CancellationToken ct = default)
    {
        var resp = await http.PostAsJsonAsync("/infer", req, Json, ct);
        resp.EnsureSuccessStatusCode();
        return await resp.Content.ReadFromJsonAsync<MlInferResponse>(Json, ct);
    }

    /// <summary>GET /health — true once the model is loaded (503 'loading' during startup).</summary>
    public async Task<bool> IsHealthyAsync(CancellationToken ct = default)
    {
        try
        {
            var resp = await http.GetAsync("/health", ct);
            return resp.IsSuccessStatusCode;
        }
        catch (HttpRequestException)
        {
            return false;
        }
    }
}
