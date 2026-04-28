import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { GlucoseUnitProvider } from "@/controllers/GlucoseUnitContext";
import NavBar from "@/views/NavBar/NavBar";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "DTU Diabetes ML Dashboard",
  description:
    "Type 1 Diabetes monitoring dashboard with ML-based anomaly detection — DTU Research Project",
  icons: {
    icon: "/diab-favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={inter.variable}>
      <body style={{ fontFamily: "var(--font-inter), sans-serif" }}>
        <GlucoseUnitProvider>
          <NavBar />
          <main style={{ maxWidth: "1200px", margin: "0 auto", padding: "1.5rem" }}>
            {children}
          </main>
        </GlucoseUnitProvider>
      </body>
    </html>
  );
}
