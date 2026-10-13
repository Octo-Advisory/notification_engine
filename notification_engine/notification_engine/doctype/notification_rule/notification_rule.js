const NOTIFICATION_ENGINE_LAYOUT_FIELDTYPES = [
	"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold", "Heading",
];

frappe.ui.form.on("Notification Rule", {
	refresh(frm) {
		refresh_dynamic_dropdowns(frm);
		load_designation_options(frm);

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
	},

	recipient_source(frm) {
		load_designation_options(frm);
	},
});

/**
 * Designation comes from ERPNext, which this app does not require, so the
 * field is an Autocomplete filled from the server rather than a Link.
 */
function load_designation_options(frm) {
	if (frm.doc.recipient_source !== "Designation") return;

	frappe.call({
		method: "notification_engine.notification_engine.doctype.notification_rule.notification_rule.get_designations",
		callback: (r) => {
			const options = r.message || [];
			frm.set_df_property("designation", "options", options);
			if (!options.length) {
				frm.set_df_property(
					"designation",
					"description",
					__("No Designations found. This source needs ERPNext (Employee / Designation) installed on this site.")
				);
			}
			frm.refresh_field("designation");
		},
	});
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
	populate_field_dropdown(frm, "document_field", (df) => df.fieldtype === "Link" && df.options === "User", clear_value);
	populate_field_dropdown(frm, "date_field", (df) => ["Date", "Datetime"].includes(df.fieldtype), clear_value);
	populate_field_dropdown(
		frm,
		"value_changed_field",
		(df) => !NOTIFICATION_ENGINE_LAYOUT_FIELDTYPES.includes(df.fieldtype),
		clear_value
	);
}

function populate_field_dropdown(frm, fieldname, filter_fn, clear_value) {
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
		const options = (meta.fields || []).filter(filter_fn).map((df) => df.fieldname);

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
