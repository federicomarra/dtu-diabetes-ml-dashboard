using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Xunit;
using Parquet.Serialization;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;

namespace DiabetesApi.Tests;

public class DoctorTests(CustomWebApplicationFactory factory) : TestBase(factory)
{
    private class ParquetRow
    {
        public string? patient_id { get; set; }
        public double? patient_age_years { get; set; }
        public long? day { get; set; }
        public long? minute { get; set; }
        public long? absolute_minute { get; set; }
        public double? blood_glucose { get; set; }
        public double? cho_mg_min { get; set; }
        public double? cho_mg_announced { get; set; }
        public double? insulin_mU_min { get; set; }
    }

    [Fact]
    public async Task UploadParquet_SuccessfulImport()
    {
        // 1. Create a dummy Parquet file in-memory
        var mockRows = new List<ParquetRow>
        {
            new ParquetRow
            {
                patient_id = "999999",
                patient_age_years = 40.0,
                day = 2,
                minute = 360,
                absolute_minute = 360,
                blood_glucose = 6.5,
                cho_mg_min = 12000.0, // 12g
                cho_mg_announced = 12000.0,
                insulin_mU_min = 150.0 // bolus (>100)
            },
            new ParquetRow
            {
                patient_id = "999999",
                patient_age_years = 40.0,
                day = 2,
                minute = 361,
                absolute_minute = 361,
                blood_glucose = 6.7,
                cho_mg_min = 0,
                cho_mg_announced = 0,
                insulin_mU_min = 50.0 // basal (<=100)
            }
        };

        using var ms = new MemoryStream();
        await ParquetSerializer.SerializeAsync(mockRows, ms);
        var bytes = ms.ToArray();

        // 2. Prepare multipart form upload request
        using var content = new MultipartFormDataContent();
        var fileContent = new ByteArrayContent(bytes);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        content.Add(fileContent, "file", "test.parquet");

        // 3. Post to api/doctor/upload-parquet
        var resp = await Client.PostAsync("/api/doctor/upload-parquet", content);
        if (resp.StatusCode != HttpStatusCode.OK)
        {
            var errStr = await resp.Content.ReadAsStringAsync();
            throw new Exception($"Request failed with status {resp.StatusCode}: {errStr}");
        }
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal("Parquet simulation imported successfully", body.GetProperty("message").GetString());
        Assert.Equal(1, body.GetProperty("patients_count").GetInt32());
        Assert.Equal(2, body.GetProperty("glucose_count").GetInt32());
        Assert.Equal(1, body.GetProperty("meal_count").GetInt32());
        Assert.True(body.GetProperty("insulin_count").GetInt32() >= 2);

        // 4. Verify database entities were correctly inserted and mapped
        using var db = CreateDb();
        var patient = await db.Patients
            .Include(p => p.Glucoses)
            .Include(p => p.Meals)
            .Include(p => p.Insulins)
            .Include(p => p.Histories)
            .FirstOrDefaultAsync(p => p.ExternalId == "SIM_999999");

        Assert.NotNull(patient);
        Assert.Equal("Simulated patient 999999", patient.Name);
        Assert.Equal(2, patient.Glucoses.Count);
        Assert.Single(patient.Meals);
        Assert.True(patient.Insulins.Count >= 2);
        
        // Check histories table synced
        Assert.True(patient.Histories.Count > 0);
    }
}
