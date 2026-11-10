"use client";

import { useMemo } from "react";

import { supportedTimezones } from "@/lib/timezones";

type Props = {
  value: string;
  onChange: (value: string) => void;
  id?: string;
  className?: string;
  label?: string;
};

export function TimezoneSelect({ value, onChange, id, className = "", label = "Timezone" }: Props) {
  const zones = useMemo(() => {
    const list = supportedTimezones();
    return list.includes(value) ? list : [value, ...list];
  }, [value]);
  return (
    <select
      id={id}
      aria-label={label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={`rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm ${className}`}
    >
      {zones.map((zone) => (
        <option key={zone} value={zone}>
          {zone.replaceAll("_", " ")}
        </option>
      ))}
    </select>
  );
}
