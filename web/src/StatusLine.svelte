<script lang="ts">
	// One line under the calendar: last check and latest report, or a message (check result, error).
	import { clock } from "./lib/format";
	import type { Status } from "./lib/types";

	interface Props {
		status: Status | null;
		message: string | null; // overrides the summary
	}

	let { status, message }: Props = $props();

	const summary = $derived.by(() => {
		if (!status?.available) return "";
		const parts: string[] = [];
		if (status.stopped) parts.push(`Stopped: ${status.stopped}`);
		if (status.last_check) parts.push(`Last check ${clock(status.last_check)}`);
		if (status.latest_report) parts.push(`latest report ${clock(status.latest_report)}`);
		return parts.join(" · ");
	});
</script>

{#if message ?? summary}
	<p class="text-xs text-gray-500">{message ?? summary}</p>
{/if}
