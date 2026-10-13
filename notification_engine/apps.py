import frappe

APP_ROLES = ("System Manager", "Teams Admin")


def has_app_permission():
	"""Show the Notification Engine tile on /apps to the people who manage notifications."""
	return bool(set(APP_ROLES) & set(frappe.get_roles()))
