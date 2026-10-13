// Copyright (c) 2026, Octo Advisory and contributors
// For license information, please see license.txt

frappe.ui.form.on("Teams Settings", {
	refresh(frm) {
		frm.trigger("show_secret_expiry");
		frm.add_custom_button(__("Open Dashboard"), () => window.open("/teams-notify", "_blank"));
		frm.add_custom_button(__("Install Guide"), () => window.open("/teams-notify/install", "_blank"));
		if (!frm.doc.bot_enabled) return;

		frm.add_custom_button(__("Check Bot Connection"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the settings first."));
				return;
			}
			frappe
				.call({ method: "notification_engine.teams.api.check_bot_connection", freeze: true })
				.then((r) => frappe.msgprint({ title: __("Teams Bot"), message: r.message, indicator: "green" }));
		}, __("Teams Bot"));

		frm.add_custom_button(__("Download Teams App Package"), () => {
			window.open("/api/method/notification_engine.teams.api.download_app_package");
		}, __("Teams Bot"));

		if (frm.doc.messaging_endpoint) {
			frm.add_custom_button(__("Copy Messaging Endpoint"), () => {
				frappe.utils.copy_to_clipboard(frm.doc.messaging_endpoint);
			}, __("Teams Bot"));
			if (!frm.doc.messaging_endpoint.startsWith("https://")) {
				frm.dashboard.add_comment(
					__("The messaging endpoint must be public HTTPS for Teams to reach it. Set Site URL to your public HTTPS address."),
					"orange",
					true
				);
			}
		}
	},

	show_secret_expiry(frm) {
		if (!frm.doc.bot_enabled || !frm.doc.bot_secret_expiry) return;
		const days = frappe.datetime.get_day_diff(frm.doc.bot_secret_expiry, frappe.datetime.get_today());
		if (days < 0) {
			frm.dashboard.add_comment(__("The bot client secret expired {0} day(s) ago. The bot cannot send.", [-days]), "red", true);
		} else if (days <= 30) {
			frm.dashboard.add_comment(__("The bot client secret expires in {0} day(s). Create a new one in Entra ID.", [days]), "orange", true);
		}
	},
});
