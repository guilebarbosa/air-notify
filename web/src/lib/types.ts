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

export interface Zone {
  name: string;
  lat: number;
  lon: number;
  radius_m: number;
}

export interface DayData {
  date: string;
  points: Point[];
  zones: Zone[];
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
