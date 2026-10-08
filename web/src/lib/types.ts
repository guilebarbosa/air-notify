// Shapes of the viewer API (src/air_notify/viewer.py).

export interface Day {
	date: string; // YYYY-MM-DD, local time
	count: number;
}

export interface Point {
	t: string; // ISO 8601 with offset
	lat: number;
	lon: number;
	acc: number; // metres
}

/** A zone is a circle or a custom shape (outline). */
export type Zone = CircleZone | OutlineZone;

export interface CircleZone {
	name: string;
	lat: number;
	lon: number;
	radius_m: number;
}

export interface OutlineZone {
	name: string;
	outline: [number, number][]; // corners in order, as [lat, lon]; the last joins back to the first
}

/** An arrival or departure, computed on the server with the same rules and wording as the alerts. */
export interface TimelineEvent {
	t: string; // ISO 8601 with offset
	zone: string;
	transition: "arrive" | "leave";
	label: string; // e.g. "Left school"
}

export interface DayData {
	date: string;
	points: Point[];
	zones: Zone[];
	events: TimelineEvent[]; // newest first
	max_accuracy_m: number; // reports less accurate than this aren't drawn (same rule as the alerts)
}

/** `available` is false when the viewer runs on its own (`air-notify view`), without the daemon. */
export type Status =
	| { available: false }
	| {
			available: true;
			last_check: string | null;
			next_check: string | null;
			latest_report: string | null;
			stopped: string | null;
		};

export interface CheckResult {
	status: "ok" | "failed" | "cooldown" | "stopped" | "unavailable";
	detail: string;
}

/** Which map tiles to draw; `warning` is set when the configured style couldn't be used. */
export interface MapTiles {
	url: string; // Leaflet URL template, with any provider key already filled in
	attribution: string;
	maxZoom: number;
	warning: string | null;
}
