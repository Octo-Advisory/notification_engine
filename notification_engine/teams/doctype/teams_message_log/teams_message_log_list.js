// Kept self-contained: the list must render even if the shared teams.js is not loaded.
const TN_LOG_COLORS = { Queued: "blue", Sent: "green", Failed: "red", Throttled: "orange", Skipped: "gray" };

frappe.listview_settings["Teams Message Log"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const color = TN_LOG_COLORS[doc.status] || "gray";
		return [__(doc.status), color, `status,=,${doc.status}`];
	},
	onload(listview) {
		listview.page.add_action_item(__("Resend"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) return;
			frappe
				.call({ method: "notification_engine.teams.api.resend", args: { names: JSON.stringify(names) }, freeze: true })
				.then((r) => {
					frappe.show_alert({ message: __("{0} message(s) queued again.", [r.message || 0]), indicator: "green" });
					listview.refresh();
				});
		});
	},
};
