using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Http;
using DiabetesApi.Services;
using System;
using System.IO;
using System.Threading.Tasks;

namespace DiabetesApi.Routes;

/// <summary>Doctor operations and global uploads.</summary>
[ApiController]
[Route("api/doctor")]
[Produces("application/json")]
public class Doctor(UploadService uploadService) : ControllerBase
{
    /// <summary>Upload patient cohort data from a simulation Parquet file.</summary>
    /// <param name="file">Parquet simulation file to upload.</param>
    [HttpPost("upload-parquet")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> UploadParquet(IFormFile file)
    {
        if (file == null || file.Length == 0)
            return BadRequest(new { error = "No file uploaded or file is empty" });

        try
        {
            using var stream = file.OpenReadStream();
            var result = await uploadService.ProcessParquetUploadAsync(stream);
            return Ok(new
            {
                message = "Parquet simulation imported successfully",
                patients_count = result.PatientsCount,
                glucose_count = result.GlucoseCount,
                meal_count = result.MealCount,
                insulin_count = result.InsulinCount
            });
        }
        catch (Exception ex)
        {
            return BadRequest(new { error = $"Failed to parse Parquet: {ex.Message}" });
        }
    }
}
