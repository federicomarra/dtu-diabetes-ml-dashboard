using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace DiabetesApi.Models;

[Table("meals")]
public class Meal
{
    [Key]
    [Column("id")]
    public int Id { get; set; }

    [Column("patient_id")]
    public int PatientId { get; set; }

    [Required]
    [Column("timestamp")]
    public DateTime Timestamp { get; set; }

    [Column("carbs")]
    public double Carbs { get; set; }

    [Column("meal_type")]
    [MaxLength(20)]
    public string? MealType { get; set; } // breakfast, lunch, dinner, snack

    public Patient Patient { get; set; } = null!;
}
