using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace DiabetesApi.Models;

[Table("exercises")]
public class Exercise
{
    [Key]
    [Column("id")]
    public int Id { get; set; }

    [Column("patient_id")]
    public int PatientId { get; set; }

    [Required]
    [Column("timestamp")]
    public DateTime Timestamp { get; set; }

    [Column("duration_minutes")]
    public int DurationMinutes { get; set; }

    [Required]
    [Column("intensity")]
    [MaxLength(10)]
    public string Intensity { get; set; } = string.Empty; // low, medium, high

    public Patient Patient { get; set; } = null!;
}
