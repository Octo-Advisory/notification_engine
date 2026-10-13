// Shared helpers for Teams Notify forms.
frappe.provide("notification_engine.teams");

notification_engine.teams.STATUS_COLORS = {
	Queued: "blue",
	Sent: "green",
	Failed: "red",
	Throttled: "orange",
	Skipped: "gray",
};

// Poll Teams Message Logs until none is Queued (or we give up), then report the outcome.
notification_engine.teams.wait_for_logs = function (names, { timeout = 30 } = {}) {
	if (!names || !names.length) {
		frappe.msgprint(__("Nothing was queued."));
		return;
	}
	const started = Date.now();
	frappe.show_alert({ message: __("Sending to Teams..."), indicator: "blue" });

	const poll = () => {
		frappe
			.call({
				method: "notification_engine.teams.api.get_log_status",
				args: { names: JSON.stringify(names) },
			})
			.then((r) => {
				const logs = r.message || [];
				const pending = logs.filter((l) => ["Queued", "Throttled"].includes(l.status));
				if (pending.length && Date.now() - started < timeout * 1000) {
					setTimeout(poll, 1500);
					return;
				}
				notification_engine.teams.show_log_results(logs, pending.length > 0);
			});
	};
	setTimeout(poll, 1000);
};

notification_engine.teams.show_log_results = function (logs, timed_out) {
	const rows = logs
		.map((l) => {
			const color = notification_engine.teams.STATUS_COLORS[l.status] || "gray";
			const error = l.error ? `<div class="text-muted small">${frappe.utils.escape_html(l.error)}</div>` : "";
			return `<tr>
				<td><a href="/app/teams-message-log/${l.name}">${frappe.utils.escape_html(l.destination || l.name)}</a></td>
				<td><span class="indicator-pill ${color}">${__(l.status)}</span>${error}</td>
			</tr>`;
		})
		.join("");
	const note = timed_out
		? `<p class="text-muted">${__(
				"Still queued. Check that a background worker is running (bench worker). The Teams Message Log will update when it is sent."
		  )}</p>`
		: "";
	const sent_note = logs.some((l) => l.status === "Sent")
		? `<p class="text-muted">${__(
				"Sent means the workflow accepted the message. If the card does not appear in Teams, open the flow's run history in Power Automate."
		  )}</p>`
		: "";
	frappe.msgprint({
		title: __("Teams delivery"),
		message: `${note}${sent_note}<table class="table table-bordered"><tbody>${rows}</tbody></table>`,
		wide: true,
	});
};
