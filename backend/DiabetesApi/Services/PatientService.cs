using System;

namespace DiabetesApi.Services;

/// <summary>Service for handling patient-related business logic.</summary>
public class PatientService
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
}
