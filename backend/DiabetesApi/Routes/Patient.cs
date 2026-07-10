using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ModelBinding;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.Models;
using DiabetesApi.Services;
using Microsoft.AspNetCore.Http;
using System;
using System.Linq;
using System.Threading.Tasks;

namespace DiabetesApi.Routes;

/// <summary>Patient management endpoints.</summary>
[ApiController]
[Route("api/patient")]
[Produces("application/json")]
public class Patient(AppDbContext db, PatientService patientService, UploadService uploadService) : ControllerBase
{
    /// <summary>List all patients with optional pagination and sorting.</summary>
    /// <param name="page">Page number (default 1).</param>
    /// <param name="perPage">Items per page (default 20).</param>
    /// <param name="sortBy">Field to sort by: "name", "ext_id"/"external_id", "age"/"date_of_birth", "anomalies", or "tir" (default is creation date).</param>
    /// <param name="sortDir">Sorting direction: "asc" or "desc" (default "desc").</param>
    /// <param name="start">Optional time window start (ISO datetime).</param>
    /// <param name="end">Optional time window end (ISO datetime).</param>
    /// <param name="last">Optional sliding window duration (e.g., "24h", "7d", "2w", "1m").</param>
    /// <param name="low">Optional custom glucose range lower threshold (mmol/L).</param>
    /// <param name="high">Optional custom glucose range upper threshold (mmol/L).</param>
    [HttpGet("list")]
    [ProducesResponseType(typeof(PaginatedPatientsResponse), StatusCodes.Status200OK)]
    public async Task<IActionResult> ListPatients(
        [FromQuery] int page = 1,
        [FromQuery] int perPage = 20,
        [FromQuery] string? sortBy = null,
        [FromQuery] string? sortDir = null,
        [FromQuery] string? start = null,
        [FromQuery] string? end = null,
        [FromQuery] string? last = null,
        [FromQuery] double? low = null,
        [FromQuery] double? high = null)
    {
        IQueryable<Models.Patient> query = db.Patients;

        if (!string.IsNullOrWhiteSpace(sortBy))
        {
            var isAsc = sortDir?.ToLowerInvariant() == "asc";
            if (sortBy.Equals("name", StringComparison.OrdinalIgnoreCase))
            {
                query = isAsc 
                    ? query.OrderBy(p => p.Name).ThenBy(p => p.Id) 
                    : query.OrderByDescending(p => p.Name).ThenByDescending(p => p.Id);
            }
            else if (sortBy.Equals("ext_id", StringComparison.OrdinalIgnoreCase) || 
                     sortBy.Equals("external_id", StringComparison.OrdinalIgnoreCase))
            {
                query = isAsc 
                    ? query.OrderBy(p => p.ExternalId).ThenBy(p => p.Id) 
                    : query.OrderByDescending(p => p.ExternalId).ThenByDescending(p => p.Id);
            }
            else if (sortBy.Equals("age", StringComparison.OrdinalIgnoreCase) || 
                     sortBy.Equals("date_of_birth", StringComparison.OrdinalIgnoreCase))
            {
                // Age is calculated: younger has larger DateOfBirth, older has smaller DateOfBirth.
                // Age Ascending -> youngest first -> DateOfBirth DESCENDING.
                // Age Descending -> oldest first -> DateOfBirth ASCENDING.
                query = isAsc 
                    ? query.OrderByDescending(p => p.DateOfBirth).ThenByDescending(p => p.Id) 
                    : query.OrderBy(p => p.DateOfBirth).ThenBy(p => p.Id);
            }
            else if (sortBy.Equals("anomalies", StringComparison.OrdinalIgnoreCase))
            {
                var range = await TimeRangeUtils.ResolveTimeRangeAsync(
                    last: last,
                    start: start,
                    end: end,
                    getLatestTimestamp: () => db.Glucoses.Select(g => (DateTime?)g.Timestamp).MaxAsync());

                if (range is null)
                {
                    return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });
                }

                var rangeStart = range.Value.start;
                var rangeEnd = range.Value.end;

                query = isAsc 
                    ? query.OrderBy(p => p.Anomalies.Count(a => !a.IsAcknowledged && a.DetectedAt >= rangeStart && a.DetectedAt <= rangeEnd)).ThenBy(p => p.Id) 
                    : query.OrderByDescending(p => p.Anomalies.Count(a => !a.IsAcknowledged && a.DetectedAt >= rangeStart && a.DetectedAt <= rangeEnd)).ThenByDescending(p => p.Id);
            }
            else if (sortBy.Equals("tir", StringComparison.OrdinalIgnoreCase))
            {
                var range = await TimeRangeUtils.ResolveTimeRangeAsync(
                    last: last,
                    start: start,
                    end: end,
                    getLatestTimestamp: () => db.Glucoses.Select(g => (DateTime?)g.Timestamp).MaxAsync());

                if (range is null)
                {
                    return BadRequest(new { error = "Invalid last parameter format. Use e.g. 24h, 7d, 2w, 1m." });
                }

                var rangeStart = range.Value.start;
                var rangeEnd = range.Value.end;
                var thresholdLow = low ?? 3.9;
                var thresholdHigh = high ?? 10.0;

                query = isAsc 
                    ? query.OrderBy(p => p.Glucoses.Count(g => g.Timestamp >= rangeStart && g.Timestamp <= rangeEnd) == 0 
                        ? 0.0 
                        : (double)p.Glucoses.Count(g => g.Timestamp >= rangeStart && g.Timestamp <= rangeEnd && g.GlucoseMmoll >= thresholdLow && g.GlucoseMmoll <= thresholdHigh) 
                          / p.Glucoses.Count(g => g.Timestamp >= rangeStart && g.Timestamp <= rangeEnd)
                      ).ThenBy(p => p.Id) 
                    : query.OrderByDescending(p => p.Glucoses.Count(g => g.Timestamp >= rangeStart && g.Timestamp <= rangeEnd) == 0 
                        ? 0.0 
                        : (double)p.Glucoses.Count(g => g.Timestamp >= rangeStart && g.Timestamp <= rangeEnd && g.GlucoseMmoll >= thresholdLow && g.GlucoseMmoll <= thresholdHigh) 
                          / p.Glucoses.Count(g => g.Timestamp >= rangeStart && g.Timestamp <= rangeEnd)
                      ).ThenByDescending(p => p.Id);
            }
            else
            {
                query = query.OrderByDescending(p => p.CreatedAt).ThenByDescending(p => p.Id);
            }
        }
        else
        {
            query = query.OrderByDescending(p => p.CreatedAt).ThenByDescending(p => p.Id);
        }

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
    [ProducesResponseType(StatusCodes.Status409Conflict)]
    public async Task<IActionResult> CreatePatient([FromBody] CreatePatientRequest req)
    {
        if (string.IsNullOrWhiteSpace(req.ExternalId) || string.IsNullOrWhiteSpace(req.Name))
            return BadRequest(new { error = "external_id and name are required" });

        // Without this the unique index on external_id raises a DbUpdateException, which the
        // client receives as an unhandled 500 with a stack trace and no readable `error` field.
        if (await db.Patients.AnyAsync(p => p.ExternalId == req.ExternalId))
            return Conflict(new { error = $"A patient with external_id '{req.ExternalId}' already exists." });

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
            using var stream = file.OpenReadStream();
            var result = await uploadService.ProcessCsvUploadAsync(patientId, stream);

            return Ok(new {
                message = "CSV imported successfully",
                glucose_count = result.GlucoseCount,
                meal_count = result.MealCount,
                insulin_count = result.InsulinCount,
                date_from = result.DateFrom?.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                date_to   = result.DateTo?.ToString("yyyy-MM-ddTHH:mm:ssZ")
            });
        }
        catch (Exception ex)
        {
            return BadRequest(new { error = $"Failed to parse CSV: {ex.Message}" });
        }
    }

    /// <summary>Upload glucose, insulin, and carb data from a Glooko ZIP export.</summary>
    /// <param name="id">Patient database ID.</param>
    /// <param name="file">Glooko ZIP file to upload.</param>
    [HttpPost("upload-glooko-zip")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> UploadGlookoZip(
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
            using var stream = file.OpenReadStream();
            var result = await uploadService.ProcessGlookoZipUploadAsync(patientId, stream);

            return Ok(new
            {
                message = "Glooko ZIP imported successfully",
                glucose_count = result.GlucoseCount,
                meal_count = result.MealCount,
                insulin_count = result.InsulinCount,
                date_from = result.DateFrom?.ToString("yyyy-MM-ddTHH:mm:ssZ"),
                date_to   = result.DateTo?.ToString("yyyy-MM-ddTHH:mm:ssZ")
            });
        }
        catch (Exception ex)
        {
            return BadRequest(new { error = $"Failed to parse Glooko ZIP: {ex.Message}" });
        }
    }

    private PatientDto ToDto(Models.Patient p) => new(
        p.Id,
        p.ExternalId,
        p.Name,
        patientService.CalculateAge(p.DateOfBirth) ?? 0
    );
}
