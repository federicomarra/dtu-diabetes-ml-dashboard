"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import styles from "./NavBar.module.css";

export default function NavBar() {
  const { unit, toggleUnit } = useGlucoseUnit();
  const pathname = usePathname();
  const router = useRouter();

  const [loggedInId, setLoggedInId] = useState<string | null>(null);
  const [loggedInName, setLoggedInName] = useState<string | null>(null);

  const syncLoginState = () => {
    if (typeof window !== "undefined") {
      setLoggedInId(localStorage.getItem("logged_in_patient_id"));
      setLoggedInName(localStorage.getItem("logged_in_patient_name"));
    }
  };

  useEffect(() => {
    syncLoginState();
    window.addEventListener("storage", syncLoginState);
    return () => {
      window.removeEventListener("storage", syncLoginState);
    };
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("logged_in_patient_id");
    localStorage.removeItem("logged_in_patient_name");
    syncLoginState();
    window.dispatchEvent(new Event("storage"));
    router.push("/patient");
  };

  const isDoctorRoute = pathname.startsWith("/doctor");
  const isPatientRoute = pathname.startsWith("/patient");

  return (
    <nav className={styles.nav}>
      <div className={styles.left}>
        <span className={styles.brand}>
          <Link href="/" className={styles.brandLink}>
            DTU Diabetes ML Dashboard
          </Link>
        </span>
      </div>

      <div className={styles.right}>
        <button
          id="unit-toggle"
          className={styles.unitToggle}
          onClick={toggleUnit}
          title="Switch glucose unit"
        >
          <span className={unit === "mmol/L" ? styles.unitActive : styles.unitInactive}>
            mmol/L
          </span>
          <span className={styles.unitDivider}>|</span>
          <span className={unit === "mg/dL" ? styles.unitActive : styles.unitInactive}>
            mg/dL
          </span>
        </button>

        {/* Doctor portal link only visible if we are in doctor routes */}
        {isDoctorRoute && (
          <Link href="/doctor" className={styles.navLink}>
            Doctor View
          </Link>
        )}

        {/* Patient portal links only visible if we are in patient routes */}
        {isPatientRoute && (
          <>
            {loggedInId ? (
              <div className={styles.patientInfo}>
                <span>Logged in: <strong>{loggedInName || loggedInId}</strong></span>
                <button onClick={handleLogout} className={styles.logoutBtn}>
                  Logout
                </button>
              </div>
            ) : (
              <Link href="/patient" className={styles.navLink}>
                Login
              </Link>
            )}
          </>
        )}
      </div>
    </nav>
  );
}
