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

    [Column("created_at")]
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    [Column("updated_at")]
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;

    // Navigation
    public ICollection<Glucose> Glucoses { get; set; } = [];
    public ICollection<Insulin> Insulins { get; set; } = [];
    public ICollection<Meal> Meals { get; set; } = [];
    public ICollection<Anomaly> Anomalies { get; set; } = [];
    public ICollection<Exercise> Exercises { get; set; } = [];
    public ICollection<History> Histories { get; set; } = [];
}
