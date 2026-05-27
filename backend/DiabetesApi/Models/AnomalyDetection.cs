using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace DiabetesApi.Models;

[Table("anomaly_detections")]
public class AnomalyDetection
{
    [Key]
    [Column("id")]
    public int Id { get; set; }

    [Column("patient_id")]
    public int PatientId { get; set; }

    [Column("glucose_reading_id")]
    public int? GlucoseReadingId { get; set; }

    [Required]
    [Column("anomaly_type")]
    [MaxLength(30)]
    public string AnomalyType { get; set; } = string.Empty;

    [Column("confidence")]
    public double Confidence { get; set; }

    [Column("description")]
    public string? Description { get; set; }

    [Column("is_acknowledged")]
    public bool IsAcknowledged { get; set; } = false;

    [Column("detected_at")]
    public DateTime DetectedAt { get; set; } = DateTime.UtcNow;

    // Navigation
    public Patient Patient { get; set; } = null!;
    public GlucoseReading? GlucoseReading { get; set; }
}
