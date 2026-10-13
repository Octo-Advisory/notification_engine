// Copyright (c) 2026, Octo Advisory and contributors
// For license information, please see license.txt

frappe.ui.form.on("Teams Message Log", {
	refresh(frm) {
		if (frm.doc.status !== "Queued") {
			frm.add_custom_button(__("Resend"), () => {
				frappe
					.call({ method: "notification_engine.teams.api.resend", args: { names: frm.doc.name }, freeze: true })
					.then(() => notification_engine.teams.wait_for_logs([frm.doc.name]))
					.then(() => frm.reload_doc());
			});
		}
		if (frm.doc.reference_doctype && frm.doc.reference_name) {
			frm.add_custom_button(__("Open Document"), () =>
				frappe.set_route("Form", frm.doc.reference_doctype, frm.doc.reference_name)
			);
		}
	},
});
