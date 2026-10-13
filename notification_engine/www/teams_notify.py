from urllib.parse import quote

import frappe

from notification_engine.teams.api import ADMIN_ROLES

no_cache = 1


def get_context(context):
	# Signed out: log in and come back, rather than load a shell full of 403s.
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + quote(frappe.request.path)
		raise frappe.Redirect(302)
	if not set(ADMIN_ROLES) & set(frappe.get_roles()):
		frappe.throw(frappe._("Only Teams Admin and System Manager can open Teams Notify."), frappe.PermissionError)
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.site_name = frappe.local.site
	return context
