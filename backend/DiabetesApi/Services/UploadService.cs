using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using DiabetesApi.Data;
using DiabetesApi.Models;
using Parquet.Serialization;

namespace DiabetesApi.Services;

/// <summary>
/// Service for parsing and ingesting patient clinical data from different file formats.
/// </summary>
public class UploadService(AppDbContext db, PatientService patientService)
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
    }

    public class IngestionPayload
    {
        public List<Glucose> Glucoses { get; set; } = new();
        public List<Meal> Meals { get; set; } = new();
        public List<Insulin> Insulins { get; set; } = new();
    }

    public class UploadResult
    {
        public int PatientsCount { get; set; }
        public int GlucoseCount { get; set; }
        public int MealCount { get; set; }
        public int InsulinCount { get; set; }
        public DateTime? DateFrom { get; set; }
        public DateTime? DateTo { get; set; }
    }

    /// <summary>
    /// Processes a Parquet simulation file and creates/updates patient cohort records.
    /// </summary>
    public async Task<UploadResult> ProcessParquetUploadAsync(Stream stream)
    {
        IList<ParquetRow> rows;
        try
        {
            var result = await ParquetSerializer.DeserializeAsync<ParquetRow>(stream);
            rows = result.Data;
        }
        catch (Exception ex)
        {
            throw new ArgumentException($"Failed to deserialize Parquet file: {ex.Message}", ex);
        }

        if (rows == null || rows.Count == 0)
        {
            throw new ArgumentException("Parquet file contains no rows.");
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
                var newPat = new Patient
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

        var patientDataMap = new Dictionary<int, IngestionPayload>();
        bool hasAnnounced = rows.Any(r => r.cho_mg_announced.HasValue);

        foreach (var grp in patientsGrouped)
        {
            string formattedId = int.TryParse(grp.Key, out int pidInt) ? pidInt.ToString("D6") : grp.Key;
            string extId = $"SIM_{formattedId}";
            if (!patientIdMap.TryGetValue(extId, out int dbPatientId)) continue;

            var patientRows = grp.Where(r => r.absolute_minute.HasValue).OrderBy(r => r.absolute_minute!.Value).ToList();
            var payload = new IngestionPayload();

            // 1. Glucose readings
            foreach (var row in patientRows)
            {
                if (!row.blood_glucose.HasValue) continue;

                var ts = DateTime.SpecifyKind(baseDt.AddMinutes(row.absolute_minute!.Value), DateTimeKind.Utc);
                double mmol = Math.Round(row.blood_glucose.Value, 1);
                string status = GetGlucoseStatus(mmol);

                payload.Glucoses.Add(new Glucose
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
                payload.Meals.Add(new Meal
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
                payload.Insulins.Add(new Insulin
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
                payload.Insulins.Add(new Insulin
                {
                    PatientId = dbPatientId,
                    Timestamp = ts,
                    Units = b.Units,
                    EventType = "basal"
                });
            }

            patientDataMap[dbPatientId] = payload;
        }

        return await IngestDataInternalAsync(patientDataMap);
    }

    /// <summary>
    /// Processes a Libre CSV file for a patient.
    /// </summary>
    public async Task<UploadResult> ProcessCsvUploadAsync(int patientId, Stream stream)
    {
        using var reader = new StreamReader(stream);
        string? headerLine = null;
        string? line;
        while ((line = await reader.ReadLineAsync()) != null)
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            if (line.StartsWith("Glucose Data")) continue; // Skip metadata header line
            headerLine = line;
            break;
        }

        if (headerLine == null)
            throw new ArgumentException("CSV is empty or missing header");

        char delimiter = ',';
        if (headerLine.Contains(';') && !headerLine.Contains(','))
        {
            delimiter = ';';
        }

        var headers = ParseCsvLine(headerLine, delimiter);
        int timestampIdx = headers.IndexOf("Device Timestamp");
        int recordTypeIdx = headers.IndexOf("Record Type");
        int historicGlucoseIdx = headers.IndexOf("Historic Glucose mmol/L");
        int scanGlucoseIdx = headers.IndexOf("Scan Glucose mmol/L");
        int rapidInsulinIdx = headers.IndexOf("Rapid-Acting Insulin (units)");
        int longInsulinIdx = headers.IndexOf("Long-Acting Insulin Value (units)");
        int carbsIdx = headers.IndexOf("Carbohydrates (grams)");

        if (timestampIdx == -1 || recordTypeIdx == -1)
        {
            throw new ArgumentException("Required columns 'Device Timestamp' or 'Record Type' not found in CSV headers.");
        }

        var payload = new IngestionPayload();

        string[] formats = {
            "dd-MM-yyyy HH:mm",
            "dd-MM-yyyy HH:mm:ss",
            "yyyy-MM-dd HH:mm:ss",
            "yyyy-MM-dd HH:mm",
            "yyyy-MM-ddTHH:mm:ss",
            "dd/MM/yyyy HH:mm",
            "dd/MM/yyyy HH:mm:ss"
        };

        while ((line = await reader.ReadLineAsync()) != null)
        {
            if (string.IsNullOrWhiteSpace(line)) continue;

            var row = ParseCsvLine(line, delimiter);
            if (row.Count <= timestampIdx || row.Count <= recordTypeIdx) continue;

            string timestampStr = row[timestampIdx];
            if (string.IsNullOrWhiteSpace(timestampStr)) continue;

            if (!DateTime.TryParseExact(timestampStr, formats, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out DateTime parsedTime))
            {
                if (!DateTime.TryParse(timestampStr, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out parsedTime))
                {
                    continue; // skip unparseable timestamps
                }
            }

            DateTime timestampUtc = DateTime.SpecifyKind(parsedTime, DateTimeKind.Utc);

            if (!int.TryParse(row[recordTypeIdx], out int recordType)) continue;

            // 1. Parse Glucose
            double glucoseVal = 0;
            bool hasGlucose = false;
            if (recordType == 0 && historicGlucoseIdx != -1 && historicGlucoseIdx < row.Count && double.TryParse(row[historicGlucoseIdx], NumberStyles.Any, CultureInfo.InvariantCulture, out glucoseVal))
            {
                hasGlucose = true;
            }
            else if (recordType == 1 && scanGlucoseIdx != -1 && scanGlucoseIdx < row.Count && double.TryParse(row[scanGlucoseIdx], NumberStyles.Any, CultureInfo.InvariantCulture, out glucoseVal))
            {
                hasGlucose = true;
            }

            if (hasGlucose)
            {
                string status = GetGlucoseStatus(glucoseVal);

                payload.Glucoses.Add(new Glucose
                {
                    PatientId = patientId,
                    Timestamp = timestampUtc,
                    GlucoseMmoll = glucoseVal,
                    Source = "libre",
                    Status = status
                });
            }

            // 2. Parse Carbs
            if (recordType == 5 && carbsIdx != -1 && carbsIdx < row.Count && double.TryParse(row[carbsIdx], NumberStyles.Any, CultureInfo.InvariantCulture, out double carbsVal))
            {
                payload.Meals.Add(new Meal
                {
                    PatientId = patientId,
                    Timestamp = timestampUtc,
                    Carbs = carbsVal,
                    MealType = null
                });
            }

            // 3. Parse Insulin (Rapid-acting/bolus)
            if (rapidInsulinIdx != -1 && rapidInsulinIdx < row.Count && double.TryParse(row[rapidInsulinIdx], NumberStyles.Any, CultureInfo.InvariantCulture, out double rapidInsulinVal))
            {
                payload.Insulins.Add(new Insulin
                {
                    PatientId = patientId,
                    Timestamp = timestampUtc,
                    Units = rapidInsulinVal,
                    EventType = "bolus"
                });
            }

            // 4. Parse Insulin (Long-acting/basal)
            if (longInsulinIdx != -1 && longInsulinIdx < row.Count && double.TryParse(row[longInsulinIdx], NumberStyles.Any, CultureInfo.InvariantCulture, out double longInsulinVal))
            {
                payload.Insulins.Add(new Insulin
                {
                    PatientId = patientId,
                    Timestamp = timestampUtc,
                    Units = longInsulinVal,
                    EventType = "basal"
                });
            }
        }

        var patientDataMap = new Dictionary<int, IngestionPayload> { { patientId, payload } };
        return await IngestDataInternalAsync(patientDataMap);
    }

    /// <summary>
    /// Processes a Glooko ZIP file for a patient.
    /// </summary>
    public async Task<UploadResult> ProcessGlookoZipUploadAsync(int patientId, Stream stream)
    {
        using var archive = new ZipArchive(stream, ZipArchiveMode.Read);
        var payload = new IngestionPayload();

        // Glooko date format: dd/MM/yyyy HH:mm
        string[] glookoFormats = {
            "dd/MM/yyyy HH:mm",
            "dd/MM/yyyy HH:mm:ss",
            "dd-MM-yyyy HH:mm",
            "dd-MM-yyyy HH:mm:ss"
        };

        foreach (var entry in archive.Entries)
        {
            if (entry.Length == 0) continue;

            string entryName = entry.Name.ToLowerInvariant();
            string entryFullName = entry.FullName.Replace('\\', '/');
            bool inInsulinDataFolder = entryFullName.Contains("Insulin data/", StringComparison.OrdinalIgnoreCase)
                || entryFullName.Contains("Insulin_data/", StringComparison.OrdinalIgnoreCase);

            bool isCgm = entryName.StartsWith("cgm_data") && entryName.EndsWith(".csv");
            bool isBg = entryName.StartsWith("bg_data") && entryName.EndsWith(".csv");
            bool isBasal = inInsulinDataFolder && entryName.StartsWith("basal_data") && entryName.EndsWith(".csv");
            bool isBolus = inInsulinDataFolder && entryName.StartsWith("bolus_data") && entryName.EndsWith(".csv");

            if (!isCgm && !isBg && !isBasal && !isBolus) continue;

            using var entryStream = entry.Open();
            using var reader = new StreamReader(entryStream);

            // Skip metadata row 1; row 2 is the column header
            string? firstLine = await reader.ReadLineAsync();
            if (firstLine == null) continue;

            // If row 1 looks like a header already (no 'Nome:' prefix), use it directly
            string? headerLine;
            if (firstLine.StartsWith("Nome:") || firstLine.StartsWith("Name:"))
            {
                headerLine = await reader.ReadLineAsync();
            }
            else
            {
                headerLine = firstLine;
            }

            if (string.IsNullOrWhiteSpace(headerLine)) continue;

            var headers = ParseCsvLine(headerLine, ',');

            int dateIdx = headers.IndexOf("Data e ora");
            if (dateIdx == -1) continue; // can't parse without timestamp column

            if (isCgm)
            {
                int valIdx = headers.IndexOf("Valore glicemia CGM (mmol/l)");
                if (valIdx == -1) continue;

                string? line;
                while ((line = await reader.ReadLineAsync()) != null)
                {
                    if (string.IsNullOrWhiteSpace(line)) continue;
                    var row = ParseCsvLine(line, ',');
                    if (row.Count <= dateIdx || row.Count <= valIdx) continue;

                    if (!TryParseGlookoDate(row[dateIdx], glookoFormats, out DateTime ts)) continue;
                    if (!TryParseGlookoDouble(row[valIdx], out double val)) continue;

                    payload.Glucoses.Add(new Glucose
                    {
                        PatientId = patientId,
                        Timestamp = ts,
                        GlucoseMmoll = val,
                        Source = "glooko_cgm",
                        Status = GetGlucoseStatus(val)
                    });
                }
            }
            else if (isBg)
            {
                int valIdx = headers.IndexOf("Valore glucosio (mmol/l)");
                if (valIdx == -1) continue;

                string? line;
                while ((line = await reader.ReadLineAsync()) != null)
                {
                    if (string.IsNullOrWhiteSpace(line)) continue;
                    var row = ParseCsvLine(line, ',');
                    if (row.Count <= dateIdx || row.Count <= valIdx) continue;

                    if (!TryParseGlookoDate(row[dateIdx], glookoFormats, out DateTime ts)) continue;
                    if (!TryParseGlookoDouble(row[valIdx], out double val)) continue;

                    payload.Glucoses.Add(new Glucose
                    {
                        PatientId = patientId,
                        Timestamp = ts,
                        GlucoseMmoll = val,
                        Source = "glooko_manual",
                        Status = GetGlucoseStatus(val)
                    });
                }
            }
            else if (isBasal)
            {
                int freqIdx = headers.IndexOf("Frequenza");

                string? line;
                while ((line = await reader.ReadLineAsync()) != null)
                {
                    if (string.IsNullOrWhiteSpace(line)) continue;
                    var row = ParseCsvLine(line, ',');
                    if (row.Count <= dateIdx) continue;

                    if (!TryParseGlookoDate(row[dateIdx], glookoFormats, out DateTime ts)) continue;

                    double units = 0.0;
                    if (freqIdx != -1 && freqIdx < row.Count && !string.IsNullOrWhiteSpace(row[freqIdx]))
                        TryParseGlookoDouble(row[freqIdx], out units);

                    payload.Insulins.Add(new Insulin
                    {
                        PatientId = patientId,
                        Timestamp = ts,
                        Units = units,
                        EventType = "basal"
                    });
                }
            }
            else if (isBolus)
            {
                int unitsIdx = headers.IndexOf("Insulina erogata (U)");
                int carbsIdx = headers.IndexOf("Consumo di carboidrati (g)");

                string? line;
                while ((line = await reader.ReadLineAsync()) != null)
                {
                    if (string.IsNullOrWhiteSpace(line)) continue;
                    var row = ParseCsvLine(line, ',');
                    if (row.Count <= dateIdx) continue;

                    if (!TryParseGlookoDate(row[dateIdx], glookoFormats, out DateTime ts)) continue;

                    // Bolus insulin
                    if (unitsIdx != -1 && unitsIdx < row.Count &&
                        TryParseGlookoDouble(row[unitsIdx], out double bolusUnits))
                    {
                        payload.Insulins.Add(new Insulin
                        {
                            PatientId = patientId,
                            Timestamp = ts,
                            Units = bolusUnits,
                            EventType = "bolus"
                        });
                    }

                    // Carbs (only if > 0)
                    if (carbsIdx != -1 && carbsIdx < row.Count &&
                        TryParseGlookoDouble(row[carbsIdx], out double carbs) &&
                        carbs > 0)
                    {
                        payload.Meals.Add(new Meal
                        {
                            PatientId = patientId,
                            Timestamp = ts,
                            Carbs = carbs,
                            MealType = null
                        });
                    }
                }
            }
        }

        var patientDataMap = new Dictionary<int, IngestionPayload> { { patientId, payload } };
        return await IngestDataInternalAsync(patientDataMap);
    }

    /// <summary>
    /// Evaluates glucose levels based on clinical ranges.
    /// </summary>
    public static string GetGlucoseStatus(double val)
    {
        if (val < 3.0) return "very_low";
        if (val < 3.9) return "low";
        if (val > 13.9) return "very_high";
        if (val > 10.0) return "high";
        return "in_range";
    }

    /// <summary>
    /// Shared database ingestion and deduplication function reused across the 3 types of upload.
    /// </summary>
    private async Task<UploadResult> IngestDataInternalAsync(
        Dictionary<int, IngestionPayload> patientDataMap)
    {
        var patientIds = patientDataMap.Keys.ToList();

        // Bulk load existing timestamps for all affected patients to avoid N+1 queries
        var existingGlucoseSet = (await db.Glucoses
            .Where(g => patientIds.Contains(g.PatientId))
            .Select(g => new { g.PatientId, g.Timestamp })
            .ToListAsync())
            .Select(x => (x.PatientId, x.Timestamp))
            .ToHashSet();

        var existingMealSet = (await db.Meals
            .Where(m => patientIds.Contains(m.PatientId))
            .Select(m => new { m.PatientId, m.Timestamp })
            .ToListAsync())
            .Select(x => (x.PatientId, x.Timestamp))
            .ToHashSet();

        var existingInsulinSet = (await db.Insulins
            .Where(i => patientIds.Contains(i.PatientId))
            .Select(i => new { i.PatientId, i.Timestamp, i.EventType })
            .ToListAsync())
            .Select(x => (x.PatientId, x.Timestamp, x.EventType))
            .ToHashSet();

        var glucosesToInsert = new List<Glucose>();
        var mealsToInsert = new List<Meal>();
        var insulinsToInsert = new List<Insulin>();

        foreach (var (patientId, payload) in patientDataMap)
        {
            foreach (var g in payload.Glucoses)
            {
                if (!existingGlucoseSet.Contains((patientId, g.Timestamp)))
                {
                    glucosesToInsert.Add(g);
                    existingGlucoseSet.Add((patientId, g.Timestamp));
                }
            }

            foreach (var m in payload.Meals)
            {
                if (!existingMealSet.Contains((patientId, m.Timestamp)))
                {
                    mealsToInsert.Add(m);
                    existingMealSet.Add((patientId, m.Timestamp));
                }
            }

            foreach (var ins in payload.Insulins)
            {
                if (!existingInsulinSet.Contains((patientId, ins.Timestamp, ins.EventType)))
                {
                    insulinsToInsert.Add(ins);
                    existingInsulinSet.Add((patientId, ins.Timestamp, ins.EventType));
                }
            }
        }

        try
        {
            db.ChangeTracker.AutoDetectChangesEnabled = false;

            if (glucosesToInsert.Count > 0) db.Glucoses.AddRange(glucosesToInsert.OrderBy(g => g.Timestamp));
            if (mealsToInsert.Count > 0) db.Meals.AddRange(mealsToInsert.OrderBy(m => m.Timestamp));
            if (insulinsToInsert.Count > 0) db.Insulins.AddRange(insulinsToInsert.OrderBy(i => i.Timestamp));

            // Populate histories table for each patient
            foreach (var patientId in patientIds)
            {
                var patGlucoses = glucosesToInsert.Where(g => g.PatientId == patientId).ToList();
                var patMeals = mealsToInsert.Where(m => m.PatientId == patientId).ToList();
                var patInsulins = insulinsToInsert.Where(i => i.PatientId == patientId).ToList();

                await patientService.SyncHistoriesAsync(patientId, patGlucoses, patMeals, patInsulins);
            }

            db.ChangeTracker.DetectChanges();
            await db.SaveChangesAsync();
        }
        finally
        {
            db.ChangeTracker.AutoDetectChangesEnabled = true;
        }

        var allTimestamps = glucosesToInsert.Select(g => g.Timestamp)
            .Concat(mealsToInsert.Select(m => m.Timestamp))
            .Concat(insulinsToInsert.Select(i => i.Timestamp))
            .ToList();

        return new UploadResult
        {
            PatientsCount = patientIds.Count,
            GlucoseCount = glucosesToInsert.Count,
            MealCount = mealsToInsert.Count,
            InsulinCount = insulinsToInsert.Count,
            DateFrom = allTimestamps.Count > 0 ? allTimestamps.Min() : null,
            DateTo = allTimestamps.Count > 0 ? allTimestamps.Max() : null
        };
    }

    // ── Helper parsing methods ──────────────────────────────────────────────

    private static List<string> ParseCsvLine(string line, char delimiter)
    {
        var result = new List<string>();
        var currentToken = new System.Text.StringBuilder();
        bool inQuotes = false;
        for (int i = 0; i < line.Length; i++)
        {
            char c = line[i];
            if (c == '"')
            {
                inQuotes = !inQuotes;
            }
            else if (c == delimiter && !inQuotes)
            {
                result.Add(currentToken.ToString().Trim());
                currentToken.Clear();
            }
            else
            {
                currentToken.Append(c);
            }
        }
        result.Add(currentToken.ToString().Trim());
        return result;
    }

    private static bool TryParseGlookoDate(string raw, string[] formats, out DateTime result)
    {
        if (DateTime.TryParseExact(raw, formats, CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeLocal | DateTimeStyles.AdjustToUniversal, out result))
            return true;
        if (DateTime.TryParse(raw, CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeLocal | DateTimeStyles.AdjustToUniversal, out result))
            return true;
        return false;
    }

    private static bool TryParseGlookoDouble(string raw, out double result)
    {
        if (string.IsNullOrWhiteSpace(raw)) { result = 0; return false; }
        string normalised = raw.Replace(',', '.');
        return double.TryParse(normalised, NumberStyles.Any, CultureInfo.InvariantCulture, out result);
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
}
