<script lang="ts">
	// One line: when the daemon last checked and the time of the latest report, as icons and times,
	// or a message instead (check result, error).
	import { clock } from "./lib/format";
	import type { Status } from "./lib/types";

	interface Props {
		status: Status | null;
		message: string | null; // overrides the summary
		class?: string;
	}

	let { status, message, class: className = "" }: Props = $props();

	// Icons (24×24, stroked like the others).
	const REFRESH = "M20 4v5h-5M19.4 14.5A8 8 0 1 1 18 6.6L20 9"; // last check
	const CHECK = "M5 12.5l4.5 4.5L19 7.5"; // latest report
</script>

{#snippet item(path: string, label: string, time: string)}
	<span class="inline-flex items-center gap-1" title={label}>
		<svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" aria-hidden="true">
			<path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={path} />
		</svg>
		<span class="sr-only">{label}</span>
		{clock(time)}
	</span>
{/snippet}

{#if message}
	<p class="text-xs text-gray-500 {className}">{message}</p>
{:else if status?.available && (status.stopped || status.last_check || status.latest_report)}
	<p class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500 {className}">
		{#if status.stopped}<span>Stopped: {status.stopped}</span>{/if}
		{#if status.last_check}{@render item(REFRESH, "Last check", status.last_check)}{/if}
		{#if status.latest_report}{@render item(CHECK, "Latest report", status.latest_report)}{/if}
	</p>
{/if}
