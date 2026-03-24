import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DTU Diabetes ML Dashboard",
  description:
    "Type 1 Diabetes monitoring dashboard with ML-based anomaly detection — DTU Research Project",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <nav style={{
          background: "var(--nav-bg)",
          color: "var(--nav-text)",
          padding: "0.75rem 1.5rem",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          borderBottom: "1px solid var(--border)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <span style={{ fontSize: "1.25rem", fontWeight: 700 }}>
              🩸 DTU Diabetes Dashboard
            </span>
          </div>
          <div style={{ display: "flex", gap: "1.5rem", fontSize: "0.9rem" }}>
            <a href="/patient" style={{ color: "var(--nav-text)", textDecoration: "none" }}>
              Patient View
            </a>
            <a href="/doctor" style={{ color: "var(--nav-text)", textDecoration: "none" }}>
              Doctor View
            </a>
          </div>
        </nav>
        <main style={{ maxWidth: "1200px", margin: "0 auto", padding: "1.5rem" }}>
          {children}
        </main>
      </body>
    </html>
  );
}
