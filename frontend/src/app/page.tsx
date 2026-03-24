import Link from "next/link";

export default function Home() {
  return (
    <div style={{ textAlign: "center", paddingTop: "4rem" }}>
      <h1 style={{ fontSize: "2.5rem", fontWeight: 700, marginBottom: "1rem" }}>
        DTU Diabetes ML Dashboard
      </h1>
      <p style={{
        fontSize: "1.1rem",
        color: "var(--text-secondary)",
        maxWidth: "600px",
        margin: "0 auto 2.5rem",
        lineHeight: 1.7,
      }}>
        Type 1 Diabetes monitoring system with continuous glucose monitoring,
        insulin tracking, and ML-powered anomaly detection for missed and late
        boluses.
      </p>

      <div style={{
        display: "flex",
        gap: "1.5rem",
        justifyContent: "center",
        flexWrap: "wrap",
      }}>
        <Link
          href="/patient"
          style={{
            display: "inline-block",
            padding: "0.9rem 2rem",
            background: "var(--primary)",
            color: "#fff",
            borderRadius: "10px",
            fontWeight: 600,
            fontSize: "1rem",
            textDecoration: "none",
            transition: "background 0.2s",
          }}
        >
          Patient Dashboard →
        </Link>
        <Link
          href="/doctor"
          style={{
            display: "inline-block",
            padding: "0.9rem 2rem",
            background: "var(--card-bg)",
            color: "var(--text-primary)",
            border: "1px solid var(--border)",
            borderRadius: "10px",
            fontWeight: 600,
            fontSize: "1rem",
            textDecoration: "none",
            transition: "background 0.2s",
          }}
        >
          Doctor Dashboard →
        </Link>
      </div>

      <div style={{
        marginTop: "4rem",
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
        gap: "1.5rem",
        textAlign: "left",
      }}>
        {[
          {
            icon: "📊",
            title: "Glucose Monitoring",
            desc: "Real-time CGM data visualization with target range indicators",
          },
          {
            icon: "🤖",
            title: "Anomaly Detection",
            desc: "ML-powered detection of missed and late insulin boluses",
          },
          {
            icon: "📡",
            title: "Sensor Integration",
            desc: "Connect Dexcom and Libre sensors for automatic data import",
          },
        ].map((feature) => (
          <div
            key={feature.title}
            style={{
              background: "var(--card-bg)",
              border: "1px solid var(--border)",
              borderRadius: "12px",
              padding: "1.5rem",
            }}
          >
            <div style={{ fontSize: "2rem", marginBottom: "0.75rem" }}>
              {feature.icon}
            </div>
            <h3 style={{ marginBottom: "0.5rem", fontWeight: 600 }}>
              {feature.title}
            </h3>
            <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem" }}>
              {feature.desc}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
