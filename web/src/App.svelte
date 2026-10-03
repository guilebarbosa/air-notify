<script lang="ts">
  import { onMount } from "svelte";

  import CheckNow from "./CheckNow.svelte";
  import DayList from "./DayList.svelte";
  import { checkNow, getDay, getDays, getStatus } from "./lib/api";
  import type { Day, DayData, Status } from "./lib/types";
  import MapView from "./MapView.svelte";

  let days = $state<Day[]>([]);
  let selected = $state<string | null>(null);
  let day = $state<DayData | null>(null);
  let status = $state<Status | null>(null);
  let message = $state<string | null>(null);
  let checking = $state(false);

  const showError = (error: unknown) => {
    console.error(error);
    message = `Error: ${error instanceof Error ? error.message : String(error)}`;
  };

  async function select(date: string) {
    selected = date;
    day = await getDay(date);
  }

  async function loadDays() {
    days = await getDays();
    // Keep the selected day if it's still listed; otherwise show the newest.
    const keep = days.find((d) => d.date === selected)?.date ?? days[0]?.date;
    if (keep) await select(keep);
  }

  async function loadStatus() {
    status = await getStatus();
  }

  async function check() {
    checking = true;
    message = null;
    try {
      const result = await checkNow();
      await Promise.all([loadStatus(), loadDays()]);
      if (result.status !== "ok") message = result.detail;
    } catch (error) {
      showError(error);
    } finally {
      checking = false;
    }
  }

  onMount(() => {
    Promise.all([loadStatus(), loadDays()]).catch(showError);
  });
</script>

<nav>
  <h1>air-notify</h1>
  <CheckNow {status} {message} {checking} oncheck={check} />
  <DayList {days} {selected} onselect={(date) => select(date).catch(showError)} />
</nav>
<main>
  <MapView points={day?.points ?? []} zones={day?.zones ?? []} />
</main>

<style>
  nav {
    width: 13rem;
    overflow-y: auto;
    border-right: 1px solid #ddd;
  }

  h1 {
    font-size: 1rem;
    margin: 0.75rem;
  }

  main {
    flex: 1;
    min-height: 0;
  }

  @media (max-width: 40rem) {
    nav {
      width: auto;
      height: 40%;
      border-right: 0;
      border-bottom: 1px solid #ddd;
    }
  }
</style>
