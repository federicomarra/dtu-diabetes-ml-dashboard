using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace DiabetesApi.Models;

[Table("glucose_readings")]
public class GlucoseReading
{
    [Key]
    [Column("id")]
    public int Id { get; set; }

    [Column("patient_id")]
    public int PatientId { get; set; }

    [Required]
    [Column("timestamp")]
    public DateTime Timestamp { get; set; }

    [Column("glucose_mmoll")]
    public double GlucoseMmoll { get; set; }

    [Column("source")]
    [MaxLength(20)]
    public string Source { get; set; } = "simulated";

    [Column("created_at")]
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    // Navigation
    public Patient Patient { get; set; } = null!;

    /// <summary>Clinical classification of the glucose value (mmol/L thresholds).</summary>
    [NotMapped]
    public string Status => GlucoseMmoll switch
    {
        < 3.0 => "very_low",
        < 3.9 => "low",
        <= 10.0 => "in_range",
        <= 13.9 => "high",
        _ => "very_high"
    };
}
