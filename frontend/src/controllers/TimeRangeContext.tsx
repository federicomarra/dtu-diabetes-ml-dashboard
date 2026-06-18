"use client";

import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

export interface TimeRange {
  last?: string;  // e.g. "24h", "7d", "2w", "1m"
  start?: string; // ISO string (optional)
  end?: string;   // ISO string (optional)
}

interface TimeRangeContextValue {
  timeRange: TimeRange;
  setTimeRange: (range: TimeRange) => void;
  setLast: (last: string) => void;
  setCustomRange: (start: string, end: string) => void;
}

const TimeRangeContext = createContext<TimeRangeContextValue | undefined>(undefined);

export function TimeRangeProvider({ children }: { children: ReactNode }) {
  const [timeRange, setTimeRangeRaw] = useState<TimeRange>({ last: "2w" });

  const setTimeRange = useCallback((range: TimeRange) => {
    setTimeRangeRaw(range);
  }, []);

  const setLast = useCallback((last: string) => {
    setTimeRangeRaw({ last });
  }, []);

  const setCustomRange = useCallback((start: string, end: string) => {
    if (end == "") {
      end = new Date().toISOString();
    }
    setTimeRangeRaw({ start, end });
  }, []);

  return (
    <TimeRangeContext.Provider value={{ timeRange, setTimeRange, setLast, setCustomRange }}>
      {children}
    </TimeRangeContext.Provider>
  );
}

/** Hook to access the current time range filter state and setters. */
export function useTimeRange(): TimeRangeContextValue {
  const ctx = useContext(TimeRangeContext);
  if (!ctx) {
    throw new Error("useTimeRange must be used within a TimeRangeProvider");
  }
  return ctx;
}

export function parseLastToDays(last: string): number {
  const match = last.match(/^(\d+)([hdwmy])$/);
  if (!match) return 14;
  const value = parseInt(match[1], 10);
  const unit = match[2];
  switch (unit) {
    case "h": return value / 24;
    case "d": return value;
    case "w": return value * 7;
    case "m": return value * 30;
    case "y": return value * 365;
    default: return value;
  }
}

export function formatDayMonthStr(dateStr: string): string {
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function returnTextFromSpanDays(days: number): [string, string, string] {
  let span: string;
  if (days <= 1) {
    span = "day";
  } else if (days === 7) {
    span = "week";
  } else if (days === 14) {
    span = "2 weeks";
  } else if (days < 14) {
    span = `${days} days`;
  } else if (days === 30 || days === 31) {
    span = "month";
  } else if (days < 30) {
    span = `${Math.round(days / 7)} weeks`;
  } else if (days < 365) {
    span = `${Math.round(days / 30)} months`;
  } else {
    span = `${Math.round(days / 365)} year${Math.round(days / 365) !== 1 ? "s" : ""}`;
  }
  const start_day: string = formatDayMonthStr(new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString());
  const end_day: string = formatDayMonthStr(new Date().toISOString());
  return [span, start_day, end_day];
}

export function formatTimeRangeFriendly(timeRange: TimeRange): string {
  if (timeRange.last) {
    const days = parseLastToDays(timeRange.last);
    const [span] = returnTextFromSpanDays(days);
    return `latest ${span}`;
  }
  if (timeRange.start) {
    const startStr = formatDayMonthStr(timeRange.start);
    const endStr = timeRange.end ? formatDayMonthStr(timeRange.end) : "now";
    return `from ${startStr} to ${endStr}`;
  }
  return "latest 2 weeks";
}
