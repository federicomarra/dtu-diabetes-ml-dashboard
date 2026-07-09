using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Xunit;

namespace DiabetesApi.Tests;

public class PatientTests(CustomWebApplicationFactory factory) : TestBase(factory)
{
    [Fact]
    public async Task ListPatients_ReturnsEmpty()
    {
        var resp = await Client.GetAsync("/api/patient/list");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        // Total may be ≥ 0 (other tests might have seeded data); just check the key exists
        Assert.True(body.TryGetProperty("total", out _));
    }

    [Fact]
    public async Task ListPatients_WithPagination_ReturnsCorrectItems()
    {
        var p1 = await SeedPatientAsync("P_LIST_PAG_1", "Patient 1");
        var p2 = await SeedPatientAsync("P_LIST_PAG_2", "Patient 2");
        var p3 = await SeedPatientAsync("P_LIST_PAG_3", "Patient 3");

        var resp = await Client.GetAsync("/api/patient/list?page=1&perPage=2");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal(2, body.GetProperty("patients").GetArrayLength());
        
        var respPage2 = await Client.GetAsync("/api/patient/list?page=2&perPage=2");
        Assert.Equal(HttpStatusCode.OK, respPage2.StatusCode);
        
        var body2 = await respPage2.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.True(body2.GetProperty("patients").GetArrayLength() >= 1);
    }

    [Fact]
    public async Task CreatePatient_Returns201()
    {
        var resp = await Client.PostAsJsonAsync("/api/patient/create", new
        {
            external_id = "P001_CREATE",
            name = "Test Patient"
        });
        Assert.Equal(HttpStatusCode.Created, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal("P001_CREATE", body.GetProperty("external_id").GetString());
        Assert.Equal("Test Patient", body.GetProperty("name").GetString());
    }

    [Fact]
    public async Task CreatePatient_WithDateOfBirth_ReturnsAge()
    {
        var birthDate = DateOnly.FromDateTime(DateTime.UtcNow).AddYears(-30);
        var resp = await Client.PostAsJsonAsync("/api/patient/create", new
        {
            external_id = "P002_AGE_TEST",
            name = "Age Test Patient",
            date_of_birth = birthDate.ToString("yyyy-MM-dd")
        });
        Assert.Equal(HttpStatusCode.Created, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal("P002_AGE_TEST", body.GetProperty("external_id").GetString());
        Assert.Equal(30, body.GetProperty("age").GetInt32());
        Assert.False(body.TryGetProperty("date_of_birth", out _));
    }

    [Fact]
    public async Task CreatePatient_MissingFields_Returns400()
    {
        var resp = await Client.PostAsJsonAsync("/api/patient/create", new { });
        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
    }

    [Fact]
    public async Task CreatePatient_DuplicateExternalId_Returns409()
    {
        var body = new { external_id = "P003_DUPLICATE", name = "First" };

        var first = await Client.PostAsJsonAsync("/api/patient/create", body);
        Assert.Equal(HttpStatusCode.Created, first.StatusCode);

        // Without an existence check this hits the unique index and surfaces as a raw
        // 500 DbUpdateException, which the frontend cannot render.
        var second = await Client.PostAsJsonAsync("/api/patient/create", body);
        Assert.Equal(HttpStatusCode.Conflict, second.StatusCode);

        var err = await second.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Contains("already exists", err.GetProperty("error").GetString()!);
    }

    [Fact]
    public async Task GetPatient_ReturnsPatient()
    {
        var patient = await SeedPatientAsync("P_GET_TEST", "Get Test Patient");

        var resp = await Client.GetAsync($"/api/patient?id={patient.Id}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal("P_GET_TEST", body.GetProperty("external_id").GetString());
        Assert.Equal("Get Test Patient", body.GetProperty("name").GetString());
    }

    [Fact]
    public async Task GetPatient_NotFound_Returns404()
    {
        var resp = await Client.GetAsync("/api/patient?id=99999");
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    [Fact]
    public async Task GetPatientByExternalId_ReturnsPatient()
    {
        var patient = await SeedPatientAsync("P_BY_EXT_TEST", "External Test Patient");

        var resp = await Client.GetAsync($"/api/patient?ext_id={patient.ExternalId}");
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal("P_BY_EXT_TEST", body.GetProperty("external_id").GetString());
        Assert.Equal("External Test Patient", body.GetProperty("name").GetString());
    }

    [Fact]
    public async Task GetPatientByExternalId_NotFound_Returns404()
    {
        var resp = await Client.GetAsync("/api/patient?ext_id=NONEXISTENT");
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    [Fact]
    public async Task GetPatient_MissingParams_Returns400()
    {
        var resp = await Client.GetAsync("/api/patient");
        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
    }

    [Fact]
    public async Task UploadCsv_SuccessfullyImports()
    {
        var patient = await SeedPatientAsync("P_UPLOAD_CSV", "CSV Upload Patient");

        var csvContent = "Device Timestamp,Record Type,Historic Glucose mmol/L,Scan Glucose mmol/L,Rapid-Acting Insulin (units),Long-Acting Insulin Value (units),Carbohydrates (grams)\n" +
                         "06-07-2026 12:00,0,6.5,,,,,\n" +
                         "06-07-2026 12:15,5,,,,,45\n" +
                         "06-07-2026 12:30,1,,7.2,,,,\n" +
                         "06-07-2026 12:45,4,,,2.5,,,\n" +
                         "06-07-2026 13:00,4,,,,1.5,,\n";

        using var content = new MultipartFormDataContent();
        var fileContent = new ByteArrayContent(System.Text.Encoding.UTF8.GetBytes(csvContent));
        fileContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("text/csv");
        content.Add(fileContent, "file", "test.csv");

        var resp = await Client.PostAsync($"/api/patient/upload-libre-csv?id={patient.Id}", content);
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal("CSV imported successfully", body.GetProperty("message").GetString());
        Assert.Equal(2, body.GetProperty("glucose_count").GetInt32());
        Assert.Equal(1, body.GetProperty("meal_count").GetInt32());
        Assert.Equal(2, body.GetProperty("insulin_count").GetInt32());

        // Verify Histories are populated
        using var db = CreateDb();
        var histories = await db.Histories
            .Where(h => h.PatientId == patient.Id)
            .OrderBy(h => h.Timestamp)
            .ToListAsync();

        Assert.Equal(5, histories.Count);
        Assert.Equal(6.5f, histories[0].Glucose);
        Assert.Equal(45f, histories[1].Meal);
        Assert.Equal(7.2f, histories[2].Glucose);
        Assert.Equal(2.5f, histories[3].Insulin);
        Assert.Equal(1.5f, histories[4].Insulin);
    }

    [Fact]
    public async Task UploadCsv_EmptyFile_Returns400()
    {
        var patient = await SeedPatientAsync("P_UPLOAD_EMPTY", "CSV Empty Patient");

        using var content = new MultipartFormDataContent();
        var fileContent = new ByteArrayContent([]);
        fileContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("text/csv");
        content.Add(fileContent, "file", "empty.csv");

        var resp = await Client.PostAsync($"/api/patient/upload-libre-csv?id={patient.Id}", content);
        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
    }

    [Fact]
    public async Task UploadCsv_PatientNotFound_Returns404()
    {
        using var content = new MultipartFormDataContent();
        var fileContent = new ByteArrayContent(System.Text.Encoding.UTF8.GetBytes("header\ndata"));
        fileContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("text/csv");
        content.Add(fileContent, "file", "test.csv");

        var resp = await Client.PostAsync("/api/patient/upload-libre-csv?id=99999", content);
        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    [Fact]
    public async Task UploadGlookoZip_SuccessfullyImports()
    {
        var patient = await SeedPatientAsync("P_UPLOAD_ZIP", "ZIP Upload Patient");

        using var zipMs = new System.IO.MemoryStream();
        using (var archive = new System.IO.Compression.ZipArchive(zipMs, System.IO.Compression.ZipArchiveMode.Create, true))
        {
            var cgmEntry = archive.CreateEntry("cgm_data_1.csv");
            using (var writer = new System.IO.StreamWriter(cgmEntry.Open()))
            {
                writer.WriteLine("Data e ora,Valore glicemia CGM (mmol/l)");
                writer.WriteLine("06/07/2026 12:00,6.5");
            }

            var bgEntry = archive.CreateEntry("bg_data_1.csv");
            using (var writer = new System.IO.StreamWriter(bgEntry.Open()))
            {
                writer.WriteLine("Data e ora,Valore glucosio (mmol/l)");
                writer.WriteLine("06/07/2026 12:10,7.0");
            }

            var basalEntry = archive.CreateEntry("Insulin data/basal_data_1.csv");
            using (var writer = new System.IO.StreamWriter(basalEntry.Open()))
            {
                writer.WriteLine("Data e ora,Frequenza");
                writer.WriteLine("06/07/2026 12:15,1.2");
            }

            var bolusEntry = archive.CreateEntry("Insulin data/bolus_data_1.csv");
            using (var writer = new System.IO.StreamWriter(bolusEntry.Open()))
            {
                writer.WriteLine("Data e ora,Insulina erogata (U),Consumo di carboidrati (g)");
                writer.WriteLine("06/07/2026 12:20,5.5,45");
            }
        }
        zipMs.Position = 0;

        using var content = new MultipartFormDataContent();
        var fileContent = new ByteArrayContent(zipMs.ToArray());
        fileContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/zip");
        content.Add(fileContent, "file", "export.zip");

        var resp = await Client.PostAsync($"/api/patient/upload-glooko-zip?id={patient.Id}", content);
        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);

        var body = await resp.Content.ReadFromJsonAsync<JsonElement>(JsonOpts);
        Assert.Equal("Glooko ZIP imported successfully", body.GetProperty("message").GetString());
        Assert.Equal(2, body.GetProperty("glucose_count").GetInt32());
        Assert.Equal(1, body.GetProperty("meal_count").GetInt32());
        Assert.Equal(2, body.GetProperty("insulin_count").GetInt32());

        // Verify Histories are populated
        using var db = CreateDb();
        var histories = await db.Histories
            .Where(h => h.PatientId == patient.Id)
            .OrderBy(h => h.Timestamp)
            .ToListAsync();

        Assert.Equal(4, histories.Count);
        Assert.Equal(6.5f, histories[0].Glucose);
        Assert.Equal(7.0f, histories[1].Glucose);
        Assert.Equal(1.2f, histories[2].Insulin);
        Assert.Equal(5.5f, histories[3].Insulin);
        Assert.Equal(45f, histories[3].Meal);
    }
}
