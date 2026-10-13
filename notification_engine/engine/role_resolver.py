import frappe
from frappe import _


def resolve_via_project_department(rule, doc):
	"""Given a document, automatically finds the relevant users based purely
	on its Project and Department values - no manual role selection by the
	admin.

	Two modes:

	**Notify Only Current State's Approver = OFF** (general "keep everyone
	informed" mode): combines two sources -
	  1. The Project's own Committee (Project.custom_roles, doctype
	     "Project Role"), every applicable row.
	  2. The Department Head of the document's department.

	**Notify Only Current State's Approver = ON** (targeted approval
	routing): finds the single Role required by the document's CURRENT
	Workflow state (Workflow Document State.allow_edit), then resolves it
	through a priority chain:
	  1. Project Committee - if a committee row is bound to that Role
	     (via Role Master.internal_role_name) and resolves to a valid,
	     active user who genuinely still holds that Role, use them.
	  2. Department Head - only if the department head happens to
	     actually hold the required Role themselves (checked via
	     frappe.get_roles) - this covers cases where "Department Head" or
	     similar IS the state's required role.
	  3. Direct Role Holder - anyone in the system directly assigned that
	     Frappe Role (via Has Role), with no project/department context
	     needed at all. This is what covers company-wide singular roles
	     like CEO / MD / Purchase Head that were never going to appear in
	     a Project Committee table in the first place.
	Each step only runs if the previous one found nobody valid - Project
	Committee takes priority when the role IS in the committee, falling
	through to direct resolution when it isn't.

	`doc` needs to expose the Project/Department values via
	rule.project_field / rule.department_field - works with a real Document
	instance (production dispatch) or any object supporting .get(fieldname)
	(used by the preview button against a sample document).

	Every candidate is checked for an active Employee record before being
	included. Project Committee candidates get an additional check: the
	resolved user must currently hold the Frappe Role their committee
	position claims to be bound to - not just be listed in the table.

	Returns (valid_user_list, details, current_state_info).
	"""
	match_current_state_only = bool(rule.get("match_current_state_role"))

	project_value = doc.get(rule.project_field) if rule.project_field else None
	department_value = doc.get(rule.department_field) if rule.department_field else None

	current_state_info = None

	if match_current_state_only:
		details, current_state_info = _resolve_current_state_approver(project_value, department_value, doc)
	else:
		details = []

		if project_value:
			details.extend(_resolve_project_roles(project_value))
		elif rule.project_field:
			details.append(_no_value_row("Project Role", "Document has no value in the configured Project field"))

		if department_value:
			details.extend(_resolve_department_head(department_value))
		elif rule.department_field:
			details.append(_no_value_row("Department Head", "Document has no value in the configured Department field"))

	valid_users = list(dict.fromkeys([d["user"] for d in details if d["valid"] and d["user"]]))
	return valid_users, details, current_state_info


def _resolve_current_state_approver(project_value, department_value, doc):
	"""The priority chain described in resolve_via_project_department's
	docstring: Project Committee -> Department Head (if role matches) ->
	Direct Role Holder. Stops as soon as a step produces at least one
	valid candidate.
	"""
	approver_role, current_state_info = _get_current_state_approver_role(doc)

	if not approver_role:
		return [
			_no_value_row(
				"Current State Approver",
				"Could not determine an approver role for the document's current workflow state "
				"(no active Workflow, no state value, or state has no 'allow_edit' role set)",
			)
		], current_state_info

	details = []

	# 1. Project Committee - preferred source when the role is bound there
	if project_value:
		committee_matches = [
			d for d in _resolve_project_roles(project_value) if d.get("bound_role") == approver_role
		]
		details.extend(committee_matches)
		if any(d["valid"] for d in committee_matches):
			return details, current_state_info
		# role either isn't bound to any committee position, or the bound
		# person failed validation (inactive employee / role mismatch) -
		# fall through to the next source below

	# 2. Department Head - only relevant if they actually hold this Role
	if department_value:
		dept_user = frappe.db.get_value("Department", department_value, "custom_department_head_user_id")
		if dept_user and approver_role in frappe.get_roles(dept_user):
			is_valid, employee, reason = _validate_active_employee(dept_user)
			details.append(
				{
					"source": "Department Head",
					"user": dept_user,
					"employee": employee,
					"valid": is_valid,
					"reason": reason,
					"bound_role": approver_role,
				}
			)
			if is_valid:
				return details, current_state_info
		# if the department head doesn't hold the required role at all,
		# they're simply not a candidate for this approval - no row added,
		# since they're not relevant here rather than "excluded"

	# 3. Direct Role Holder - anyone in the system directly assigned this
	# Frappe Role, no project/department context required. Covers
	# company-wide singular roles (CEO, MD, Purchase Head) that were never
	# going to be in a Project Committee table to begin with.
	direct_users = frappe.get_all("Has Role", filters={"role": approver_role, "parenttype": "User"}, pluck="parent")

	if not direct_users:
		details.append(
			_no_value_row(
				f"Direct Role Holder ({approver_role})",
				f"No committee member, department head, or directly-assigned user was found for the "
				f"required role '{approver_role}'",
			)
		)
		return details, current_state_info

	for user in direct_users:
		is_valid, employee, reason = _validate_active_employee(user)
		details.append(
			{
				"source": f"Direct Role Holder ({approver_role})",
				"user": user,
				"employee": employee,
				"valid": is_valid,
				"reason": reason,
				"bound_role": approver_role,
			}
		)

	return details, current_state_info


def _resolve_project_roles(project):
	"""Reads the Project's own committee table (custom_roles / Project Role)
	directly. Each row is matched to its Role Master record (by name, since
	Role Master autonames from its `role` text) to get the bound Frappe
	Role and the applicable flag.
	"""
	rows = frappe.get_all(
		"Project Role",
		filters={"parent": project},
		fields=["role", "project_employee", "user"],
	)

	if not rows:
		return [_no_value_row("Project Role", "No Project Committee rows found for this project")]

	details = []
	for row in rows:
		if not row.role:
			continue

		role_master = frappe.db.get_value(
			"Role Master", row.role, ["internal_role_name", "applicable"], as_dict=True
		)

		if not role_master:
			details.append(
				{
					"source": f"Project Role ({row.role})",
					"user": None,
					"employee": None,
					"valid": False,
					"reason": f"No Role Master record found for '{row.role}' - add one to bind it to a Frappe Role",
					"bound_role": None,
				}
			)
			continue

		if not role_master.applicable:
			# Marked not applicable in Role Master - intentionally excluded
			# from automation, not reported as an error in the preview.
			continue

		bound_role = role_master.internal_role_name
		source = f"Project Committee ({row.role})"

		user = row.user
		employee = row.project_employee
		if not user and row.project_employee:
			user = frappe.db.get_value("Employee", row.project_employee, "user_id")

		if not user:
			details.append(
				{
					"source": source,
					"user": None,
					"employee": employee,
					"valid": False,
					"reason": "This committee role has no person assigned for this project yet",
					"bound_role": bound_role,
				}
			)
			continue

		is_valid, resolved_employee, reason = _validate_recipient(user, bound_role)
		details.append(
			{
				"source": source,
				"user": user,
				"employee": employee or resolved_employee,
				"valid": is_valid,
				"reason": reason,
				"bound_role": bound_role,
			}
		)
	return details


def _resolve_department_head(department):
	user = frappe.db.get_value("Department", department, "custom_department_head_user_id")
	if not user:
		return [_no_value_row("Department Head", "Department has no Department Head User ID set")]

	is_valid, employee, reason = _validate_active_employee(user)
	return [
		{"source": "Department Head", "user": user, "employee": employee, "valid": is_valid,
		 "reason": reason, "bound_role": None}
	]


def _get_current_state_approver_role(doc):
	"""Looks up the reference doctype's active Workflow, finds the document's
	current state value, and returns the Role permitted to act on the
	document while it's in that state (Workflow Document State.allow_edit).

	Returns (role_or_None, info_dict_for_preview).
	"""
	workflow = frappe.db.get_value(
		"Workflow", {"document_type": doc.doctype, "is_active": 1}, ["name", "workflow_state_field"], as_dict=True
	)
	if not workflow:
		return None, {"workflow": None, "state_field": None, "state_value": None, "approver_role": None}

	state_value = doc.get(workflow.workflow_state_field)
	if not state_value:
		return None, {
			"workflow": workflow.name, "state_field": workflow.workflow_state_field,
			"state_value": None, "approver_role": None,
		}

	approver_role = frappe.db.get_value(
		"Workflow Document State", {"parent": workflow.name, "state": state_value}, "allow_edit"
	)
	return approver_role, {
		"workflow": workflow.name,
		"state_field": workflow.workflow_state_field,
		"state_value": state_value,
		"approver_role": approver_role,
	}


def _validate_active_employee(user):
	"""Every resolved user, via any path, must have an active Employee
	record. Assumes the standard ERPNext Employee fields `user_id` and
	`status` (with "Active" as the active-status value) - adjust the
	filter here if your Employee status options differ.
	"""
	employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
	if employee:
		return True, employee, "OK"

	has_any_employee = frappe.db.exists("Employee", {"user_id": user})
	if has_any_employee:
		return False, None, "Employee record exists but is not Active"
	return False, None, "No Employee record found for this user"


def _validate_recipient(user, bound_role):
	"""Project Committee entries only. Combines the active-Employee check
	with a check that the user actually holds the Frappe Role their
	committee position claims to be bound to.
	"""
	is_active, employee, reason = _validate_active_employee(user)
	if not is_active:
		return False, employee, reason

	if bound_role and bound_role not in frappe.get_roles(user):
		return False, employee, f"User does not currently have the '{bound_role}' Role assigned"

	return True, employee, "OK"


def _no_value_row(source, reason):
	return {"source": source, "user": None, "employee": None, "valid": False, "reason": reason, "bound_role": None}


def render_preview_html(details, current_state_info=None):
	"""Builds the HTML table shown in the Notification Rule's preview field.
	Only VALID (active-employee-checked) users are shown here - excluded
	candidates are omitted entirely rather than shown greyed out. A summary
	line reports how many were excluded, without listing them.
	"""
	state_note = ""
	if current_state_info:
		if current_state_info.get("state_value"):
			role_text = current_state_info.get("approver_role") or "no approver role set for this state"
			state_note = (
				f"<p style='color:#555;margin-bottom:6px'>Current state "
				f"<b>{frappe.utils.escape_html(current_state_info['state_value'])}</b> "
				f"(field <code>{frappe.utils.escape_html(current_state_info['state_field'])}</code>) "
				f"requires: <b>{frappe.utils.escape_html(role_text)}</b></p>"
			)
		elif current_state_info.get("workflow") is None:
			state_note = "<p style='color:#c62828;margin-bottom:6px'>No active Workflow found for this doctype.</p>"

	if not details:
		return state_note + "<p style='color:#888'>Set a Sample Reference Document and click Preview to see results here.</p>"

	valid_rows = [d for d in details if d["valid"] and d["user"]]
	excluded_count = len(details) - len(valid_rows)

	if not valid_rows:
		return (
			state_note
			+ "<p style='color:#c62828'>No valid users resolved. "
			f"{excluded_count} candidate(s) were excluded - check Project Committee assignments, "
			"Role Master bindings, Department Head, and active Employee records.</p>"
		)

	rows = []
	for d in valid_rows:
		bound_role = d.get("bound_role")
		role_html = (
			f"<span style='background:#e8f0fe;color:#1a56db;border-radius:3px;"
			f"padding:1px 6px;font-size:12px'>{frappe.utils.escape_html(bound_role)}</span>"
			if bound_role else "<span style='color:#999'>-</span>"
		)
		rows.append(
			"<tr>"
			f"<td>{frappe.utils.escape_html(d['source'] or '')}</td>"
			f"<td>{frappe.utils.escape_html(d['user'] or '-')}</td>"
			f"<td>{frappe.utils.escape_html(d['employee'] or '-')}</td>"
			f"<td>{role_html}</td>"
			"</tr>"
		)

	summary = (
		f"<p style='color:#888;margin-bottom:6px'>{len(valid_rows)} user(s) will be notified"
		+ (f" - {excluded_count} candidate(s) excluded (not shown)" if excluded_count else "")
		+ "</p>"
	)

	return (
		state_note
		+ summary
		+ "<table class='table table-bordered' style='margin-top:4px'>"
		"<thead><tr>"
		"<th>Source</th><th>User</th><th>Employee</th><th>Bound Role</th>"
		"</tr></thead>"
		f"<tbody>{''.join(rows)}</tbody>"
		"</table>"
	)
