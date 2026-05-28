using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace DiabetesApi.Models;

[Table("histories")]
public class History
{
    [Key]
    [Column("id")]
    public int Id { get; set; }

    [Column("patient_id")]
    public int PatientId { get; set; }

    public Patient Patient { get; set; } = null!;

    [Required]
    [Column("timestamp")]
    public DateTime Timestamp { get; set; }

    [Column("glucose_mmoll")]
    public float? Glucose { get; set; }

    [Column("insulin_U")]
    public float? Insulin { get; set; }

    [Column("cho_grams")]
    public float? Meal { get; set; }
}