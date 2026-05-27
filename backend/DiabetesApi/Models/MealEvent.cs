using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace DiabetesApi.Models;

[Table("meal_events")]
public class MealEvent
{
    [Key]
    [Column("id")]
    public int Id { get; set; }

    [Column("patient_id")]
    public int PatientId { get; set; }

    [Required]
    [Column("timestamp")]
    public DateTime Timestamp { get; set; }

    [Column("carbs_grams")]
    public double CarbsGrams { get; set; }

    [Column("meal_type")]
    [MaxLength(20)]
    public string? MealType { get; set; } // breakfast, lunch, dinner, snack

    [Column("created_at")]
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    public Patient Patient { get; set; } = null!;
}
