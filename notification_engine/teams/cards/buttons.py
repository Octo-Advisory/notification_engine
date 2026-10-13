"""Card buttons (Adaptive Card Action.Execute) for cards sent by the Teams bot.

A button's data carries only a key. What the key does (which workflow action, which field and value)
is always read again from the rule on the server when it is clicked.
"""

import frappe
from frappe import _

VERB = "teams_notify.action"
BUTTON_CARD_VERSION = "1.5"
STYLES = {"positive", "destructive"}


def get_buttons(rule, doc) -> list[frappe._dict]:
	"""Buttons for `doc` in its current state: [{key, title, style, ask_comment, comment_required, row}]."""
	# Rows are child Documents (rule loaded at click time) or dicts (rule from the cache).
	rows = [frappe._dict(r.as_dict() if hasattr(r, "as_dict") and not isinstance(r, dict) else r) for r in (rule.get("teams_buttons") or [])]
	buttons = []

	actions = available_workflow_actions(doc)
	by_action = {r.workflow_action: r for r in rows if r.button_type == "Workflow Action"}
	wanted = actions if rule.get("teams_all_workflow_actions") else [a for a in actions if a in by_action]
	for action in wanted:
		row = by_action.get(action) or frappe._dict()
		buttons.append(
			frappe._dict(
				key=f"wf:{action}",
				title=_(row.label or action),
				style=row.style,
				ask_comment=bool(row.ask_comment),
				comment_required=bool(row.comment_required),
				row=row,
			)
		)

	for row in rows:
		if row.button_type == "Set Value" and row.fieldname:
			buttons.append(
				frappe._dict(
					key=f"set:{row.name or row.idx}",
					title=_(row.label or _("Set {0}").format(row.fieldname)),
					style=row.style,
					ask_comment=bool(row.ask_comment),
					comment_required=bool(row.comment_required),
					row=row,
				)
			)
	return buttons


def find_button(rule, doc, key: str):
	"""The button with `key` if the rule still offers it for `doc` (ignores the current user's roles)."""
	return next((b for b in get_buttons(rule, doc) if b.key == key), None)


def available_workflow_actions(doc) -> list[str]:
	"""Workflow actions from the document's current state whose conditions pass, for any role."""
	from frappe.model.workflow import get_workflow_name, is_transition_condition_satisfied

	workflow_name = get_workflow_name(doc.doctype)
	if not workflow_name:
		return []
	workflow = frappe.get_cached_doc("Workflow", workflow_name)
	state = doc.get(workflow.workflow_state_field)
	actions = []
	for transition in workflow.transitions:
		if transition.state == state and transition.action not in actions:
			try:
				if is_transition_condition_satisfied(transition, doc):
					actions.append(transition.action)
			except Exception:
				continue
	return actions


def add_buttons(card: dict, rule, doc, test: bool = False) -> dict:
	"""Add Action.Execute buttons to a card (in place). Open in Frappe stays last."""
	buttons = get_buttons(rule, doc)
	if not buttons:
		return card

	data_base = {
		"doctype": doc.doctype,
		"name": doc.name,
		"rule": rule.get("name"),
		"modified": str(doc.get("modified") or ""),
	}
	if test:
		data_base["test"] = 1

	actions = []
	for button in buttons:
		data = {**data_base, "key": button.key}
		execute = {"type": "Action.Execute", "title": button.title, "verb": VERB, "data": data}
		if button.style in STYLES:
			execute["style"] = button.style
		if not button.ask_comment:
			actions.append(execute)
			continue
		comment_input = {
			"type": "Input.Text",
			"id": "comment",
			"isMultiline": True,
			"placeholder": _("Add a comment"),
			"label": _("Comment"),
		}
		if button.comment_required:
			comment_input.update({"isRequired": True, "errorMessage": _("A comment is required.")})
		show_card = {
			"type": "Action.ShowCard",
			"title": button.title,
			"card": {
				"type": "AdaptiveCard",
				"body": [comment_input],
				"actions": [{**execute, "title": _("Submit: {0}").format(button.title)}],
			},
		}
		if button.style in STYLES:
			show_card["style"] = button.style
		actions.append(show_card)

	card["version"] = BUTTON_CARD_VERSION
	open_actions = [a for a in card.get("actions") or [] if a.get("type") == "Action.OpenUrl"]
	card["actions"] = actions + open_actions
	return card
