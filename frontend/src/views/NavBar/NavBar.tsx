"use client";

import Link from "next/link";
import { useGlucoseUnit } from "@/controllers/GlucoseUnitContext";
import styles from "./NavBar.module.css";

export default function NavBar() {
  const { unit, toggleUnit } = useGlucoseUnit();

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

        <Link href="/patient" className={styles.navLink}>
          Patient View
        </Link>
        <Link href="/doctor" className={styles.navLink}>
          Doctor View
        </Link>
      </div>
    </nav>
  );
}
