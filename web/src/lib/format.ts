export const clock = (t: string) =>
	new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export const dayLabel = (date: string) =>
	new Date(`${date}T12:00`).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
