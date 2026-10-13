const NOTIFICATION_ENGINE_LAYOUT_FIELDTYPES = [
	"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold", "Heading",
];
const NOTIFICATION_ENGINE_RULE_METHOD = "notification_engine.notification_engine.doctype.notification_rule.notification_rule";
const NOTIFICATION_ENGINE_OWN_DOCTYPES = [
	"Notification Rule", "Notification Engine Log", "Notification User Preference", "Notification Engine Settings",
	"Teams Settings", "Teams Destination", "Teams Message Log", "Teams Digest Buffer", "Teams User Map",
];
const NOTIFICATION_ENGINE_TEAMS_GROUP_TYPES = ["Webhook", "Bot Conversation"];
const NOTIFICATION_ENGINE_TEAMS_PERSONAL_TYPES = ["Bot (Personal Chat)", "Webhook (Personal via Flow bot)"];

frappe.ui.form.on("Notification Rule", {
	setup(frm) {
		frm.set_query("reference_doctype", () => ({
			filters: { istable: 0, name: ["not in", NOTIFICATION_ENGINE_OWN_DOCTYPES] },
		}));
		frm.set_query("destination", "teams_destinations", () => ({
			filters: { destination_type: ["in", NOTIFICATION_ENGINE_TEAMS_GROUP_TYPES] },
		}));
		frm.set_query("teams_personal_destination", () => ({
			filters: { destination_type: ["in", NOTIFICATION_ENGINE_TEAMS_PERSONAL_TYPES] },
		}));
	},

	refresh(frm) {
		refresh_dynamic_dropdowns(frm);
		load_hr_options(frm);
		refresh_teams_options(frm);

		if (!frm.is_new() && frm.doc.send_teams) {
			frm.add_custom_button(__("Send Teams Test"), () => send_teams_test(frm));
		}

		if (!frm.is_new() && frm.doc.recipient_source === "Role \u2192 Expand To Users" && frm.doc.role) {
			frm.add_custom_button(__("Sync From Role"), () => {
				frappe.call({
					method: "notification_engine.notification_engine.doctype.notification_rule.notification_rule.sync_role_users",
					args: { name: frm.doc.name },
					freeze: true,
					freeze_message: __("Syncing recipients..."),
					callback: () => frm.reload_doc(),
				});
			});
		}

		if (!frm.is_new() && frm.doc.recipient_source === "Workflow Roles (Project + Department)") {
			if (frm.doc.sample_reference_document) {
				frm.add_custom_button(__("Preview Resolved Users"), () => {
					frappe.call({
						method: "notification_engine.notification_engine.doctype.notification_rule.notification_rule.preview_role_resolution",
						args: { name: frm.doc.name },
						freeze: true,
						freeze_message: __("Resolving users..."),
						callback: (r) => {
							// "HTML" fieldtype fields hold no document value - set_value()
							// on them is a silent no-op. The content must be written
							// directly into the field's wrapper element instead.
							const field = frm.get_field("resolved_users_html");
							if (field) {
								field.$wrapper.html(r.message || "");
							}
						},
					});
				});
			}
		}

		if (!frm.is_new()) {
			frm.add_custom_button(__("View Delivery Log"), () => {
				frappe.set_route("List", "Notification Engine Log", { notification_rule: frm.doc.name });
			});
		}
	},

	reference_doctype(frm) {
		refresh_dynamic_dropdowns(frm, true);
		refresh_teams_options(frm);
	},

	recipient_source(frm) {
		load_hr_options(frm);
	},

	send_teams(frm) {
		refresh_teams_options(frm);
	},
});

/**
 * Designation and Department come from ERPNext, which this app does not
 * require, so they are Autocomplete fields filled from the server rather
 * than Links.
 */
function load_hr_options(frm) {
	const fieldname = { Designation: "designation", Department: "department" }[frm.doc.recipient_source];
	if (!fieldname) return;

	frappe.call({
		method: `${NOTIFICATION_ENGINE_RULE_METHOD}.get_hr_options`,
		args: { doctype: frm.doc.recipient_source },
		callback: (r) => {
			const options = r.message || [];
			frm.set_df_property(fieldname, "options", options);
			if (!options.length) {
				frm.set_df_property(
					fieldname,
					"description",
					__("No {0} records found. This source needs ERPNext (Employee / {0}) installed on this site.", [
						__(frm.doc.recipient_source),
					])
				);
			}
			frm.refresh_field(fieldname);
		},
	});
}

/** Field pickers of the Teams section: card fields, Set Value buttons and workflow actions. */
function refresh_teams_options(frm) {
	if (!frm.doc.reference_doctype || !frm.doc.send_teams) return;

	const blocked = ["Password", ...frappe.model.table_fields, ...frappe.model.no_value_type];
	const standard = ["name", "owner", "creation", "modified", "modified_by"];

	frappe.model.with_doctype(frm.doc.reference_doctype, () => {
		const options = frappe
			.get_meta(frm.doc.reference_doctype)
			.fields.filter((df) => !blocked.includes(df.fieldtype))
			.map((df) => ({
				value: df.fieldname,
				label: `${df.fieldname} (${__(df.label || df.fieldname, null, df.parent)})`,
			}));

		frm.fields_dict.teams_fields.grid.update_docfield_property("fieldname", "options", [""].concat(options, standard));
		frm.fields_dict.teams_buttons.grid.update_docfield_property("fieldname", "options", [""].concat(options));
		frm.refresh_field("teams_fields");
	});

	frappe.db
		.get_value("Workflow", { document_type: frm.doc.reference_doctype, is_active: 1 }, "name")
		.then((r) => {
			const workflow = r.message && r.message.name;
			if (!workflow) {
				frm.fields_dict.teams_buttons.grid.update_docfield_property("workflow_action", "options", [""]);
				frm.set_df_property(
					"teams_all_workflow_actions",
					"description",
					__("{0} has no active Workflow. Only Set Value buttons are possible.", [__(frm.doc.reference_doctype)])
				);
				return;
			}
			frappe.model.with_doc("Workflow", workflow, () => {
				const actions = [...new Set((frappe.get_doc("Workflow", workflow).transitions || []).map((t) => t.action))];
				frm.fields_dict.teams_buttons.grid.update_docfield_property("workflow_action", "options", [""].concat(actions));
				frm.refresh_field("teams_buttons");
			});
		});
}

/** Sends this rule's Teams card for a chosen (or the latest) document, with a [TEST] prefix. */
function send_teams_test(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the rule before sending a test."));
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Send Teams Test"),
		fields: [
			{
				fieldname: "docname",
				fieldtype: "Link",
				label: __("Document"),
				options: frm.doc.reference_doctype,
				description: __("Leave empty to use the latest {0}.", [__(frm.doc.reference_doctype)]),
			},
		],
		primary_action_label: __("Send"),
		primary_action(values) {
			dialog.hide();
			frappe
				.call({
					method: "notification_engine.teams.api.send_test_for_rule",
					args: { rule: frm.doc.name, docname: values.docname },
					freeze: true,
				})
				.then((r) => {
					const res = r.message || {};
					if (res.condition_error) {
						frappe.show_alert({ message: __("Condition error: {0}", [res.condition_error]), indicator: "red" });
					} else if (res.condition === false) {
						frappe.show_alert(
							{
								message: __("Note: the condition is false for {0}, so a real event would not send.", [res.docname]),
								indicator: "orange",
							},
							8
						);
					}
					notification_engine.teams.wait_for_logs(res.logs);
				});
		},
	});
	dialog.show();
}

/**
 * Populates every fieldname-picker on the form as a dropdown built from the
 * Reference Document Type's own fields - the same pattern Frappe's own
 * "Fetch From" field picker uses in Customize Form, so admins pick from a
 * list instead of typing a fieldname by hand. Runs on both form refresh
 * (so reopening a saved rule shows the dropdown correctly) and whenever
 * Reference Document Type changes.
 */
function refresh_dynamic_dropdowns(frm, clear_value) {
	populate_field_dropdown(frm, "project_field", (df) => df.fieldtype === "Link" && df.options === "Project", clear_value);
	populate_field_dropdown(frm, "department_field", (df) => df.fieldtype === "Link" && df.options === "Department", clear_value);
	populate_field_dropdown(frm, "document_field", (df) => df.fieldtype === "Link" && df.options === "User", clear_value, [
		"owner",
		"modified_by",
	]);
	populate_field_dropdown(frm, "date_field", (df) => ["Date", "Datetime"].includes(df.fieldtype), clear_value);
	populate_field_dropdown(
		frm,
		"value_changed_field",
		(df) => !NOTIFICATION_ENGINE_LAYOUT_FIELDTYPES.includes(df.fieldtype),
		clear_value
	);
}

function populate_field_dropdown(frm, fieldname, filter_fn, clear_value, extra_options = []) {
	if (!frm.doc.reference_doctype) {
		frm.set_df_property(fieldname, "options", []);
		if (clear_value) frm.set_value(fieldname, "");
		frm.refresh_field(fieldname);
		return;
	}

	frappe.model.with_doctype(frm.doc.reference_doctype, () => {
		const meta = frappe.get_meta(frm.doc.reference_doctype);
		// meta.fields includes custom fields (Customize Form additions) the
		// same way it includes standard ones - no separate handling needed.
		const options = (meta.fields || []).filter(filter_fn).map((df) => df.fieldname).concat(extra_options);

		frm.set_df_property(fieldname, "options", [""].concat(options).join("\n"));

		// keep the current value only if it's still a valid option after
		// switching reference_doctype; otherwise clear it so a stale
		// fieldname from a previous doctype can't silently stick around
		if (clear_value && frm.doc[fieldname] && !options.includes(frm.doc[fieldname])) {
			frm.set_value(fieldname, "");
		}

		frm.refresh_field(fieldname);
	});
}
