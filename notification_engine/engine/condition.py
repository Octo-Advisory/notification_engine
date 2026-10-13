import frappe


def evaluate_condition(condition, doc):
	"""Evaluate an optional condition string against a document.

	An empty/blank condition always matches. Uses frappe.safe_eval so rule
	authors cannot execute arbitrary Python (no imports, no attribute access
	to dunder methods, etc.) - the same mechanism Frappe's own core
	Notification / Server Script "condition" fields use.
	"""
	if not condition or not condition.strip():
		return True

	try:
		return bool(frappe.safe_eval(condition, None, {"doc": doc}))
	except Exception:
		frappe.log_error(
			title="Notification Rule condition failed to evaluate",
			message=f"condition={condition!r} doctype={doc.doctype} name={doc.name}",
		)
		# fail closed: a broken condition should not spam everyone
		return False
