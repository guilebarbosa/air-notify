// Zones: Flowbite's timeline colour names, with the matching hex for the map circles.
// Blue is left out: it's used for the points.
export const ZONE_COLORS = [
	{ name: "green", hex: "#16a34a" },
	{ name: "orange", hex: "#ea580c" },
	{ name: "purple", hex: "#9333ea" },
	{ name: "red", hex: "#dc2626" },
	{ name: "gray", hex: "#4b5563" },
] as const;

export type ZoneColor = (typeof ZONE_COLORS)[number];

/** Zones keep their config order, so a zone always gets the same colour. */
export const zoneColor = (index: number): ZoneColor => ZONE_COLORS[Math.max(0, index) % ZONE_COLORS.length];

// Points: from light blue (the day's oldest report) to dark blue (its newest).
const OLDEST = [191, 219, 254]; // Tailwind blue-200
const NEWEST = [30, 58, 138]; // Tailwind blue-900

/** `t` is how far through the day's reports a point is: 0 = oldest, 1 = newest. */
export function pointColor(t: number): string {
	const k = Math.min(1, Math.max(0, t));
	const rgb = OLDEST.map((from, i) => Math.round(from + (NEWEST[i] - from) * k));
	return `rgb(${rgb.join(", ")})`;
}
