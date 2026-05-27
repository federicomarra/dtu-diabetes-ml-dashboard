using Microsoft.EntityFrameworkCore;
using DiabetesApi.Models;

namespace DiabetesApi.Data;

public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public DbSet<Patient> Patients => Set<Patient>();
    public DbSet<GlucoseReading> GlucoseReadings => Set<GlucoseReading>();
    public DbSet<AnomalyDetection> AnomalyDetections => Set<AnomalyDetection>();
    public DbSet<InsulinEvent> InsulinEvents => Set<InsulinEvent>();
    public DbSet<MealEvent> MealEvents => Set<MealEvent>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        // Patient unique index on external_id
        modelBuilder.Entity<Patient>()
            .HasIndex(p => p.ExternalId)
            .IsUnique();

        // Composite index: glucose readings per patient sorted by time
        modelBuilder.Entity<GlucoseReading>()
            .HasIndex(g => new { g.PatientId, g.Timestamp })
            .HasDatabaseName("ix_glucose_patient_time");

        // Composite index: insulin events per patient sorted by time
        modelBuilder.Entity<InsulinEvent>()
            .HasIndex(i => new { i.PatientId, i.Timestamp })
            .HasDatabaseName("ix_insulin_patient_time");

        // Composite index: meal events per patient sorted by time
        modelBuilder.Entity<MealEvent>()
            .HasIndex(m => new { m.PatientId, m.Timestamp })
            .HasDatabaseName("ix_meal_patient_time");

        // Relationships
        modelBuilder.Entity<GlucoseReading>()
            .HasOne(g => g.Patient)
            .WithMany(p => p.GlucoseReadings)
            .HasForeignKey(g => g.PatientId);

        modelBuilder.Entity<InsulinEvent>()
            .HasOne(i => i.Patient)
            .WithMany(p => p.InsulinEvents)
            .HasForeignKey(i => i.PatientId);

        modelBuilder.Entity<MealEvent>()
            .HasOne(m => m.Patient)
            .WithMany(p => p.MealEvents)
            .HasForeignKey(m => m.PatientId);

        modelBuilder.Entity<AnomalyDetection>()
            .HasOne(a => a.Patient)
            .WithMany(p => p.AnomalyDetections)
            .HasForeignKey(a => a.PatientId);

        modelBuilder.Entity<AnomalyDetection>()
            .HasOne(a => a.GlucoseReading)
            .WithMany()
            .HasForeignKey(a => a.GlucoseReadingId)
            .IsRequired(false);
    }
}
