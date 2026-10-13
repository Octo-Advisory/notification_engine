import click
from frappe.commands import get_site, pass_context


@click.group("notification-engine")
def notification_engine():
	"""Notification Engine commands."""


@notification_engine.command("build-teams-manifest")
@pass_context
def build_manifest(context):
	"""Write the Teams app package (teams_notify_app.zip) to the site's private files."""
	import frappe

	from notification_engine.teams.teams_manifest.builder import write_package

	site = get_site(context)
	frappe.init(site=site)
	frappe.connect()
	try:
		click.echo(write_package())
	finally:
		frappe.destroy()


commands = [notification_engine]
