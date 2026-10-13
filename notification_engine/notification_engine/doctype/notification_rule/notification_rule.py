import json

import frappe
from frappe import _
from frappe.model import default_fields, no_value_fields, table_fields
from frappe.model.document import Document

from notification_engine.engine.events import OWN_DOCTYPES, clear_rule_cache

# Standard columns that can be shown on a Teams card.
STANDARD_FIELDS = ("name", "owner", "creation", "modified", "modified_by", "docstatus")
# Never send these to Teams.
BLOCKED_FIELDTYPES = {"Password", *table_fields, *no_value_fields}
PERSONAL_TYPES = ("Webhook (Personal via Flow bot)", "Bot (Personal Chat)")
# Recipient sources backed by ERPNext's Employee, which this app does not require.
HR_SOURCES = {"Designation": "designation", "Department": "department"}
USER_CHANNELS = ("send_system_notification", "send_email", "send_sms")


class NotificationRule(Document):
	def validate(self):
		self.validate_reference_doctype()
		self.validate_condition()
		self.validate_recipient_source()
		self.validate_event_fields()
		self.validate_channels()
		self.validate_email_delivery()
		if self.send_teams:
			self.validate_teams()

	def on_update(self):
		clear_rule_cache()

	def on_trash(self):
		clear_rule_cache()

	def after_rename(self, *args, **kwargs):
		clear_rule_cache()

	def validate_recipient_source(self):
		if self.recipient_source == "Role \u2192 Expand To Users" and not self.role:
			frappe.throw(_("Role is required when Recipient Source is 'Role \u2192 Expand To Users'"))

		if self.recipient_source == "Document Field (User)" and not self.document_field:
			frappe.throw(_("Document Field is required when Recipient Source is 'Document Field (User)'"))

		if self.recipient_source == "Document Field (User)" and self.document_field not in ("owner", "modified_by"):
			df = frappe.get_meta(self.reference_doctype).get_field(self.document_field)
			if not df:
				frappe.throw(_("{0} is not a field of {1}").format(self.document_field, self.reference_doctype))

		if self.recipient_source in HR_SOURCES:
			doctype, fieldname = self.recipient_source, HR_SOURCES[self.recipient_source]
			if not frappe.db.exists("DocType", "Employee"):
				frappe.throw(
					_("Recipient Source '{0}' needs ERPNext (Employee / {0}) installed on this site.").format(_(doctype))
				)
			if not self.get(fieldname):
				frappe.throw(_("{0} is required when Recipient Source is '{0}'").format(_(doctype)))
			if not frappe.db.exists(doctype, self.get(fieldname)):
				frappe.throw(_("{0} {1} does not exist").format(_(doctype), self.get(fieldname)))

		if self.recipient_source == "Workflow Roles (Project + Department)":
			if not frappe.db.exists("DocType", "Employee"):
				frappe.throw(
					_("Recipient Source 'Workflow Roles (Project + Department)' needs ERPNext (Employee / Project / Department) installed on this site.")
				)
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

		no_recipient_table_sources = (
			"Document Field (User)",
			"Workflow Roles (Project + Department)",
			"Assigned To",
			*HR_SOURCES,
		)
		# A Teams rule may post only to chats / channels, with nobody to notify individually.
		teams_group_only = self.send_teams and self.teams_destinations and not self.teams_personal_destination
		if self.recipient_source not in no_recipient_table_sources and not self.recipients and not teams_group_only:
			frappe.msgprint(
				_(
					"No recipients configured yet. This rule will not notify anyone until you add at "
					"least one enabled recipient, or use 'Sync From Role'."
				),
				indicator="orange",
				alert=True,
			)

	def validate_event_fields(self):
		if self.event == "Value Change":
			if not self.value_changed_field:
				frappe.throw(_("Field To Watch is required for the 'Value Change' event"))
			meta = frappe.get_meta(self.reference_doctype)
			if not (meta.get_field(self.value_changed_field) or self.value_changed_field in default_fields):
				frappe.throw(_("{0} is not a field of {1}").format(self.value_changed_field, self.reference_doctype))

		if self.event in ("Days Before", "Days After"):
			if not self.date_field:
				frappe.throw(_("Date Field is required for '{0}' event").format(self.event))
			df = frappe.get_meta(self.reference_doctype).get_field(self.date_field)
			if self.date_field not in ("creation", "modified") and not (df and df.fieldtype in ("Date", "Datetime")):
				frappe.throw(_("{0} is not a Date or Datetime field of {1}").format(self.date_field, self.reference_doctype))
			if not self.days_offset:
				frappe.throw(_("Number Of Days is required for '{0}' event").format(self.event))

	def validate_reference_doctype(self):
		if self.reference_doctype in OWN_DOCTYPES:
			frappe.throw(_("Notification Engine's own DocTypes cannot have notification rules."))
		meta = frappe.get_meta(self.reference_doctype)
		if meta.istable:
			frappe.throw(_("{0} is a child table. Create the rule on its parent DocType.").format(self.reference_doctype))
		if self.event in ("On Submit", "On Cancel") and not meta.is_submittable:
			frappe.throw(_("{0} is not submittable, so it has no {1} event.").format(self.reference_doctype, _(self.event)))

	def validate_condition(self):
		if not (self.condition or "").strip():
			return
		try:
			compile(self.condition, "<condition>", "eval")
		except SyntaxError as e:
			frappe.throw(_("Condition is not a valid Python expression: {0}").format(e.msg), title=_("Invalid Condition"))

	def validate_channels(self):
		if not any(self.get(f) for f in (*USER_CHANNELS, "send_teams")):
			frappe.msgprint(_("No channel is ticked yet, so this rule sends nothing."), indicator="orange", alert=True)
		if any(self.get(f) for f in USER_CHANNELS) and not (self.message or "").strip():
			frappe.throw(_("Message is required for System Notification, Email and SMS."))

	def validate_teams(self):
		"""The Microsoft Teams section: destinations, card fields, buttons and templates."""
		if not self.teams_destinations and not self.teams_personal_destination:
			frappe.throw(_("Microsoft Teams is ticked: add a Teams chat / channel or a Personal Destination."))

		seen = set()
		for row in self.teams_destinations:
			if row.destination in seen:
				frappe.throw(_("Teams Chats / Channels row {0}: {1} is listed twice.").format(row.idx, row.destination))
			seen.add(row.destination)
			if _destination_type(row.destination) in PERSONAL_TYPES:
				frappe.throw(
					_("Teams Chats / Channels row {0}: {1} sends personal messages. Use it as Personal Destination instead.").format(
						row.idx, row.destination
					)
				)
		if self.teams_personal_destination and _destination_type(self.teams_personal_destination) not in PERSONAL_TYPES:
			frappe.throw(
				_("Personal Destination must be a 'Bot (Personal Chat)' or 'Webhook (Personal via Flow bot)' destination.")
			)

		meta = frappe.get_meta(self.reference_doctype)
		seen = set()
		for row in self.teams_fields:
			if row.fieldname in seen:
				frappe.throw(_("Fields to Show row {0}: {1} is listed twice.").format(row.idx, row.fieldname))
			seen.add(row.fieldname)
			if row.fieldname in STANDARD_FIELDS:
				continue
			df = meta.get_field(row.fieldname)
			if not df:
				frappe.throw(_("Fields to Show row {0}: {1} is not a field of {2}.").format(row.idx, row.fieldname, self.reference_doctype))
			if df.fieldtype in BLOCKED_FIELDTYPES:
				frappe.throw(_("Fields to Show row {0}: {1} fields cannot be sent to Teams.").format(row.idx, _(df.fieldtype)))

		self.validate_teams_buttons()
		self.validate_teams_templates()

	def validate_teams_buttons(self):
		from frappe.model.workflow import get_workflow_name

		if not (self.teams_all_workflow_actions or self.teams_buttons):
			return
		workflow_rows = [r for r in self.teams_buttons if r.button_type == "Workflow Action"]
		if self.teams_all_workflow_actions or workflow_rows:
			workflow_name = get_workflow_name(self.reference_doctype)
			if not workflow_name:
				frappe.throw(_("{0} has no active Workflow, so it has no workflow actions.").format(self.reference_doctype))
			actions = set(frappe.get_all("Workflow Transition", {"parent": workflow_name}, pluck="action"))
			seen = set()
			for row in workflow_rows:
				if row.workflow_action not in actions:
					frappe.throw(
						_("Buttons row {0}: {1} is not an action of workflow {2}.").format(
							row.idx, row.workflow_action, workflow_name
						)
					)
				if row.workflow_action in seen:
					frappe.throw(_("Buttons row {0}: {1} is listed twice.").format(row.idx, row.workflow_action))
				seen.add(row.workflow_action)

		meta = frappe.get_meta(self.reference_doctype)
		for row in self.teams_buttons:
			if row.button_type != "Set Value":
				continue
			df = meta.get_field(row.fieldname) if row.fieldname else None
			if not df:
				frappe.throw(_("Buttons row {0}: choose a field of {1} to set.").format(row.idx, self.reference_doctype))
			if df.fieldtype in BLOCKED_FIELDTYPES or df.fieldtype in ("Attach", "Attach Image", "Signature"):
				frappe.throw(_("Buttons row {0}: {1} fields cannot be set from Teams.").format(row.idx, _(df.fieldtype)))
			if not row.label:
				frappe.throw(_("Buttons row {0}: enter a label for the Set Value button.").format(row.idx))

		destinations = [r.destination for r in self.teams_destinations] + [self.teams_personal_destination]
		if not any((_destination_type(d) or "").startswith("Bot") for d in destinations if d):
			frappe.msgprint(
				_("Buttons only appear on cards sent by the Teams bot. This rule has no bot destination yet."),
				indicator="orange",
				alert=True,
			)

	def validate_teams_templates(self):
		"""Render the Teams card against a sample document so mistakes show up on save."""
		from notification_engine.teams.cards.builder import build_card
		from notification_engine.teams.templates import get_context, render

		doc = get_sample_doc(self.reference_doctype)
		try:
			build_card(self, doc)
		except json.JSONDecodeError as e:
			frappe.throw(_("Teams Card Template did not render valid JSON: {0}").format(e), title=_("Invalid Card Template"))
		except frappe.ValidationError:
			raise
		except Exception as e:
			frappe.throw(_("Teams template error: {0}").format(e), title=_("Invalid Template"))

		if (self.teams_card_template or "").strip():
			card = json.loads(render(self.teams_card_template, get_context(doc)))
			if not isinstance(card, dict) or card.get("type") != "AdaptiveCard":
				frappe.throw(_('Teams Card Template must render a JSON object with "type": "AdaptiveCard".'))

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
		from notification_engine.engine.role_resolver import (
			render_preview_html,
			resolve_via_project_department,
		)

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
def get_hr_options(doctype):
	"""Options for the Designation / Department pickers. Empty when ERPNext isn't installed."""
	if doctype not in HR_SOURCES or not frappe.db.exists("DocType", doctype):
		return []
	return frappe.get_all(doctype, pluck="name", order_by="name asc")


def get_sample_doc(doctype, name=None):
	"""The given document, else the latest one, else a blank new document."""
	if name:
		return frappe.get_doc(doctype, name)
	meta = frappe.get_meta(doctype)
	if meta.issingle:
		return frappe.get_doc(doctype)
	latest = frappe.get_all(doctype, order_by="modified desc", limit=1, pluck="name")
	if latest:
		return frappe.get_doc(doctype, latest[0])
	doc = frappe.new_doc(doctype)
	doc.name = _("Sample")
	return doc


def _destination_type(destination):
	if not destination:
		return None
	return frappe.db.get_value("Teams Destination", destination, "destination_type")


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
