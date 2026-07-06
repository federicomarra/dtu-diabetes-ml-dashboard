using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ModelBinding;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.Models;
using DiabetesApi.Services;
using Microsoft.AspNetCore.Http;
using System.Globalization;

namespace DiabetesApi.Routes;

/// <summary>Patient management endpoints.</summary>
[ApiController]
[Route("api/patient")]
[Produces("application/json")]
public class Patient(AppDbContext db, PatientService patientService) : ControllerBase
{
    /// <summary>List all patients with optional pagination.</summary>
    /// <param name="page">Page number (default 1).</param>
    /// <param name="perPage">Items per page (default 20).</param>
    [HttpGet("list")]
    [ProducesResponseType(typeof(PaginatedPatientsResponse), StatusCodes.Status200OK)]
    public async Task<IActionResult> ListPatients(
        [FromQuery] int page = 1,
        [FromQuery] int perPage = 20)
    {
        var query = db.Patients.OrderByDescending(p => p.CreatedAt);
        int total = await query.CountAsync();
        int pages = (int)Math.Ceiling(total / (double)perPage);

        var items = await query
            .Skip((page - 1) * perPage)
            .Take(perPage)
            .ToListAsync();

        return Ok(new PaginatedPatientsResponse(
            items.Select(ToDto),
            total,
            page,
            pages
        ));
    }

    /// <summary>Get a single patient by ID or external ID.</summary>
    /// <param name="id">Internal patient database ID.</param>
    /// <param name="ext_id">External patient identifier string.</param>
    [HttpGet]
    [ProducesResponseType(typeof(PatientDto), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> GetPatient(
        [FromQuery] int? id = null,
        [FromQuery(Name = "ext_id")] string? ext_id = null)
    {
        if (id is null && string.IsNullOrWhiteSpace(ext_id))
        {
            return BadRequest(new { error = "Either id or ext_id query parameter must be provided." });
        }

        Models.Patient? patient = null;
        if (id is not null)
        {
            patient = await db.Patients.FindAsync(id.Value);
        }
        else
        {
            patient = await db.Patients.FirstOrDefaultAsync(p => p.ExternalId == ext_id);
        }

        if (patient is null) return NotFound();
        return Ok(ToDto(patient));
    }

    /// <summary>Create a new patient. Requires external_id and name.</summary>
    [HttpPost("create")]
    [ProducesResponseType(typeof(PatientDto), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> CreatePatient([FromBody] CreatePatientRequest req)
    {
        if (string.IsNullOrWhiteSpace(req.ExternalId) || string.IsNullOrWhiteSpace(req.Name))
            return BadRequest(new { error = "external_id and name are required" });

        var patient = new Models.Patient
        {
            ExternalId   = req.ExternalId,
            Name         = req.Name,
            DateOfBirth  = req.DateOfBirth  is not null ? DateOnly.Parse(req.DateOfBirth)  : null,
        };

        db.Patients.Add(patient);
        await db.SaveChangesAsync();

        return CreatedAtAction(nameof(GetPatient), new { id = patient.Id }, ToDto(patient));
    }

    /// <summary>Upload glucose, insulin, and carb data from LibreView CSV.</summary>
    /// <param name="id">Patient database ID.</param>
    /// <param name="file">Libre CSV file to upload.</param>
    [HttpPost("upload-libre-csv")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> UploadCsv(
        [BindRequired, FromQuery] int id,
        IFormFile file)
    {
        int patientId = id;
        if (file == null || file.Length == 0)
            return BadRequest(new { error = "No file uploaded or file is empty" });

        var patient = await db.Patients.FindAsync(patientId);
        if (patient is null) return NotFound(new { error = "Patient not found" });

        try
        {
            using var reader = new StreamReader(file.OpenReadStream());
            string? headerLine = null;
            string? line;
            while ((line = await reader.ReadLineAsync()) != null)
            {
                if (string.IsNullOrWhiteSpace(line)) continue;
                if (line.StartsWith("Glucose Data")) continue; // Skip metadata header line
                headerLine = line;
                break;
            }

            if (headerLine == null)
                return BadRequest(new { error = "CSV is empty or missing header" });

            char delimiter = ',';
            if (headerLine.Contains(';') && !headerLine.Contains(','))
            {
                delimiter = ';';
            }

            var headers = ParseCsvLine(headerLine, delimiter);
            int timestampIdx = headers.IndexOf("Device Timestamp");
            int recordTypeIdx = headers.IndexOf("Record Type");
            int historicGlucoseIdx = headers.IndexOf("Historic Glucose mmol/L");
            int scanGlucoseIdx = headers.IndexOf("Scan Glucose mmol/L");
            int rapidInsulinIdx = headers.IndexOf("Rapid-Acting Insulin (units)");
            int longInsulinIdx = headers.IndexOf("Long-Acting Insulin Value (units)");
            int carbsIdx = headers.IndexOf("Carbohydrates (grams)");

            if (timestampIdx == -1 || recordTypeIdx == -1)
            {
                return BadRequest(new { error = "Required columns 'Device Timestamp' or 'Record Type' not found in CSV headers." });
            }

            // Fetch existing data to avoid duplicates (N+1 queries prevention)
            var existingGlucoseTimestamps = await db.Glucoses
                .Where(g => g.PatientId == patientId)
                .Select(g => g.Timestamp)
                .ToHashSetAsync();

            var existingMealTimestamps = await db.Meals
                .Where(m => m.PatientId == patientId)
                .Select(m => m.Timestamp)
                .ToHashSetAsync();

            var existingInsulinTimestamps = await db.Insulins
                .Where(i => i.PatientId == patientId)
                .Select(i => i.Timestamp)
                .ToHashSetAsync();

            var glucosesToInsert = new List<Glucose>();
            var mealsToInsert = new List<Models.Meal>();
            var insulinsToInsert = new List<Models.Insulin>();

            string[] formats = {
                "dd-MM-yyyy HH:mm",
                "dd-MM-yyyy HH:mm:ss",
                "yyyy-MM-dd HH:mm:ss",
                "yyyy-MM-dd HH:mm",
                "yyyy-MM-ddTHH:mm:ss",
                "dd/MM/yyyy HH:mm",
                "dd/MM/yyyy HH:mm:ss"
            };

            while ((line = await reader.ReadLineAsync()) != null)
            {
                if (string.IsNullOrWhiteSpace(line)) continue;

                var row = ParseCsvLine(line, delimiter);
                if (row.Count <= timestampIdx || row.Count <= recordTypeIdx) continue;

                string timestampStr = row[timestampIdx];
                if (string.IsNullOrWhiteSpace(timestampStr)) continue;

                if (!DateTime.TryParseExact(timestampStr, formats, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out DateTime parsedTime))
                {
                    if (!DateTime.TryParse(timestampStr, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out parsedTime))
                    {
                        continue; // skip unparseable timestamps
                    }
                }

                DateTime timestampUtc = DateTime.SpecifyKind(parsedTime, DateTimeKind.Utc);

                if (!int.TryParse(row[recordTypeIdx], out int recordType)) continue;

                // 1. Parse Glucose
                double glucoseVal = 0;
                bool hasGlucose = false;
                if (recordType == 0 && historicGlucoseIdx != -1 && historicGlucoseIdx < row.Count && double.TryParse(row[historicGlucoseIdx], NumberStyles.Any, CultureInfo.InvariantCulture, out glucoseVal))
                {
                    hasGlucose = true;
                }
                else if (recordType == 1 && scanGlucoseIdx != -1 && scanGlucoseIdx < row.Count && double.TryParse(row[scanGlucoseIdx], NumberStyles.Any, CultureInfo.InvariantCulture, out glucoseVal))
                {
                    hasGlucose = true;
                }

                if (hasGlucose && !existingGlucoseTimestamps.Contains(timestampUtc))
                {
                    string status = "in_range";
                    if (glucoseVal < 3.0) status = "very_low";
                    else if (glucoseVal < 3.9) status = "low";
                    else if (glucoseVal > 13.9) status = "very_high";
                    else if (glucoseVal > 10.0) status = "high";

                    glucosesToInsert.Add(new Glucose
                    {
                        PatientId = patientId,
                        Timestamp = timestampUtc,
                        GlucoseMmoll = glucoseVal,
                        Source = "libre",
                        Status = status
                    });
                    existingGlucoseTimestamps.Add(timestampUtc);
                }

                // 2. Parse Carbs
                if (recordType == 5 && carbsIdx != -1 && carbsIdx < row.Count && double.TryParse(row[carbsIdx], NumberStyles.Any, CultureInfo.InvariantCulture, out double carbsVal))
                {
                    if (!existingMealTimestamps.Contains(timestampUtc))
                    {
                        mealsToInsert.Add(new Models.Meal
                        {
                            PatientId = patientId,
                            Timestamp = timestampUtc,
                            Carbs = carbsVal,
                            MealType = null
                        });
                        existingMealTimestamps.Add(timestampUtc);
                    }
                }

                // 3. Parse Insulin (Rapid-acting/bolus)
                if (rapidInsulinIdx != -1 && rapidInsulinIdx < row.Count && double.TryParse(row[rapidInsulinIdx], NumberStyles.Any, CultureInfo.InvariantCulture, out double rapidInsulinVal))
                {
                    if (!existingInsulinTimestamps.Contains(timestampUtc))
                    {
                        insulinsToInsert.Add(new Models.Insulin
                        {
                            PatientId = patientId,
                            Timestamp = timestampUtc,
                            Units = rapidInsulinVal,
                            EventType = "bolus"
                        });
                        existingInsulinTimestamps.Add(timestampUtc);
                    }
                }

                // 4. Parse Insulin (Long-acting/basal)
                if (longInsulinIdx != -1 && longInsulinIdx < row.Count && double.TryParse(row[longInsulinIdx], NumberStyles.Any, CultureInfo.InvariantCulture, out double longInsulinVal))
                {
                    if (!existingInsulinTimestamps.Contains(timestampUtc))
                    {
                        insulinsToInsert.Add(new Models.Insulin
                        {
                            PatientId = patientId,
                            Timestamp = timestampUtc,
                            Units = longInsulinVal,
                            EventType = "basal"
                        });
                        existingInsulinTimestamps.Add(timestampUtc);
                    }
                }
            }

            if (glucosesToInsert.Count > 0) db.Glucoses.AddRange(glucosesToInsert);
            if (mealsToInsert.Count > 0) db.Meals.AddRange(mealsToInsert);
            if (insulinsToInsert.Count > 0) db.Insulins.AddRange(insulinsToInsert);

            await db.SaveChangesAsync();

            return Ok(new {
                message = "CSV imported successfully",
                glucose_count = glucosesToInsert.Count,
                meal_count = mealsToInsert.Count,
                insulin_count = insulinsToInsert.Count
            });
        }
        catch (Exception ex)
        {
            return BadRequest(new { error = $"Failed to parse CSV: {ex.Message}" });
        }
    }

    private static List<string> ParseCsvLine(string line, char delimiter)
    {
        var result = new List<string>();
        var currentToken = new System.Text.StringBuilder();
        bool inQuotes = false;
        for (int i = 0; i < line.Length; i++)
        {
            char c = line[i];
            if (c == '"')
            {
                inQuotes = !inQuotes;
            }
            else if (c == delimiter && !inQuotes)
            {
                result.Add(currentToken.ToString().Trim());
                currentToken.Clear();
            }
            else
            {
                currentToken.Append(c);
            }
        }
        result.Add(currentToken.ToString().Trim());
        return result;
    }

    private PatientDto ToDto(Models.Patient p) => new(
        p.Id,
        p.ExternalId,
        p.Name,
        patientService.CalculateAge(p.DateOfBirth) ?? 0
    );
}
