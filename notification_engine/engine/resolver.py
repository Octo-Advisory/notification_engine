import frappe


def resolve_recipients(rule, doc):
	"""Resolve a Notification Rule + document into a final list of user emails.

	Order of resolution:
	  1. Get the candidate list based on recipient_source.
	  2. Drop anyone whose per-recipient row is disabled (rule.recipients.is_enabled = 0).
	  3. Drop anyone who has personally opted out via Notification User Preference.
	  4. Drop disabled/non-system users defensively.
	"""
	candidates = _get_candidates(rule, doc)
	if not candidates:
		return []

	preferences = _get_preferences(rule.name, candidates)

	final_users = []
	for user in candidates:
		if preferences.get(user) is False:
			continue
		final_users.append(user)

	if not final_users:
		return []

	valid_users = set(
		frappe.get_all(
			"User",
			filters={"name": ["in", final_users], "enabled": 1, "user_type": "System User"},
			pluck="name",
		)
	)
	return [u for u in final_users if u in valid_users]


def _get_candidates(rule, doc):
	if rule.recipient_source == "Document Field (User)":
		value = doc.get(rule.document_field)
		return [value] if value else []

	if rule.recipient_source == "Workflow Roles (Project + Department)":
		from notification_engine.engine.role_resolver import resolve_via_project_department

		users, _details, _state_info = resolve_via_project_department(rule, doc)
		return users

	# "Specific Users" and "Role \u2192 Expand To Users" both ultimately store
	# their resolved list in the recipients child table - the only difference
	# is *how* that table gets populated (manually vs "Sync From Role").
	return [row.user for row in (rule.recipients or []) if row.is_enabled]


def _get_preferences(rule_name, users):
	"""Return {user: is_enabled} for any explicit preference rows that exist.
	Users without a row are treated as enabled (opt-out model, not opt-in).
	"""
	if not users:
		return {}

	rows = frappe.get_all(
		"Notification User Preference",
		filters={"notification_rule": rule_name, "user": ["in", users]},
		fields=["user", "is_enabled"],
	)
	return {row.user: bool(row.is_enabled) for row in rows}
