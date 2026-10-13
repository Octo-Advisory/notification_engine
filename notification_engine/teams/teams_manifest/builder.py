"""Build the Teams app package (manifest.json + icons) that IT uploads in Teams Admin Center."""

import io
import json
import os
import zipfile
from urllib.parse import urlparse

import frappe
from frappe import _

from notification_engine import __version__

HERE = os.path.dirname(__file__)
PACKAGE_NAME = "teams_notify_app.zip"


def build_manifest() -> dict:
	from notification_engine.teams.bot.auth import get_bot_settings
	from notification_engine.teams.cards.builder import get_site_url

	settings = get_bot_settings()
	if not settings.app_id:
		frappe.throw(_("Set the bot App (Client) ID in Teams Settings first."))
	site_url = get_site_url()
	host = urlparse(site_url).hostname or ""
	values = {
		"version": _semver(__version__),
		"app_id": settings.app_id,
		"developer_name": (frappe.db.get_single_value("System Settings", "app_name") or "Frappe")[:32],
		"site_url": site_url if site_url.startswith("https://") else f"https://{host}",
		"site_host": host,
		"short_name": settings.name[:30],
		"full_name": settings.name[:100],
	}
	text = open(os.path.join(HERE, "manifest.template.json")).read()
	for key, value in values.items():
		text = text.replace("{{ " + key + " }}", json.dumps(value)[1:-1])
	return json.loads(text)


def build_package() -> bytes:
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
		zf.writestr("manifest.json", json.dumps(build_manifest(), indent=2))
		for icon in ("color.png", "outline.png"):
			zf.write(os.path.join(HERE, icon), icon)
	return buffer.getvalue()


def write_package() -> str:
	"""Write the package into the site's private files folder and return its path."""
	path = frappe.get_site_path("private", "files", PACKAGE_NAME)
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "wb") as f:
		f.write(build_package())
	return os.path.abspath(path)


def _semver(version: str) -> str:
	parts = (version.split("+")[0].split("-")[0].split(".") + ["0", "0", "0"])[:3]
	return ".".join(p if p.isdigit() else "0" for p in parts)
