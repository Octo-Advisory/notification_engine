// Copyright (c) 2026, Octo Advisory and contributors
// For license information, please see license.txt

frappe.ui.form.on("Teams Destination", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Send Test Message"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the destination before sending a test."));
				return;
			}
			frappe
				.call({
					method: "notification_engine.teams.api.send_test_to_destination",
					args: { destination: frm.doc.name },
					freeze: true,
				})
				.then((r) => notification_engine.teams.wait_for_logs(r.message ? [r.message] : []));
		});

		frm.add_custom_button(__("Message Log"), () =>
			frappe.set_route("List", "Teams Message Log", { destination: frm.doc.name })
		);

		if (frm.doc.consecutive_failures) {
			frm.dashboard.set_headline(
				__("{0} consecutive failures. Last error: {1}", [
					frm.doc.consecutive_failures,
					frappe.utils.escape_html(frm.doc.last_error || ""),
				]),
				"red"
			);
		} else if (frm.doc.last_success) {
			frm.dashboard.set_headline(
				__("Last delivered {0}.", [frappe.datetime.comment_when(frm.doc.last_success)]),
				"green"
			);
		}
	},
});
