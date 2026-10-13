import frappe
from frappe import _


def render(template: str | None, context: dict) -> str:
	"""Render a Jinja string in Frappe's sandboxed environment.

	frappe.render_template guesses that one-line strings ending in e.g. ".txt" are file paths;
	rule templates are always strings, so render them directly.
	"""
	if not template:
		return ""
	if ".__" in template:
		frappe.throw(_("Illegal template"))

	from frappe.utils.jinja import get_jenv

	return get_jenv().from_string(template).render(context)


def get_context(doc) -> dict:
	# Frappe's jinja environment already exposes its safe `frappe` globals; only add the doc.
	return {"doc": doc}
