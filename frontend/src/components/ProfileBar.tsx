import { formatInt } from "../format";
import type { Profile } from "../types";

export function ProfileBar({ profile, version }: { profile: Profile; version: number }) {
  const q = profile.quality;
  const tone = q.total >= 85 ? "good" : q.total >= 65 ? "ok" : "bad";
  const items: [string, string][] = [
    ["Γραμμές", formatInt(profile.shape[0])],
    ["Στήλες", formatInt(profile.shape[1])],
    ["Κενά κελιά", formatInt(profile.total_missing)],
    ["Διπλότυπα", formatInt(profile.duplicates_count)],
    ["Μνήμη", `${profile.memory_mb} MB`],
  ];
  return (
    <div className="profile-bar">
      <span className="chip version">v{version}</span>
      {items.map(([label, value]) => (
        <div key={label} className="stat">
          <span className="stat-label">{label}</span>
          <span className="stat-value">{value}</span>
        </div>
      ))}
      <div
        className={`stat quality ${tone}`}
        title={`Πληρότητα ${q.completeness}% · Μοναδικότητα ${q.uniqueness}% · Εγκυρότητα τύπων ${q.validity}% · Συνέπεια ${q.consistency}%`}
      >
        <span className="stat-label">Ποιότητα</span>
        <span className="stat-value">{q.total}/100</span>
      </div>
    </div>
  );
}
