import frappe
from frappe import _
from frappe.model.document import Document


class NotificationRule(Document):
	def validate(self):
		self.validate_recipient_source()
		self.validate_event_fields()
		self.validate_email_delivery()

	def validate_recipient_source(self):
		if self.recipient_source == "Role \u2192 Expand To Users" and not self.role:
			frappe.throw(_("Role is required when Recipient Source is 'Role \u2192 Expand To Users'"))

		if self.recipient_source == "Document Field (User)" and not self.document_field:
			frappe.throw(_("Document Field is required when Recipient Source is 'Document Field (User)'"))

		if self.recipient_source == "Workflow Roles (Project + Department)":
			# When "Notify Only Current State's Approver" is on, a rule can
			# validly rely purely on the Direct Role Holder fallback (step 3
			# of the resolution chain) with no Project or Department context
			# at all - e.g. a workflow state that just requires the CEO,
			# unrelated to any project or department. Only require at least
			# one of the two fields when that fallback chain isn't in play,
			# since without it there'd be no source of recipients at all.
			if not self.match_current_state_role and not self.project_field and not self.department_field:
				frappe.throw(
					_("Set at least one of Project Field / Department Field when Recipient Source is "
					  "'Workflow Roles (Project + Department)' - unless 'Notify Only Current State's "
					  "Approver' is enabled, which can resolve directly via Role assignment "
					  "(e.g. CEO/MD/Purchase Head) without either field.")
				)

		no_recipient_table_sources = ("Document Field (User)", "Workflow Roles (Project + Department)")
		if self.recipient_source not in no_recipient_table_sources and not self.recipients:
			frappe.msgprint(
				_(
					"No recipients configured yet. This rule will not notify anyone until you add at "
					"least one enabled recipient, or use 'Sync From Role'."
				),
				indicator="orange",
				alert=True,
			)

	def validate_event_fields(self):
		if self.event == "Value Change" and not self.value_changed_field:
			frappe.throw(_("Field To Watch is required for the 'Value Change' event"))

		if self.event in ("Days Before", "Days After"):
			if not self.date_field:
				frappe.throw(_("Date Field is required for '{0}' event").format(self.event))
			if not self.days_offset:
				frappe.throw(_("Number Of Days is required for '{0}' event").format(self.event))

	def validate_email_delivery(self):
		if not self.send_email:
			return

		if not self.email_delivery_mode:
			self.email_delivery_mode = "Individual Emails"

		if self.email_delivery_mode == "Single Email (To)" and self.recipient_source == "Document Field (User)":
			# fine either way - just a single recipient in that case - no special handling needed
			pass

	def sync_from_role(self):
		"""Diff-merge the role's current users into the recipients child table.

		Newly added members of the role are appended as enabled rows.
		Existing rows (and their is_enabled toggle) are left untouched, so an
		admin's decision to silence a specific person is never overwritten by
		a later sync. Users who left the role are NOT auto-removed - they are
		left in place so the change is visible and reversible; remove manually
		if desired.
		"""
		if not self.role:
			frappe.throw(_("Set a Role before syncing"))

		existing_users = {row.user for row in self.recipients}
		role_users = frappe.get_all(
			"Has Role",
			filters={"role": self.role, "parenttype": "User"},
			pluck="parent",
		)
		# only active, non-system users
		active_role_users = set(
			frappe.get_all(
				"User",
				filters={"name": ["in", role_users], "enabled": 1, "user_type": "System User"},
				pluck="name",
			)
		)

		added = 0
		for user in active_role_users:
			if user in existing_users:
				continue
			self.append(
				"recipients",
				{"user": user, "is_enabled": 1, "added_via": "Role Expansion"},
			)
			added += 1

		self.save()
		return added

	def preview_role_resolution(self):
		"""Runs the automatic Project/Department resolution against the
		configured sample document and returns a rendered HTML table for
		the preview field.
		"""
		from notification_engine.engine.role_resolver import resolve_via_project_department, render_preview_html

		if not self.sample_reference_document:
			frappe.throw(_("Set a Sample Reference Document before previewing"))

		sample_doc = frappe.get_doc(self.reference_doctype, self.sample_reference_document)
		_users, details, state_info = resolve_via_project_department(self, sample_doc)
		return render_preview_html(details, state_info)


@frappe.whitelist()
def sync_role_users(name):
	"""Whitelisted wrapper so this can be called from the Desk 'Sync From Role' action."""
	doc = frappe.get_doc("Notification Rule", name)
	doc.check_permission("write")
	added = doc.sync_from_role()
	frappe.msgprint(_("Added {0} new recipient(s) from role '{1}'").format(added, doc.role))
	return added


@frappe.whitelist()
def preview_role_resolution(name):
	"""Whitelisted wrapper for the 'Preview Resolved Users' button. Read-only:
	does not save the rule, just runs resolution against the sample document
	and returns the rendered HTML table.
	"""
	doc = frappe.get_doc("Notification Rule", name)
	doc.check_permission("read")
	return doc.preview_role_resolution()


@frappe.whitelist()
def generate_rules_for_active_workflows():
	"""Scans every DocType with an active Workflow and creates a draft
	(disabled) Notification Rule for any that don't already have one using
	'Workflow Roles (Project + Department)' + 'Notify Only Current State's
	Approver'. This is how the "only the person responsible for whatever
	the current state requires gets notified" pattern gets rolled out
	across every workflow-enabled doctype, not just one - each doctype
	still needs a human to review the generated rule (set Project/Department
	Field where applicable - the field only exists on some doctypes - and
	tick Enabled), since a blanket auto-enable across every doctype in the
	system would be reckless.
	"""
	frappe.only_for("System Manager")

	workflows = frappe.get_all(
		"Workflow",
		filters={"is_active": 1},
		fields=["name", "document_type", "workflow_state_field"],
	)

	created = []
	skipped = []

	for wf in workflows:
		if not wf.document_type:
			continue

		already_exists = frappe.db.exists(
			"Notification Rule",
			{
				"reference_doctype": wf.document_type,
				"recipient_source": "Workflow Roles (Project + Department)",
			},
		)
		if already_exists:
			skipped.append(wf.document_type)
			continue

		state_field = wf.workflow_state_field or "workflow_state"

		rule = frappe.get_doc(
			{
				"doctype": "Notification Rule",
				"title": f"{wf.document_type} - Workflow Approval",
				"is_enabled": 0,  # deliberately OFF - review before enabling
				"reference_doctype": wf.document_type,
				"event": "Value Change",
				"value_changed_field": state_field,
				"recipient_source": "Workflow Roles (Project + Department)",
				"match_current_state_role": 1,
				"send_system_notification": 1,
				"send_email": 1,
				"email_delivery_mode": "Single Email (To)",
				"subject": "{{ doc.doctype }} {{ doc.name }} needs your approval",
				"message": (
					f"{{{{ doc.doctype }}}} {{{{ doc.name }}}} is now at status "
					f"'{{{{ doc.get('{state_field}') }}}}' and requires your action.<br><br>"
					f"Click here to view: <a href=\"{{{{ frappe.utils.get_url_to_form(doc.doctype, doc.name) }}}}\">{{{{ doc.name }}}}</a><br><br>"
					f"Regards,<br>Heeru ERP"
				),
			}
		)
		rule.insert(ignore_permissions=True)
		created.append(wf.document_type)

	frappe.db.commit()
	return {"created": created, "skipped": skipped}