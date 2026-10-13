import frappe
from frappe import _

TEAMS_ADMIN = "Teams Admin"
# Requests from the Bot Connector run as this user once their token is validated. It has no roles.
BOT_USER = "teams-bot@teams-notify.invalid"
# The standalone app this module replaces. It defines the same Teams DocTypes.
LEGACY_APP = "teams_notify"


def check_legacy_app_removed():
	"""before_install / before_migrate: the Teams DocTypes cannot belong to two apps on one site."""
	if LEGACY_APP not in frappe.get_installed_apps():
		return
	frappe.throw(
		_(
			"The {0} app is installed on this site. Notification Engine now includes Teams, with the same "
			"DocTypes. Run `bench --site {1} remove-from-installed-apps {0}` (keeps its data: destinations, "
			"settings, logs and rules are taken over), then migrate again."
		).format(LEGACY_APP, frappe.local.site),
		title=_("Remove Teams Notify first"),
	)


def setup():
	ensure_role()
	ensure_bot_user()


def ensure_role():
	"""Create the Teams Admin role. The fixture does the same on migrate; this covers fresh installs."""
	if frappe.db.exists("Role", TEAMS_ADMIN):
		return
	frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": TEAMS_ADMIN,
			"desk_access": 1,
		}
	).insert(ignore_permissions=True)


def ensure_bot_user():
	if frappe.db.exists("User", BOT_USER):
		return
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": BOT_USER,
			"first_name": "Teams Bot",
			"user_type": "Website User",
			"send_welcome_email": 0,
			"enabled": 1,
		}
	)
	user.flags.no_welcome_mail = True
	user.insert(ignore_permissions=True)
