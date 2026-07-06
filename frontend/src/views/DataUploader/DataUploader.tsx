"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { uploadCsv, uploadGlookoZip } from "@/models/api";

interface DataUploaderProps {
  patientId: number;
  onUploadSuccess?: () => void;
}

export default function DataUploader({ patientId, onUploadSuccess }: DataUploaderProps) {
  const router = useRouter();

  // CSV Upload states
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<{
    success: boolean;
    message: string;
    stats?: { glucose: number; meal: number; insulin: number };
  } | null>(null);

  // Glooko ZIP upload states
  const [glookoFile, setGlookoFile] = useState<File | null>(null);
  const [glookoUploading, setGlookoUploading] = useState(false);
  const [glookoResult, setGlookoResult] = useState<{
    success: boolean;
    message: string;
    stats?: { glucose: number; meal: number; insulin: number };
  } | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setCsvFile(e.target.files[0]);
      setUploadResult(null);
    }
  };

  const handleCsvUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!csvFile || !patientId) return;

    setUploading(true);
    setUploadResult(null);

    try {
      const res = await uploadCsv(patientId, csvFile);
      setUploadResult({
        success: true,
        message: res.message,
        stats: {
          glucose: res.glucose_count,
          meal: res.meal_count,
          insulin: res.insulin_count,
        },
      });
      setCsvFile(null);
      setTimeout(() => {
        router.refresh();
        if (onUploadSuccess) {
          onUploadSuccess();
        }
      }, 1500);
    } catch (err: unknown) {
      console.error(err);
      const errMsg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error || "Failed to upload CSV file";
      setUploadResult({
        success: false,
        message: errMsg,
      });
    } finally {
      setUploading(false);
    }
  };

  const handleGlookoFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setGlookoFile(e.target.files[0]);
      setGlookoResult(null);
    }
  };

  const handleGlookoUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!glookoFile || !patientId) return;

    setGlookoUploading(true);
    setGlookoResult(null);

    try {
      const res = await uploadGlookoZip(patientId, glookoFile);
      setGlookoResult({
        success: true,
        message: res.message,
        stats: {
          glucose: res.glucose_count,
          meal: res.meal_count,
          insulin: res.insulin_count,
        },
      });
      setGlookoFile(null);
      setTimeout(() => {
        router.refresh();
        if (onUploadSuccess) onUploadSuccess();
      }, 1500);
    } catch (err: unknown) {
      console.error(err);
      const errMsg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error || "Failed to upload Glooko ZIP";
      setGlookoResult({ success: false, message: errMsg });
    } finally {
      setGlookoUploading(false);
    }
  };

  return (
    <>
      {/* CSV Upload Section */}
      <div style={{
        background: "var(--card-bg)",
        border: "1px solid var(--border)",
        borderRadius: "16px",
        padding: "1.5rem",
        marginBottom: "1.5rem",
        boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.05)"
      }}>
        <h3 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "1rem", color: "var(--text-primary)" }}>
          Upload LibreView Data (CSV)
        </h3>
        <form onSubmit={handleCsvUpload} style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "center" }}>
          <div style={{ flex: 1, minWidth: "250px" }}>
            <input
              type="file"
              accept=".csv"
              onChange={handleFileChange}
              id="csv-file-input"
              style={{ display: "none" }}
            />
            <label
              htmlFor="csv-file-input"
              style={{
                display: "block",
                padding: "0.75rem 1rem",
                border: "2px dashed var(--border)",
                borderRadius: "8px",
                textAlign: "center",
                cursor: "pointer",
                color: "var(--text-secondary)",
                background: "var(--bg)",
                transition: "all 0.2s"
              }}
              onMouseOver={(e) => (e.currentTarget.style.borderColor = "var(--primary)")}
              onMouseOut={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
            >
              {csvFile ? `Selected: ${csvFile.name}` : "Click to select a LibreView CSV file"}
            </label>
          </div>
          <button
            type="submit"
            disabled={!csvFile || uploading}
            style={{
              background: !csvFile ? "var(--border)" : "var(--primary)",
              color: "white",
              border: "none",
              padding: "0.75rem 1.5rem",
              borderRadius: "8px",
              fontWeight: 600,
              cursor: !csvFile ? "not-allowed" : "pointer",
              transition: "opacity 0.2s"
            }}
          >
            {uploading ? "Importing..." : "Upload & Parse"}
          </button>
        </form>

        {uploadResult && (
          <div style={{
            marginTop: "1rem",
            padding: "0.75rem 1rem",
            borderRadius: "8px",
            fontSize: "0.9rem",
            background: uploadResult.success ? "rgba(39, 174, 96, 0.1)" : "rgba(231, 76, 60, 0.1)",
            border: `1px solid ${uploadResult.success ? "var(--success)" : "var(--danger)"}`,
            color: uploadResult.success ? "var(--success)" : "var(--danger)"
          }}>
            <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>{uploadResult.message}</div>
            {uploadResult.success && uploadResult.stats && (
              <div style={{ fontSize: "0.85rem", opacity: 0.9 }}>
                Imported: {uploadResult.stats.glucose} glucose readings, {uploadResult.stats.meal} carb entries, {uploadResult.stats.insulin} insulin doses.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Glooko ZIP Upload Section */}
      <div style={{
        background: "var(--card-bg)",
        border: "1px solid var(--border)",
        borderRadius: "16px",
        padding: "1.5rem",
        marginBottom: "1.5rem",
        boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.05)"
      }}>
        <h3 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "1rem", color: "var(--text-primary)" }}>
          Upload Glooko Data (ZIP)
        </h3>
        <form onSubmit={handleGlookoUpload} style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "center" }}>
          <div style={{ flex: 1, minWidth: "250px" }}>
            <input
              type="file"
              accept=".zip"
              onChange={handleGlookoFileChange}
              id="glooko-zip-input"
              style={{ display: "none" }}
            />
            <label
              htmlFor="glooko-zip-input"
              style={{
                display: "block",
                padding: "0.75rem 1rem",
                border: "2px dashed var(--border)",
                borderRadius: "8px",
                textAlign: "center",
                cursor: "pointer",
                color: "var(--text-secondary)",
                background: "var(--bg)",
                transition: "all 0.2s"
              }}
              onMouseOver={(e) => (e.currentTarget.style.borderColor = "var(--primary)")}
              onMouseOut={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
            >
              {glookoFile ? `Selected: ${glookoFile.name}` : "Click to select a Glooko ZIP file"}
            </label>
          </div>
          <button
            type="submit"
            disabled={!glookoFile || glookoUploading}
            style={{
              background: !glookoFile ? "var(--border)" : "var(--primary)",
              color: "white",
              border: "none",
              padding: "0.75rem 1.5rem",
              borderRadius: "8px",
              fontWeight: 600,
              cursor: !glookoFile ? "not-allowed" : "pointer",
              transition: "opacity 0.2s"
            }}
          >
            {glookoUploading ? "Importing..." : "Upload & Parse"}
          </button>
        </form>

        {glookoResult && (
          <div style={{
            marginTop: "1rem",
            padding: "0.75rem 1rem",
            borderRadius: "8px",
            fontSize: "0.9rem",
            background: glookoResult.success ? "rgba(39, 174, 96, 0.1)" : "rgba(231, 76, 60, 0.1)",
            border: `1px solid ${glookoResult.success ? "var(--success)" : "var(--danger)"}`,
            color: glookoResult.success ? "var(--success)" : "var(--danger)"
          }}>
            <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>{glookoResult.message}</div>
            {glookoResult.success && glookoResult.stats && (
              <div style={{ fontSize: "0.85rem", opacity: 0.9 }}>
                Imported: {glookoResult.stats.glucose} glucose readings, {glookoResult.stats.meal} carb entries, {glookoResult.stats.insulin} insulin doses.
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
