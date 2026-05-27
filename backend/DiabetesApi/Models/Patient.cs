using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace DiabetesApi.Models;

[Table("patients")]
public class Patient
{
    [Key]
    [Column("id")]
    public int Id { get; set; }

    [Required]
    [Column("external_id")]
    [MaxLength(50)]
    public string ExternalId { get; set; } = string.Empty;

    [Required]
    [Column("name")]
    [MaxLength(120)]
    public string Name { get; set; } = string.Empty;

    [Column("date_of_birth")]
    public DateOnly? DateOfBirth { get; set; }

    [Column("diabetes_type")]
    [MaxLength(10)]
    public string DiabetesType { get; set; } = "T1D";

    [Column("diagnosis_date")]
    public DateOnly? DiagnosisDate { get; set; }

    [Column("created_at")]
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    [Column("updated_at")]
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;

    // Navigation
    public ICollection<GlucoseReading> GlucoseReadings { get; set; } = [];
    public ICollection<InsulinEvent> InsulinEvents { get; set; } = [];
    public ICollection<MealEvent> MealEvents { get; set; } = [];
    public ICollection<AnomalyDetection> AnomalyDetections { get; set; } = [];
}
