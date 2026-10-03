import type { CheckResult, Day, DayData, Status } from "./types";

// The viewer refuses POSTs without this header, so other websites can't trigger checks.
const CHECK_HEADER = "X-Air-Notify";

async function getJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  // 503 carries a JSON explanation (checks need the daemon); anything else non-2xx is an error.
  if (!response.ok && response.status !== 503) throw new Error(`${url}: HTTP ${response.status}`);
  return (await response.json()) as T;
}

export const getDays = () => getJSON<Day[]>("/api/days");

export const getDay = (date: string) => getJSON<DayData>(`/api/days/${encodeURIComponent(date)}`);

export const getStatus = () => getJSON<Status>("/api/status");

export const checkNow = () =>
  getJSON<CheckResult>("/api/poll", { method: "POST", headers: { [CHECK_HEADER]: "1" } });
