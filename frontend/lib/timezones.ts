/** Timezone helpers. The server is authoritative for conversion and DST
 * validation; these helpers only format and navigate dates for display. */

export const FALLBACK_TIMEZONES = [
  "UTC",
  "Asia/Karachi",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
  "Europe/London",
  "Europe/Berlin",
  "Africa/Lagos",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Sao_Paulo",
];

export function browserTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? null;
  } catch {
    return null;
  }
}

export function supportedTimezones(): string[] {
  try {
    const values = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone");
    if (values && values.length) return values.includes("UTC") ? values : ["UTC", ...values];
  } catch {
    // fall through
  }
  return FALLBACK_TIMEZONES;
}

/** Format an instant in a timezone, e.g. "Tue, 10 Mar 2027, 09:00". */
export function formatInZone(iso: string, timeZone: string, options: Intl.DateTimeFormatOptions = {}): string {
  return new Intl.DateTimeFormat(undefined, {
    timeZone,
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    ...options,
  }).format(new Date(iso));
}

/** Today's date (YYYY-MM-DD) in a timezone. */
export function todayInZone(timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** Calendar arithmetic on plain YYYY-MM-DD strings (no timezone involved). */
export function addDays(day: string, amount: number): string {
  const [year, month, date] = day.split("-").map(Number);
  const value = new Date(Date.UTC(year, month - 1, date + amount));
  return value.toISOString().slice(0, 10);
}

export function addMonths(day: string, amount: number): string {
  const [year, month] = day.split("-").map(Number);
  const value = new Date(Date.UTC(year, month - 1 + amount, 1));
  return value.toISOString().slice(0, 10);
}

export function weekdayIndex(day: string): number {
  const [year, month, date] = day.split("-").map(Number);
  return (new Date(Date.UTC(year, month - 1, date)).getUTCDay() + 6) % 7; // Monday = 0
}

export function formatDay(day: string, options: Intl.DateTimeFormatOptions): string {
  const [year, month, date] = day.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { timeZone: "UTC", ...options }).format(new Date(Date.UTC(year, month - 1, date)));
}

export function splitLocal(local: string): { date: string; time: string } {
  const [date, time = "09:00"] = local.split("T");
  return { date, time: time.slice(0, 5) };
}
