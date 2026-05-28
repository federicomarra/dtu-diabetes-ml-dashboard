using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace DiabetesApi.Models;

[Table("glucoses")]
public class Glucose
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

    [NotMapped]
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    // Navigation
    public Patient Patient { get; set; } = null!;

    [Required]
    [Column("status")]
    [MaxLength(20)]
    public string Status { get; set; } = "in_range";
}
