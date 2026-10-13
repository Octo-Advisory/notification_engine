# Copyright (c) 2026, Octo Advisory and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TeamsMessageLog(Document):
	pass


def on_doctype_update():
	frappe.db.add_index("Teams Message Log", ["status", "creation"])
	frappe.db.add_index("Teams Message Log", ["reference_doctype", "reference_name"])
