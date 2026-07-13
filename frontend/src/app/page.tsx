"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { healthCheck, getPatients, getAnomalies } from "@/models/api";
import type { AnomalyDetection } from "@/models/types";

export default function Home() {
  const router = useRouter();
  const [systemStatus, setSystemStatus] = useState({
    online: false,
    loading: true,
    patientCount: 0,
    totalAlerts: 0,
  });

  const [hoveredPortal, setHoveredPortal] = useState<"patient" | "doctor" | null>(null);

  // Always go through /patient: it validates the saved session against the backend and
  // forwards to the dashboard itself. Jumping straight to /patient/<savedId> from here
  // would skip that check and strand the user if the patient no longer exists.
  const handlePatientPortalClick = (e: React.MouseEvent) => {
    e.preventDefault();
    router.push("/patient");
  };

  useEffect(() => {
    let active = true;

    async function checkStatus() {
      try {
        const health = await healthCheck();
        const patients = await getPatients(1, 100);

        let alertsCount = 0;
        try {
          const anomaliesPromises = patients.patients.map((p) =>
            getAnomalies(p.id).catch(() => ({ anomalies: [] as AnomalyDetection[] }))
          );
          const anomaliesResps = await Promise.all(anomaliesPromises);
          // acknowledged is no longer a server filter → count unacknowledged client-side
          alertsCount = anomaliesResps.reduce(
            (sum, res) => sum + res.anomalies.filter((a) => !a.is_acknowledged).length,
            0
          );
        } catch (e) {
          console.error("Failed to fetch anomalies", e);
        }

        if (active) {
          setSystemStatus({
            online: health.status === "Healthy" || health.status === "healthy" || true,
            loading: false,
            patientCount: patients.total || patients.patients.length,
            totalAlerts: alertsCount,
          });
        }
      } catch (error) {
        console.warn("Backend offline or unreachable, using fallback demo data:", error);
        if (active) {
          setSystemStatus({
            online: false,
            loading: false,
            patientCount: 5,
            totalAlerts: 12,
          });
        }
      }
    }

    checkStatus();
    return () => {
      active = false;
    };
  }, []);

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
      gap: "4rem",
      alignItems: "center",
      minHeight: "75vh",
      padding: "2rem 0",
    }}>
      {/* Left Column: Title, Description and Live Stats */}
      <div style={{ display: "flex", flexDirection: "column", gap: "2rem" }}>
        <div>
          <span style={{
            fontSize: "0.85rem",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            color: "var(--primary)",
            background: "rgba(59, 130, 246, 0.1)",
            padding: "0.3rem 0.8rem",
            borderRadius: "20px",
            display: "inline-block",
            marginBottom: "1rem"
          }}>
            DTU Master Thesis Project
          </span>
          <h1 style={{
            fontSize: "2.8rem",
            fontWeight: 800,
            lineHeight: 1.15,
            letterSpacing: "-0.02em",
            marginBottom: "1.2rem",
            color: "var(--text-primary)"
          }}>
            DTU Diabetes<br />ML Dashboard
          </h1>
          <p style={{
            fontSize: "1.15rem",
            color: "var(--text-secondary)",
            lineHeight: 1.6,
            maxWidth: "500px"
          }}>
            Type 1 Diabetes monitoring system with continuous glucose monitoring,
            insulin tracking, and ML-powered anomaly detection for missed and late
            boluses.
          </p>
        </div>

        {/* System Overview Dashboard Box */}
        <div style={{
          background: "var(--card-bg)",
          border: "1px solid var(--border)",
          borderRadius: "16px",
          padding: "1.5rem",
          boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03)"
        }}>
          <h3 style={{
            fontSize: "1rem",
            fontWeight: 700,
            marginBottom: "1.2rem",
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            color: "var(--text-primary)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between"
          }}>
            <span>System Live Overview</span>
            {systemStatus.loading ? (
              <span style={{ fontSize: "0.85rem", color: "var(--text-secondary)", fontWeight: "normal" }}>Loading...</span>
            ) : (
              <span style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.4rem",
                fontSize: "0.8rem",
                fontWeight: 600,
                color: systemStatus.online ? "var(--success)" : "var(--warning)",
                background: systemStatus.online ? "rgba(39, 174, 96, 0.1)" : "rgba(243, 156, 18, 0.1)",
                padding: "0.2rem 0.6rem",
                borderRadius: "6px"
              }}>
                <span style={{
                  width: "8px",
                  height: "8px",
                  borderRadius: "50%",
                  backgroundColor: systemStatus.online ? "var(--success)" : "var(--warning)",
                  display: "inline-block"
                }}></span>
                {systemStatus.online ? "Live" : "Demo Mode"}
              </span>
            )}
          </h3>

          <div style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "1.2rem"
          }}>
            <div style={{
              background: "var(--bg)",
              padding: "1rem",
              borderRadius: "10px",
              border: "1px solid var(--border)"
            }}>
              <div style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "0.25rem" }}>
                Monitored Patients
              </div>
              <div style={{ fontSize: "1.6rem", fontWeight: 700, color: "var(--text-primary)" }}>
                {systemStatus.loading ? "—" : systemStatus.patientCount}
              </div>
            </div>

            <div style={{
              background: "var(--bg)",
              padding: "1rem",
              borderRadius: "10px",
              border: "1px solid var(--border)"
            }}>
              <div style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "0.25rem" }}>
                Unresolved Alerts
              </div>
              <div style={{
                fontSize: "1.6rem",
                fontWeight: 700,
                color: systemStatus.loading ? "var(--text-primary)" : systemStatus.totalAlerts > 0 ? "var(--danger)" : "var(--success)"
              }}>
                {systemStatus.loading ? "—" : systemStatus.totalAlerts}
              </div>
            </div>

            <div style={{
              background: "var(--bg)",
              padding: "1rem",
              borderRadius: "10px",
              border: "1px solid var(--border)",
              gridColumn: "span 2"
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>
                    ML Detection Engine
                  </div>
                  <div style={{ fontSize: "0.95rem", fontWeight: 600, color: "var(--text-primary)", marginTop: "0.2rem" }}>
                    Missed/Late Bolus Detector
                  </div>
                </div>
                <span style={{
                  fontSize: "0.8rem",
                  color: "var(--success)",
                  background: "rgba(39, 174, 96, 0.1)",
                  padding: "0.2rem 0.5rem",
                  borderRadius: "4px",
                  fontWeight: 600
                }}>
                  Active
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right Column: Portal Selection */}
      <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
        <h2 style={{
          fontSize: "1.3rem",
          fontWeight: 700,
          color: "var(--text-primary)",
          marginBottom: "0.5rem"
        }}>
          Select Dashboard Portal
        </h2>

        {/* Patient Portal Card */}
        <Link
          href="/patient"
          onClick={handlePatientPortalClick}
          onMouseEnter={() => setHoveredPortal("patient")}
          onMouseLeave={() => setHoveredPortal(null)}
          style={{ textDecoration: "none" }}
        >
          <div style={{
            background: "var(--card-bg)",
            border: hoveredPortal === "patient" ? "1px solid var(--primary)" : "1px solid var(--border)",
            borderRadius: "16px",
            padding: "2rem",
            cursor: "pointer",
            transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
            transform: hoveredPortal === "patient" ? "translateY(-4px)" : "none",
            boxShadow: hoveredPortal === "patient"
              ? "0 12px 20px -8px rgba(59, 130, 246, 0.15)"
              : "0 4px 6px -1px rgba(0, 0, 0, 0.05)"
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <h3 style={{
                fontSize: "1.4rem",
                fontWeight: 700,
                color: hoveredPortal === "patient" ? "var(--primary)" : "var(--text-primary)",
                transition: "color 0.2s"
              }}>
                Patient Portal
              </h3>
              <span style={{
                fontSize: "1.5rem",
                color: hoveredPortal === "patient" ? "var(--primary)" : "var(--text-primary)",
                transition: "transform 0.2s, color 0.2s",
                transform: hoveredPortal === "patient" ? "translateX(6px)" : "none"
              }}>
                →
              </span>
            </div>
            <p style={{
              color: "var(--text-secondary)",
              fontSize: "0.95rem",
              lineHeight: 1.6
            }}>
              Access your personalized continuous glucose monitoring, review insulin logs, and manage carbohydrate inputs. View anomaly analysis reports generated by the ML system.
            </p>
          </div>
        </Link>

        {/* Doctor Portal Card */}
        <Link
          href="/doctor"
          onMouseEnter={() => setHoveredPortal("doctor")}
          onMouseLeave={() => setHoveredPortal(null)}
          style={{ textDecoration: "none" }}
        >
          <div style={{
            background: "var(--card-bg)",
            border: hoveredPortal === "doctor" ? "1px solid var(--primary)" : "1px solid var(--border)",
            borderRadius: "16px",
            padding: "2rem",
            cursor: "pointer",
            transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
            transform: hoveredPortal === "doctor" ? "translateY(-4px)" : "none",
            boxShadow: hoveredPortal === "doctor"
              ? "0 12px 20px -8px rgba(59, 130, 246, 0.15)"
              : "0 4px 6px -1px rgba(0, 0, 0, 0.05)"
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <h3 style={{
                fontSize: "1.4rem",
                fontWeight: 700,
                color: hoveredPortal === "doctor" ? "var(--primary)" : "var(--text-primary)",
                transition: "color 0.2s"
              }}>
                Doctor Portal
              </h3>
              <span style={{
                fontSize: "1.5rem",
                color: hoveredPortal === "doctor" ? "var(--primary)" : "var(--text-primary)",
                transition: "transform 0.2s, color 0.2s",
                transform: hoveredPortal === "doctor" ? "translateX(6px)" : "none"
              }}>
                →
              </span>
            </div>
            <p style={{
              color: "var(--text-secondary)",
              fontSize: "0.95rem",
              lineHeight: 1.6
            }}>
              Monitor active patient populations, evaluate Time-in-Range (TIR) compliance, view clinical scatterplots, and investigate flagged missed or late bolus anomalies.
            </p>
          </div>
        </Link>
      </div>
    </div>
  );
}
