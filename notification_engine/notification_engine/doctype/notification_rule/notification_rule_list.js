frappe.listview_settings["Notification Rule"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Generate Rules For All Active Workflows"), () => {
			frappe.confirm(
				__(
					"This scans every DocType with an active Workflow and creates a " +
					"draft (disabled) Notification Rule for any that don't already " +
					"have one using 'Workflow Roles (Project + Department)'. Each " +
					"generated rule still needs review - set Project/Department Field " +
					"where relevant, adjust Subject/Message, and enable it. Continue?"
				),
				() => {
					frappe.call({
						method:
							"notification_engine.notification_engine.doctype.notification_rule.notification_rule.generate_rules_for_active_workflows",
						freeze: true,
						freeze_message: __("Scanning active workflows..."),
						callback: (r) => {
							const created = (r.message && r.message.created) || [];
							const skipped = (r.message && r.message.skipped) || [];
							frappe.msgprint({
								title: __("Done"),
								indicator: "green",
								message: __(
									"Created {0} draft rule(s): {1}<br>Skipped {2} doctype(s) that already had a rule: {3}",
									[
										created.length,
										created.join(", ") || "-",
										skipped.length,
										skipped.join(", ") || "-",
									]
								),
							});
							listview.refresh();
						},
					});
				}
			);
		});
	},
};
