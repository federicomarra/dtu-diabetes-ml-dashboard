using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace DiabetesApi.Models;

[Table("insulin_events")]
public class InsulinEvent
{
    [Key]
    [Column("id")]
    public int Id { get; set; }

    [Column("patient_id")]
    public int PatientId { get; set; }

    [Required]
    [Column("timestamp")]
    public DateTime Timestamp { get; set; }

    [Column("units")]
    public double Units { get; set; }

    [Required]
    [Column("event_type")]
    [MaxLength(10)]
    public string EventType { get; set; } = string.Empty; // bolus, basal

    [Column("is_late")]
    public bool IsLate { get; set; } = false;

    [Column("is_missed")]
    public bool IsMissed { get; set; } = false;

    [Column("created_at")]
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    public Patient Patient { get; set; } = null!;
}
