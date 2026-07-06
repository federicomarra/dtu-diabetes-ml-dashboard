using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.Models;

namespace DiabetesApi.Services;

/// <summary>Service for handling patient-related business logic.</summary>
public class PatientService(AppDbContext db)
{
    /// <summary>
    /// Calculates the patient's age in years based on their DateOfBirth.
    /// Returns null if DateOfBirth is null.
    /// </summary>
    public int? CalculateAge(DateOnly? dateOfBirth)
    {
        if (dateOfBirth == null) return null;

        var today = DateOnly.FromDateTime(DateTime.UtcNow);
        int age = today.Year - dateOfBirth.Value.Year;

        // If today's date is before the birth date this year, decrement age
        if (today < dateOfBirth.Value.AddYears(age))
        {
            age--;
        }

        return age;
    }

    /// <summary>
    /// Syncs newly uploaded glucose, meal, and insulin data into the histories table.
    /// Integrates/merges the values for each unique timestamp.
    /// </summary>
    public async Task SyncHistoriesAsync(
        int patientId,
        List<Glucose> glucoses,
        List<Meal> meals,
        List<Insulin> insulins)
    {
        if (glucoses.Count == 0 && meals.Count == 0 && insulins.Count == 0)
            return;

        // Extract all unique timestamps
        var timestamps = glucoses.Select(g => g.Timestamp)
            .Concat(meals.Select(m => m.Timestamp))
            .Concat(insulins.Select(i => i.Timestamp))
            .Distinct()
            .ToList();

        if (timestamps.Count == 0) return;

        var minTime = timestamps.Min();
        var maxTime = timestamps.Max();

        // Fetch existing histories in the range to avoid duplication and merge instead
        var existingHistories = await db.Histories
            .Where(h => h.PatientId == patientId && h.Timestamp >= minTime && h.Timestamp <= maxTime)
            .ToDictionaryAsync(h => h.Timestamp);

        // Group the new data by timestamp to aggregate/merge values
        var glucoseByTime = glucoses
            .GroupBy(g => g.Timestamp)
            .ToDictionary(g => g.Key, g => g.First().GlucoseMmoll);

        var mealsByTime = meals
            .GroupBy(m => m.Timestamp)
            .ToDictionary(g => g.Key, g => g.Sum(m => m.Carbs));

        var insulinsByTime = insulins
            .GroupBy(i => i.Timestamp)
            .ToDictionary(g => g.Key, g => g.Sum(i => i.Units));

        var historiesToInsert = new List<History>();

        foreach (var ts in timestamps)
        {
            double? glucoseVal = glucoseByTime.TryGetValue(ts, out var g) ? g : null;
            double? mealVal = mealsByTime.TryGetValue(ts, out var m) ? m : null;
            double? insulinVal = insulinsByTime.TryGetValue(ts, out var ins) ? ins : null;

            if (existingHistories.TryGetValue(ts, out var existingHist))
            {
                // If it already exists, merge the new values with existing ones
                if (glucoseVal.HasValue)
                {
                    existingHist.Glucose = (float)Math.Round(glucoseVal.Value, 1);
                }
                if (mealVal.HasValue)
                {
                    existingHist.Meal = (float)Math.Round(mealVal.Value, 0);
                }
                if (insulinVal.HasValue)
                {
                    existingHist.Insulin = (float)Math.Round(insulinVal.Value, 3);
                }
            }
            else
            {
                // Create a new history entry
                historiesToInsert.Add(new History
                {
                    PatientId = patientId,
                    Timestamp = ts,
                    Glucose = glucoseVal.HasValue ? (float)Math.Round(glucoseVal.Value, 1) : null,
                    Meal = mealVal.HasValue ? (float)Math.Round(mealVal.Value, 0) : null,
                    Insulin = insulinVal.HasValue ? (float)Math.Round(insulinVal.Value, 3) : null
                });
            }
        }

        if (historiesToInsert.Count > 0)
        {
            db.Histories.AddRange(historiesToInsert);
        }
    }
}
