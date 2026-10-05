export const clock = (t: string) =>
	new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

// The API uses local YYYY-MM-DD strings; the date picker uses Date objects. Noon keeps a
// date from slipping to the neighbouring day across time zones / DST changes.
export const toDate = (iso: string) => new Date(`${iso}T12:00`);

export const toIso = (d: Date) =>
	`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export const todayIso = () => toIso(new Date());

/** e.g. "Oct 3, 2026" (in the browser's language) */
export const dateLabel = (iso: string) =>
	toDate(iso).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
