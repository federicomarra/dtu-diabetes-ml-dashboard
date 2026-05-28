using Microsoft.EntityFrameworkCore;
using DiabetesApi.Models;

namespace DiabetesApi.Data;

public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public DbSet<Patient> Patients => Set<Patient>();
    public DbSet<Glucose> Glucoses => Set<Glucose>();
    public DbSet<Anomaly> Anomalies => Set<Anomaly>();
    public DbSet<Insulin> Insulins => Set<Insulin>();
    public DbSet<Meal> Meals => Set<Meal>();
    public DbSet<Exercise> Exercises => Set<Exercise>();
    public DbSet<History> Histories => Set<History>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        // Patient unique index on external_id
        modelBuilder.Entity<Patient>()
            .HasIndex(p => p.ExternalId)
            .IsUnique()
            .HasDatabaseName("idx_patients_external_id");

        // Composite index: glucose readings per patient sorted by time
        modelBuilder.Entity<Glucose>()
            .HasIndex(g => new { g.PatientId, g.Timestamp })
            .HasDatabaseName("idx_glucose_patient_time");

        // Composite index: insulin events per patient sorted by time
        modelBuilder.Entity<Insulin>()
            .HasIndex(i => new { i.PatientId, i.Timestamp })
            .HasDatabaseName("idx_insulin_patient_time");

        // Composite index: meal events per patient sorted by time
        modelBuilder.Entity<Meal>()
            .HasIndex(m => new { m.PatientId, m.Timestamp })
            .HasDatabaseName("idx_meal_patient_time");

        // Composite index: exercise events per patient sorted by time
        modelBuilder.Entity<Exercise>()
            .HasIndex(e => new { e.PatientId, e.Timestamp })
            .HasDatabaseName("idx_exercise_patient_time");

        // Composite index: histories per patient sorted by time
        modelBuilder.Entity<History>()
            .HasIndex(h => new { h.PatientId, h.Timestamp })
            .HasDatabaseName("idx_history_patient_time");

        // Index: anomaly per patient
        modelBuilder.Entity<Anomaly>()
            .HasIndex(a => a.PatientId)
            .HasDatabaseName("idx_anomaly_patient");

        // Relationships
        modelBuilder.Entity<Glucose>()
            .HasOne(g => g.Patient)
            .WithMany(p => p.Glucoses)
            .HasForeignKey(g => g.PatientId);

        modelBuilder.Entity<Insulin>()
            .HasOne(i => i.Patient)
            .WithMany(p => p.Insulins)
            .HasForeignKey(i => i.PatientId);

        modelBuilder.Entity<Meal>()
            .HasOne(m => m.Patient)
            .WithMany(p => p.Meals)
            .HasForeignKey(m => m.PatientId);

        modelBuilder.Entity<Exercise>()
            .HasOne(e => e.Patient)
            .WithMany(p => p.Exercises)
            .HasForeignKey(e => e.PatientId);

        modelBuilder.Entity<History>()
            .HasOne(h => h.Patient)
            .WithMany(p => p.Histories)
            .HasForeignKey(h => h.PatientId);

        modelBuilder.Entity<Anomaly>()
            .HasOne(a => a.Patient)
            .WithMany(p => p.Anomalies)
            .HasForeignKey(a => a.PatientId);

        modelBuilder.Entity<Anomaly>()
            .HasOne(a => a.GlucoseReading)
            .WithMany()
            .HasForeignKey(a => a.GlucoseReadingId)
            .IsRequired(false);
    }
}
