"use client";

import { useState, useRef, useCallback } from "react";
import { format } from "date-fns";
import { uploadCsv, uploadGlookoZip } from "@/models/api";
import styles from "./DataUploader.module.css";

interface DataUploaderProps {
  patientId: number;
  onUploadSuccess?: () => void;
}

type UploadResult = {
  success: boolean;
  message: string;
  stats?: { glucose: number; meal: number; insulin: number };
  dateFrom?: string | null;
  dateTo?: string | null;
} | null;

type FileType = "csv" | "zip" | null;

function detectFileType(file: File): FileType {
  if (file.name.endsWith(".csv")) return "csv";
  if (file.name.endsWith(".zip")) return "zip";
  return null;
}

export default function DataUploader({ patientId, onUploadSuccess }: DataUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [fileType, setFileType] = useState<FileType>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UploadResult>(null);

  const acceptFile = useCallback((f: File) => {
    const type = detectFileType(f);
    setFile(f);
    setFileType(type);
    setResult(null);
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      acceptFile(e.target.files[0]);
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => setIsDragOver(false);

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) acceptFile(dropped);
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !fileType || !patientId) return;

    setUploading(true);
    setResult(null);

    try {
      const res = fileType === "csv"
        ? await uploadCsv(patientId, file)
        : await uploadGlookoZip(patientId, file);

      setResult({
        success: true,
        message: res.message,
        stats: {
          glucose: res.glucose_count,
          meal: res.meal_count,
          insulin: res.insulin_count,
        },
        dateFrom: res.date_from,
        dateTo: res.date_to,
      });
      setFile(null);
      setFileType(null);
      if (inputRef.current) inputRef.current.value = "";
      setTimeout(() => {
        if (onUploadSuccess) onUploadSuccess();
      }, 1500);
    } catch (err: unknown) {
      console.error(err);
      const errMsg =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ||
        `Failed to upload ${fileType === "csv" ? "CSV" : "ZIP"} file`;
      setResult({ success: false, message: errMsg });
    } finally {
      setUploading(false);
    }
  };

  const reset = () => {
    setFile(null);
    setFileType(null);
    setResult(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const badgeLabel =
    fileType === "csv" ? "CSV \u2014 LibreView" : fileType === "zip" ? "ZIP \u2014 Glooko" : null;

  const badgeColor =
    fileType === "csv" ? "var(--primary)" : fileType === "zip" ? "#8b5cf6" : "var(--border)";

  return (
    <>
      <div className={styles.uploaderCard}>
        <h3 style={{
          fontSize: "1.05rem",
          fontWeight: 700,
          marginBottom: "0.75rem",
          color: "var(--text-primary)",
          letterSpacing: "0.01em",
          position: "relative",
          zIndex: 1,
        }}>
          Upload your patient data
        </h3>

        <form onSubmit={handleUpload} style={{ position: "relative", zIndex: 1 }}>
          {/* Hidden file input */}
          <input
            ref={inputRef}
            type="file"
            accept=".csv,.zip"
            onChange={handleFileChange}
            id="unified-file-input"
            style={{ display: "none" }}
          />

          {/* 2/3 drop zone + 1/3 button panel */}
          <div className={styles.uploaderRow}>
            {/* Drop zone — 2/3 */}
            <div
              className={[
                styles.dropZone,
                isDragOver ? styles.dragOver : "",
                file ? styles.hasFile : "",
                fileType === "csv" ? styles.csvType : "",
                fileType === "zip" ? styles.zipType : "",
              ].filter(Boolean).join(" ")}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => inputRef.current?.click()}
            >
              {file ? (
                <>
                  {/* Clear button */}
                  <button
                    type="button"
                    className={styles.clearBtn}
                    onClick={(e) => { e.stopPropagation(); reset(); }}
                    title="Remove file"
                  >
                    ✕
                  </button>

                  {/* Badge */}
                  {badgeLabel && (
                    <div>
                      <span
                        className={styles.fileBadge}
                        style={{
                          background: `${badgeColor}20`,
                          color: badgeColor,
                          border: `1px solid ${badgeColor}55`,
                        }}
                      >
                        {fileType === "csv" ? "📄" : "🗜️"}&nbsp;{badgeLabel}
                      </span>
                    </div>
                  )}

                  {/* Filename */}
                  <div className={styles.fileName} title={file.name}>
                    {file.name}
                  </div>
                  <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginTop: "0.3rem", opacity: 0.7 }}>
                    {(file.size / (1024 * 1024)).toFixed(2)} MB &middot; click to change
                  </div>
                </>
              ) : (
                <>
                  <span className={styles.fileIcon}>
                    {isDragOver ? "📂" : "☁️"}
                  </span>
                  <div className={styles.dropHint}>
                    {isDragOver ? "Drop it here!" : "Drag & drop or click to browse"}
                  </div>
                  <div className={styles.dropSub}>Accepts .csv (LibreView) and .zip (Glooko)</div>
                </>
              )}
            </div>

            {/* Button panel — 1/3, always mounted, animated via CSS */}
            <div className={`${styles.uploadPanel} ${file && fileType ? styles.uploadPanelVisible : ""}`}>
              <button
                type="submit"
                disabled={!file || !fileType || uploading}
                className={`${styles.uploadBtn} ${fileType === "csv" ? styles.csvBtn : styles.zipBtn}`}
              >
                {uploading ? (
                  <><span className={styles.spinner} /> Importing&hellip;</>
                ) : (
                  <>{fileType === "csv" ? "📤" : "📦"} Upload &amp; Parse</>
                )}
              </button>
              <span className={styles.uploadHint}>
                {fileType === "csv"
                  ? "Will parse LibreView CSV and import readings"
                  : "Will extract and import Glooko ZIP archive"}
              </span>
            </div>
          </div>
        </form>

        {/* Result banner */}
        {result && (
          <div className={`${styles.resultBanner} ${result.success ? styles.successBanner : styles.errorBanner}`}>
            <button
              className={styles.bannerCloseBtn}
              type="button"
              onClick={() => setResult(null)}
              aria-label="Dismiss"
            >
              ✕
            </button>
            <div style={{ fontWeight: 700, marginBottom: result.stats ? "0.35rem" : 0 }}>
              {result.success ? "✓ " : "✕ "}{result.message}
            </div>
            {result.success && result.stats && (
              <div style={{ fontSize: "0.85rem", opacity: 0.85 }}>
                <div>
                  Imported <strong>{result.stats.glucose}</strong> glucose readings,{" "}
                  <strong>{result.stats.meal}</strong> carb entries,{" "}
                  <strong>{result.stats.insulin}</strong> insulin doses.
                </div>
                {(result.dateFrom || result.dateTo) && (
                  <div style={{ marginTop: "0.3rem", opacity: 0.8 }}>
                    {"from "}
                    {result.dateFrom
                      ? format(new Date(result.dateFrom), "EEE, MMM d yyyy")
                      : "–"}
                    {" to "}
                    {result.dateTo
                      ? format(new Date(result.dateTo), "EEE, MMM d yyyy")
                      : "–"}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
