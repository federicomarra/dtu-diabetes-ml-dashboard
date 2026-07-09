"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { getPatientByExternalId, createPatient } from "@/models/api";
import { clearSession, saveSession } from "@/models/session";
import styles from "./patient.module.css";

export default function PatientLoginPortal() {
  const router = useRouter();
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [activeTab, setActiveTab] = useState<"login" | "register">("login");

  // Login form state
  const [loginId, setLoginId] = useState("");
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);

  // Register form state
  const [registerId, setRegisterId] = useState("");
  const [registerName, setRegisterName] = useState("");
  const [registerDob, setRegisterDob] = useState("");
  const [registerError, setRegisterError] = useState("");
  const [registerLoading, setRegisterLoading] = useState(false);

  // 1. Check if user is already logged in. The saved ID is only a hint — the patient it
  // names may be gone (DB reset, deleted row), and redirecting to it unchecked strands the
  // user on "Patient Not Found" with no way back to this form. Verify, then clear if stale.
  useEffect(() => {
    let cancelled = false;
    const savedId = localStorage.getItem("logged_in_patient_id");
    if (savedId) {
      getPatientByExternalId(savedId)
        .then(() => {
          if (!cancelled) router.replace(`/patient/${savedId}`);
        })
        .catch(() => {
          clearSession();
          if (!cancelled) setCheckingAuth(false);
        });
      return () => {
        cancelled = true;
      };
    } else {
      setCheckingAuth(false);
    }
  }, [router]);

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!loginId.trim()) return;

    setLoginError("");
    setLoginLoading(true);

    try {
      const patient = await getPatientByExternalId(loginId.trim());
      saveSession(patient.external_id, patient.name);
      router.push(`/patient/${patient.external_id}`);
    } catch (err: unknown) {
      console.error(err);
      const status = (err as { response?: { status?: number } })?.response?.status;
      const errorMsg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error;
      if (status === 404) {
        setLoginError("Patient ID not found. Please double check the ID or register a new user.");
      } else {
        setLoginError(errorMsg || "An error occurred during log in.");
      }
    } finally {
      setLoginLoading(false);
    }
  };

  const handleRegisterSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!registerId.trim() || !registerName.trim()) return;

    setRegisterError("");
    setRegisterLoading(true);

    try {
      const newPatient = await createPatient({
        external_id: registerId.trim(),
        name: registerName.trim(),
        date_of_birth: registerDob || undefined,
      });

      saveSession(newPatient.external_id, newPatient.name);
      router.push(`/patient/${newPatient.external_id}`);
    } catch (err: unknown) {
      console.error(err);
      const status = (err as { response?: { status?: number } })?.response?.status;
      const errorMsg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error;
      if (status === 409) {
        setRegisterError(errorMsg || "That Patient ID is taken. Please choose a different one.");
      } else {
        setRegisterError(errorMsg || "Could not create the patient. Please try again.");
      }
    } finally {
      setRegisterLoading(false);
    }
  };

  if (checkingAuth) {
    return (
      <div className={styles.loadingSpinner}>
        <p style={{ color: "var(--text-secondary)" }}>Checking authentication...</p>
      </div>
    );
  }

  return (
    <div className={styles.loginContainer}>
      <div className={styles.loginCard}>
        <div className={styles.tabs}>
          <button
            onClick={() => {
              setActiveTab("login");
              setLoginError("");
              setRegisterError("");
            }}
            className={`${styles.tabBtn} ${activeTab === "login" ? styles.tabBtnActive : ""}`}
          >
            Log In
          </button>
          <button
            onClick={() => {
              setActiveTab("register");
              setLoginError("");
              setRegisterError("");
            }}
            className={`${styles.tabBtn} ${activeTab === "register" ? styles.tabBtnActive : ""}`}
          >
            Create User
          </button>
        </div>

        {activeTab === "login" ? (
          <form onSubmit={handleLoginSubmit}>
            <div className={styles.formGroup}>
              <label htmlFor="login-id" className={styles.formLabel}>
                Patient External ID
              </label>
              <input
                type="text"
                id="login-id"
                placeholder="e.g. SIM_000001"
                value={loginId}
                onChange={(e) => setLoginId(e.target.value)}
                className={styles.formInput}
                required
              />
              {loginError && <span className={styles.errorText}>{loginError}</span>}
            </div>
            <button type="submit" disabled={loginLoading} className={styles.submitBtn}>
              {loginLoading ? "Logging in..." : "Enter Patient Portal"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleRegisterSubmit}>
            <div className={styles.formGroup}>
              <label htmlFor="register-id" className={styles.formLabel}>
                Desired Patient ID (External ID)
              </label>
              <input
                type="text"
                id="register-id"
                placeholder="e.g. john72"
                value={registerId}
                onChange={(e) => setRegisterId(e.target.value)}
                className={styles.formInput}
                required
              />
            </div>
            <div className={styles.formGroup}>
              <label htmlFor="register-name" className={styles.formLabel}>
                Full Name
              </label>
              <input
                type="text"
                id="register-name"
                placeholder="e.g. John Doe"
                value={registerName}
                onChange={(e) => setRegisterName(e.target.value)}
                className={styles.formInput}
                required
              />
            </div>
            <div className={styles.formGroup}>
              <label htmlFor="register-dob" className={styles.formLabel}>
                Date of Birth
              </label>
              <input
                type="date"
                id="register-dob"
                value={registerDob}
                onChange={(e) => setRegisterDob(e.target.value)}
                className={styles.formInput}
              />
              {registerError && <span className={styles.errorText}>{registerError}</span>}
            </div>
            <button type="submit" disabled={registerLoading} className={styles.submitBtn}>
              {registerLoading ? "Creating..." : "Create & Enter Portal"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
