using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace DiabetesApi.Models;

[Table("insulins")]
public class Insulin
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

    public Patient Patient { get; set; } = null!;
}
