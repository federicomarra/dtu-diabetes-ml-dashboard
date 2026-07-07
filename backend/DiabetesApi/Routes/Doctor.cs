using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.Services;
using Parquet.Serialization;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

// Resolve type clashes between controller names and database entity models
using PatientModel = DiabetesApi.Models.Patient;
using GlucoseModel = DiabetesApi.Models.Glucose;
using MealModel = DiabetesApi.Models.Meal;
using InsulinModel = DiabetesApi.Models.Insulin;

namespace DiabetesApi.Routes;

/// <summary>Doctor operations and global uploads.</summary>
[ApiController]
[Route("api/doctor")]
[Produces("application/json")]
public class Doctor(AppDbContext db, PatientService patientService) : ControllerBase
{
    private class ParquetRow
    {
        public string? patient_id { get; set; }
        public double? patient_age_years { get; set; }
        public long? day { get; set; }
        public long? minute { get; set; }
        public long? absolute_minute { get; set; }
        public double? blood_glucose { get; set; }
        public double? cho_mg_min { get; set; }
        public double? cho_mg_announced { get; set; }
        public double? insulin_mU_min { get; set; }
        /*
        public bool? had_missed_bolus { get; set; }
        public long? n_late_boluses { get; set; }
        public long? scenario_id { get; set; }
        public object? exercise_overlay { get; set; }
        public string? exercise_type { get; set; }
        */
    }

    /// <summary>Upload patient cohort data from a simulation Parquet file.</summary>
    /// <param name="file">Parquet simulation file to upload.</param>
    [HttpPost("upload-parquet")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> UploadParquet(IFormFile file)
    {
        if (file == null || file.Length == 0)
            return BadRequest(new { error = "No file uploaded or file is empty" });

        try
        {
            IList<ParquetRow> rows;
            using (var stream = file.OpenReadStream())
            {
                var result = await ParquetSerializer.DeserializeAsync<ParquetRow>(stream);
                rows = result.Data;
            }

            if (rows == null || rows.Count == 0)
            {
                return BadRequest(new { error = "Parquet file contains no rows." });
            }

            // Determine simulation base date: now - max(day)
            long maxDay = rows.Max(r => r.day) ?? 14;
            if (maxDay <= 0) maxDay = 14;
            var baseDt = DateTime.UtcNow.Date.AddDays(-(int)maxDay);

            var patientsGrouped = rows.Where(r => !string.IsNullOrEmpty(r.patient_id)).GroupBy(r => r.patient_id!).ToList();
            var patientIdsInFile = patientsGrouped
                .Select(g => $"SIM_{(int.TryParse(g.Key, out int pidInt) ? pidInt.ToString("D6") : g.Key)}")
                .ToList();

            // Upsert patients
            var existingPatients = await db.Patients
                .Where(p => patientIdsInFile.Contains(p.ExternalId))
                .ToDictionaryAsync(p => p.ExternalId);

            foreach (var grp in patientsGrouped)
            {
                string formattedId = int.TryParse(grp.Key, out int pidInt) ? pidInt.ToString("D6") : grp.Key;
                string extId = $"SIM_{formattedId}";
                string name = $"Simulated patient {formattedId}";

                int seed = pidInt;
                var rng = new Random(seed);
                double patientAgeYears = grp.First().patient_age_years ?? 35.0;
                var birthYear = baseDt.Year - (int)patientAgeYears;
                var birthMonth = rng.Next(1, 13);
                var daysInMonth = DateTime.DaysInMonth(birthYear, birthMonth);
                var birthDay = rng.Next(1, daysInMonth + 1);
                var dob = new DateOnly(birthYear, birthMonth, birthDay);

                if (existingPatients.TryGetValue(extId, out var existingPat))
                {
                    existingPat.DateOfBirth = dob;
                    existingPat.UpdatedAt = DateTime.UtcNow;
                }
                else
                {
                    var newPat = new PatientModel
                    {
                        ExternalId = extId,
                        Name = name,
                        DateOfBirth = dob,
                        CreatedAt = DateTime.UtcNow,
                        UpdatedAt = DateTime.UtcNow
                    };
                    db.Patients.Add(newPat);
                }
            }

            await db.SaveChangesAsync();

            // Refresh patient ID map
            var patientIdMap = await db.Patients
                .Where(p => patientIdsInFile.Contains(p.ExternalId))
                .ToDictionaryAsync(p => p.ExternalId, p => p.Id);

            // Preload existing timestamps to avoid duplicate inserts
            var dbPatientIds = patientIdMap.Values.ToList();
            var existingGlucoseSet = (await db.Glucoses
                .Where(g => dbPatientIds.Contains(g.PatientId))
                .Select(g => new { g.PatientId, g.Timestamp })
                .ToListAsync())
                .Select(x => (x.PatientId, x.Timestamp))
                .ToHashSet();

            var existingMealSet = (await db.Meals
                .Where(m => dbPatientIds.Contains(m.PatientId))
                .Select(m => new { m.PatientId, m.Timestamp })
                .ToListAsync())
                .Select(x => (x.PatientId, x.Timestamp))
                .ToHashSet();

            var existingInsulinSet = (await db.Insulins
                .Where(i => dbPatientIds.Contains(i.PatientId))
                .Select(i => new { i.PatientId, i.Timestamp })
                .ToListAsync())
                .Select(x => (x.PatientId, x.Timestamp))
                .ToHashSet();

            var glucosesToInsert = new List<GlucoseModel>();
            var mealsToInsert = new List<MealModel>();
            var insulinsToInsert = new List<InsulinModel>();

            // Whether the parquet file has the cho_mg_announced column with actual values
            bool hasAnnounced = rows.Any(r => r.cho_mg_announced.HasValue);

            foreach (var grp in patientsGrouped)
            {
                string formattedId = int.TryParse(grp.Key, out int pidInt) ? pidInt.ToString("D6") : grp.Key;
                string extId = $"SIM_{formattedId}";
                if (!patientIdMap.TryGetValue(extId, out int dbPatientId)) continue;

                var patientRows = grp.Where(r => r.absolute_minute.HasValue).OrderBy(r => r.absolute_minute!.Value).ToList();

                // 1. Glucose readings
                foreach (var row in patientRows)
                {
                    if (!row.blood_glucose.HasValue) continue;

                    var ts = DateTime.SpecifyKind(baseDt.AddMinutes(row.absolute_minute!.Value), DateTimeKind.Utc);
                    if (existingGlucoseSet.Contains((dbPatientId, ts))) continue;

                    double mmol = Math.Round(row.blood_glucose.Value, 1);
                    string status = "in_range";
                    if (mmol < 3.0) status = "very_low";
                    else if (mmol < 3.9) status = "low";
                    else if (mmol > 13.9) status = "very_high";
                    else if (mmol > 10.0) status = "high";

                    glucosesToInsert.Add(new GlucoseModel
                    {
                        PatientId = dbPatientId,
                        Timestamp = ts,
                        GlucoseMmoll = mmol,
                        Source = "simulated",
                        Status = status
                    });
                }

                // 2. Meal events (collapsed)
                var collapsedMeals = CollapseMealRuns(patientRows, baseDt, hasAnnounced);
                foreach (var m in collapsedMeals)
                {
                    var ts = DateTime.SpecifyKind(m.Timestamp, DateTimeKind.Utc);
                    if (existingMealSet.Contains((dbPatientId, ts))) continue;

                    mealsToInsert.Add(new MealModel
                    {
                        PatientId = dbPatientId,
                        Timestamp = ts,
                        Carbs = m.Carbs,
                        MealType = m.MealType
                    });
                }

                // 3. Insulin events (collapsed bolus + hourly basal)
                var boluses = GetBolusEvents(patientRows, baseDt);
                foreach (var b in boluses)
                {
                    var ts = DateTime.SpecifyKind(b.Timestamp, DateTimeKind.Utc);
                    if (existingInsulinSet.Contains((dbPatientId, ts))) continue;

                    insulinsToInsert.Add(new InsulinModel
                    {
                        PatientId = dbPatientId,
                        Timestamp = ts,
                        Units = b.Units,
                        EventType = "bolus"
                    });
                }

                var basals = GetBasalEvents(patientRows, baseDt);
                foreach (var b in basals)
                {
                    var ts = DateTime.SpecifyKind(b.Timestamp, DateTimeKind.Utc);
                    if (existingInsulinSet.Contains((dbPatientId, ts))) continue;

                    insulinsToInsert.Add(new InsulinModel
                    {
                        PatientId = dbPatientId,
                        Timestamp = ts,
                        Units = b.Units,
                        EventType = "basal"
                    });
                }

                /*
                // 4. Exercises (commented out per requirement)
                var exercises = GetExerciseEvents(patientRows, baseDt, dbPatientId);
                foreach (var ex in exercises)
                {
                    db.Exercises.Add(ex);
                }
                */

                /*
                // 5. Anomalies (commented out per requirement)
                var anomalies = GetAnomalyDetections(patientRows, baseDt, dbPatientId);
                foreach (var an in anomalies)
                {
                    db.Anomalies.Add(an);
                }
                */
            }

            if (glucosesToInsert.Count > 0) db.Glucoses.AddRange(glucosesToInsert);
            if (mealsToInsert.Count > 0) db.Meals.AddRange(mealsToInsert);
            if (insulinsToInsert.Count > 0) db.Insulins.AddRange(insulinsToInsert);

            await db.SaveChangesAsync();

            // Populate histories table for each patient
            foreach (var dbPatientId in dbPatientIds)
            {
                var patGlucoses = glucosesToInsert.Where(g => g.PatientId == dbPatientId).ToList();
                var patMeals = mealsToInsert.Where(m => m.PatientId == dbPatientId).ToList();
                var patInsulins = insulinsToInsert.Where(i => i.PatientId == dbPatientId).ToList();

                await patientService.SyncHistoriesAsync(dbPatientId, patGlucoses, patMeals, patInsulins);
            }

            await db.SaveChangesAsync();

            return Ok(new
            {
                message = "Parquet simulation imported successfully",
                patients_count = patientsGrouped.Count,
                glucose_count = glucosesToInsert.Count,
                meal_count = mealsToInsert.Count,
                insulin_count = insulinsToInsert.Count
            });
        }
        catch (Exception ex)
        {
            return BadRequest(new { error = $"Failed to parse Parquet: {ex.Message}" });
        }
    }

    private static List<(DateTime Timestamp, double Carbs, string? MealType)> CollapseMealRuns(
        List<ParquetRow> patientRows,
        DateTime baseDt,
        bool useAnnounced)
    {
        var meals = new List<(DateTime Timestamp, double Carbs, string? MealType)>();
        bool inRun = false;
        DateTime runStart = default;
        double runSum = 0.0;
        int firstMinuteOfDay = 0;

        foreach (var row in patientRows)
        {
            double val = (useAnnounced ? row.cho_mg_announced : row.cho_mg_min) ?? row.cho_mg_min ?? 0.0;
            if (val > 0.0)
            {
                if (!inRun)
                {
                    inRun = true;
                    runStart = baseDt.AddMinutes(row.absolute_minute!.Value);
                    runSum = val;
                    firstMinuteOfDay = (int)(row.minute ?? 0);
                }
                else
                {
                    runSum += val;
                }
            }
            else
            {
                if (inRun)
                {
                    double carbsGrams = Math.Round(runSum / 1000.0, 0);
                    if (carbsGrams > 0)
                    {
                        meals.Add((runStart, carbsGrams, GetMealType(firstMinuteOfDay)));
                    }
                    inRun = false;
                    runSum = 0.0;
                }
            }
        }
        if (inRun)
        {
            double carbsGrams = Math.Round(runSum / 1000.0, 0);
            if (carbsGrams > 0)
            {
                meals.Add((runStart, carbsGrams, GetMealType(firstMinuteOfDay)));
            }
        }

        return meals;
    }

    private static string GetMealType(int minuteOfDay)
    {
        if (300 <= minuteOfDay && minuteOfDay < 540) return "breakfast";
        if (660 <= minuteOfDay && minuteOfDay < 840) return "lunch";
        if (1020 <= minuteOfDay && minuteOfDay < 1320) return "dinner";
        return "snack";
    }

    private static List<(DateTime Timestamp, double Units)> GetBolusEvents(
        List<ParquetRow> patientRows,
        DateTime baseDt,
        double basalThreshold = 100.0)
    {
        var boluses = new List<(DateTime Timestamp, double Units)>();
        bool inRun = false;
        DateTime runStart = default;
        double runSum = 0.0;

        foreach (var row in patientRows)
        {
            double val = row.insulin_mU_min ?? 0.0;
            if (val > basalThreshold)
            {
                if (!inRun)
                {
                    inRun = true;
                    runStart = baseDt.AddMinutes(row.absolute_minute!.Value);
                    runSum = val;
                }
                else
                {
                    runSum += val;
                }
            }
            else
            {
                if (inRun)
                {
                    double units = Math.Round(runSum / 1000.0, 2);
                    if (units > 0)
                    {
                        boluses.Add((runStart, units));
                    }
                    inRun = false;
                    runSum = 0.0;
                }
            }
        }
        if (inRun)
        {
            double units = Math.Round(runSum / 1000.0, 2);
            if (units > 0)
            {
                boluses.Add((runStart, units));
            }
        }

        return boluses;
    }

    private static List<(DateTime Timestamp, double Units)> GetBasalEvents(
        List<ParquetRow> patientRows,
        DateTime baseDt,
        double basalThreshold = 100.0)
    {
        var basals = new List<(DateTime Timestamp, double Units)>();

        // 1. Hourly sums
        var basalRows = patientRows.Where(r => (r.insulin_mU_min ?? 0.0) > 0 && (r.insulin_mU_min ?? 0.0) <= basalThreshold).ToList();
        var hourlyGroups = basalRows.GroupBy(r => r.absolute_minute!.Value / 60);
        foreach (var grp in hourlyGroups)
        {
            long hour = grp.Key;
            double sum = grp.Sum(r => r.insulin_mU_min ?? 0.0);
            double units = Math.Round(sum / 1000.0, 2);
            var ts = baseDt.AddMinutes(hour * 60);
            basals.Add((ts, units));
        }

        // 2. Zero markers when basal stops and resumes
        for (int i = 1; i < patientRows.Count; i++)
        {
            var prev = patientRows[i - 1];
            var curr = patientRows[i];

            double prevVal = prev.insulin_mU_min ?? 0.0;
            double currVal = curr.insulin_mU_min ?? 0.0;

            bool prevIsBasal = prevVal > 0 && prevVal <= basalThreshold;
            bool currIsBasal = currVal > 0 && currVal <= basalThreshold;

            if (prevIsBasal && !currIsBasal && currVal <= basalThreshold)
            {
                var ts = baseDt.AddMinutes(curr.absolute_minute!.Value);
                basals.Add((ts, 0.0));
            }

            if (currIsBasal && !prevIsBasal && prevVal == 0.0)
            {
                var ts = baseDt.AddMinutes(curr.absolute_minute!.Value - 1);
                basals.Add((ts, 0.0));
            }
        }

        return basals.GroupBy(b => b.Timestamp).Select(g => (g.Key, g.First().Units)).ToList();
    }

    /*
    private static List<DiabetesApi.Models.Exercise> GetExerciseEvents(
        List<ParquetRow> patientRows,
        DateTime baseDt,
        int dbPatientId)
    {
        var exercises = new List<DiabetesApi.Models.Exercise>();
        bool inBout = false;
        DateTime boutStart = default;
        int boutLength = 0;
        string intensity = "low";

        foreach (var row in patientRows)
        {
            string overlay = row.exercise_overlay?.ToString()?.ToLower() ?? "none";
            bool isActive = !string.IsNullOrEmpty(overlay) && overlay != "none";

            if (isActive)
            {
                if (!inBout)
                {
                    inBout = true;
                    boutStart = baseDt.AddMinutes(row.absolute_minute!.Value);
                    boutLength = 1;
                    intensity = ResolveIntensity(row.exercise_type ?? overlay);
                }
                else
                {
                    boutLength++;
                }
            }
            else
            {
                if (inBout)
                {
                    exercises.Add(new DiabetesApi.Models.Exercise
                    {
                        PatientId = dbPatientId,
                        Timestamp = boutStart,
                        DurationMinutes = boutLength,
                        Intensity = intensity
                    });
                    inBout = false;
                    boutLength = 0;
                }
            }
        }
        if (inBout)
        {
            exercises.Add(new DiabetesApi.Models.Exercise
            {
                PatientId = dbPatientId,
                Timestamp = boutStart,
                DurationMinutes = boutLength,
                Intensity = intensity
            });
        }
        return exercises;
    }

    private static string ResolveIntensity(string exType)
    {
        string t = exType.ToLower();
        if (t.Contains("high") || t.Contains("intense") || t.Contains("vigorous")) return "high";
        if (t.Contains("medium") || t.Contains("moderate")) return "medium";
        return "low";
    }
    */

    /*
    private static List<DiabetesApi.Models.Anomaly> GetAnomalyDetections(
        List<ParquetRow> patientRows,
        DateTime baseDt,
        int dbPatientId)
    {
        var anomalies = new List<DiabetesApi.Models.Anomaly>();
        bool prevMissed = false;
        bool prevLate = false;

        foreach (var row in patientRows)
        {
            bool missed = row.had_missed_bolus ?? false;
            if (missed && !prevMissed)
            {
                anomalies.Add(new DiabetesApi.Models.Anomaly
                {
                    PatientId = dbPatientId,
                    AnomalyType = "missed_bolus",
                    Confidence = 0.95,
                    Description = $"Missed bolus detected (scenario {row.scenario_id})",
                    IsAcknowledged = false,
                    DetectedAt = baseDt.AddMinutes(row.absolute_minute!.Value)
                });
            }
            prevMissed = missed;

            bool late = (row.n_late_boluses ?? 0) > 0;
            if (late && !prevLate)
            {
                anomalies.Add(new DiabetesApi.Models.Anomaly
                {
                    PatientId = dbPatientId,
                    AnomalyType = "late_bolus",
                    Confidence = 0.90,
                    Description = $"{row.n_late_boluses} late bolus(es) detected (scenario {row.scenario_id})",
                    IsAcknowledged = false,
                    DetectedAt = baseDt.AddMinutes(row.absolute_minute!.Value)
                });
            }
            prevLate = late;
        }
        return anomalies;
    }
    */
}
