import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { GlucoseUnitProvider } from "@/controllers/GlucoseUnitContext";
import { TimeRangeProvider } from "@/controllers/TimeRangeContext";
import { GlucoseRangesProvider } from "@/controllers/GlucoseRangesContext";
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
          <TimeRangeProvider>
            <GlucoseRangesProvider>
              <NavBar/>
              <main style={{ maxWidth: "1200px", margin: "0 auto", padding: "1.5rem" }}>
                {children}
              </main>
            </GlucoseRangesProvider>
          </TimeRangeProvider>
        </GlucoseUnitProvider>
      </body>
    </html>
  );
}
