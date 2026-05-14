using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.DTOs;
using DiabetesApi.Models;

namespace DiabetesApi.Controllers;

/// <summary>Patient management endpoints.</summary>
[ApiController]
[Route("api/patients")]
[Produces("application/json")]
public class PatientsController(AppDbContext db) : ControllerBase
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

    /// <summary>Get a single patient by ID.</summary>
    [HttpGet("{patientId:int}")]
    [ProducesResponseType(typeof(PatientDto), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetPatient(int patientId)
    {
        var patient = await db.Patients.FindAsync(patientId);
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

        var patient = new Patient
        {
            ExternalId   = req.ExternalId,
            Name         = req.Name,
            DiabetesType = req.DiabetesType ?? "T1D",
            DateOfBirth  = req.DateOfBirth  is not null ? DateOnly.Parse(req.DateOfBirth)  : null,
            DiagnosisDate= req.DiagnosisDate is not null ? DateOnly.Parse(req.DiagnosisDate): null,
        };

        db.Patients.Add(patient);
        await db.SaveChangesAsync();

        return CreatedAtAction(nameof(GetPatient), new { patientId = patient.Id }, ToDto(patient));
    }

    private static PatientDto ToDto(Patient p) => new(
        p.Id,
        p.ExternalId,
        p.Name,
        p.DateOfBirth?.ToString("yyyy-MM-dd"),
        p.DiabetesType,
        p.DiagnosisDate?.ToString("yyyy-MM-dd"),
        p.CreatedAt.ToString("O")
    );
}
