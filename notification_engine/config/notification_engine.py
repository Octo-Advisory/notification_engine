from frappe import _


def get_data():
	return [
		{
			"label": _("Notification Engine"),
			"icon": "fa fa-bell",
			"items": [
				{
					"type": "doctype",
					"name": "Notification Rule",
					"label": _("Notification Rule"),
					"description": _("Define who gets notified, for which document event, and how."),
				},
				{
					"type": "doctype",
					"name": "Notification User Preference",
					"label": _("Notification User Preference"),
					"description": _("Per-user opt-out of a specific Notification Rule."),
				},
				{
					"type": "doctype",
					"name": "Notification Engine Log",
					"label": _("Notification Engine Log"),
					"description": _("Delivery audit trail: who was notified, via which channel, and whether it succeeded."),
				},
				{
					"type": "doctype",
					"name": "Notification Engine Settings",
					"label": _("Notification Engine Settings"),
					"description": _("SMS gateway configuration."),
				},
			],
		}
	]
