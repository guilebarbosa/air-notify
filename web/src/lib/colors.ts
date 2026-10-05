// Zones: one colour per zone for the map circles. Avoids blue (the points) and green/red
// (arrived/left in the timeline), so a zone's colour never reads as one of those.
export const ZONE_COLORS = [
	"#9333ea", // purple
	"#ea580c", // orange
	"#0d9488", // teal
	"#db2777", // pink
	"#4b5563", // grey
] as const;

/** Zones keep their config order, so a zone always gets the same colour. */
export const zoneColor = (index: number): string => ZONE_COLORS[Math.max(0, index) % ZONE_COLORS.length];

// Points: from light blue (the day's oldest report) to dark blue (its newest).
const OLDEST = [191, 219, 254]; // Tailwind blue-200
const NEWEST = [30, 58, 138]; // Tailwind blue-900

/** `t` is how far through the day's reports a point is: 0 = oldest, 1 = newest. */
export function pointColor(t: number): string {
	const k = Math.min(1, Math.max(0, t));
	const rgb = OLDEST.map((from, i) => Math.round(from + (NEWEST[i] - from) * k));
	return `rgb(${rgb.join(", ")})`;
}
