"""Bot Framework authentication: outgoing access tokens and validation of incoming requests.

Incoming requests are validated in an `auth_hooks` handler (`auth_hook`) because Frappe rejects any
request carrying an `Authorization: Bearer` header that it cannot map to a Frappe user.
"""

import json

import frappe
import jwt
import requests

TIMEOUT_SECONDS = 10
TOKEN_SCOPE = "https://api.botframework.com/.default"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
BOTFRAMEWORK_OPENID = "https://login.botframework.com/v1/.well-known/openidconfiguration"
BOTFRAMEWORK_ISSUER = "https://api.botframework.com"
# Accepted only as a fallback, and only for our own tenant (as the Microsoft 365 Agents SDK does).
ENTRA_ISSUERS = ("https://sts.windows.net/{tenant}/", "https://login.microsoftonline.com/{tenant}/v2.0")
ENTRA_KEYS = "https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
LEEWAY_SECONDS = 300
KEYS_TTL = 24 * 3600
TOKEN_REFRESH_MARGIN = 300
ENDPOINT_PATH = "/api/method/notification_engine.teams.bot.endpoint.receive"
# Endpoint of the former standalone Teams Notify app. Azure Bots registered with it keep working
# (hooks.py override_whitelisted_methods routes it here).
LEGACY_ENDPOINT_METHOD = "teams_notify.bot.endpoint.receive"
ENDPOINT_PATHS = frozenset((ENDPOINT_PATH, f"/api/method/{LEGACY_ENDPOINT_METHOD}"))


class BotAuthError(Exception):
	pass


# ---------------------------------------------------------------- settings


def get_bot_settings() -> frappe._dict:
	get = lambda f: frappe.db.get_single_value("Teams Settings", f)  # noqa: E731
	return frappe._dict(
		enabled=bool(get("bot_enabled")),
		app_id=(get("bot_app_id") or "").strip(),
		tenant_id=(get("bot_tenant_id") or "").strip(),
		service_url=(get("bot_service_url") or "https://smba.trafficmanager.net/teams/").strip(),
		name=get("bot_name") or "ERP Notifications",
	)


def get_client_secret() -> str | None:
	from frappe.utils.password import get_decrypted_password

	return get_decrypted_password("Teams Settings", "Teams Settings", "bot_client_secret", raise_exception=False)


# ---------------------------------------------------------------- outgoing


def _token_key(app_id: str) -> str:
	return f"teams_notify:bot_token:{app_id}"


def get_access_token(force_refresh: bool = False) -> str:
	"""Access token for the Bot Connector API, cached until shortly before it expires."""
	settings = get_bot_settings()
	if not (settings.app_id and settings.tenant_id):
		raise BotAuthError("Teams bot App ID and Tenant ID are not set in Teams Settings.")

	key = _token_key(settings.app_id)
	if not force_refresh:
		cached = frappe.cache.get_value(key, expires=True)
		if cached:
			return cached

	secret = get_client_secret()
	if not secret:
		raise BotAuthError("Teams bot Client Secret is not set in Teams Settings.")

	try:
		response = requests.post(
			TOKEN_URL.format(tenant=settings.tenant_id),
			data={
				"grant_type": "client_credentials",
				"client_id": settings.app_id,
				"client_secret": secret,
				"scope": TOKEN_SCOPE,
			},
			timeout=TIMEOUT_SECONDS,
		)
	except requests.RequestException as e:
		raise BotAuthError(f"Could not reach Microsoft login: {type(e).__name__}")

	if response.status_code != 200:
		try:
			body = response.json()
			detail = body.get("error_description") or body.get("error") or ""
		except ValueError:
			detail = ""
		# error_description never contains the secret; keep the first line only.
		raise BotAuthError(f"Token request failed (HTTP {response.status_code}): {detail.splitlines()[0] if detail else ''}")

	data = response.json()
	token = data["access_token"]
	ttl = int(data.get("expires_in", 3600)) - TOKEN_REFRESH_MARGIN
	frappe.cache.set_value(key, token, expires_in_sec=max(60, ttl))
	return token


def clear_access_token():
	frappe.cache.delete_value(_token_key(get_bot_settings().app_id))


# ---------------------------------------------------------------- incoming


def auth_hook():
	"""Frappe `auth_hooks` entry: authenticate Bot Connector calls to our endpoint only."""
	request = getattr(frappe.local, "request", None)
	if not request or request.path not in ENDPOINT_PATHS:
		return
	header = request.headers.get("Authorization", "")
	if not header:
		return  # the endpoint answers 401

	try:
		activity = json.loads(request.get_data() or b"{}")
		claims = validate_request(header, activity)
	except (BotAuthError, ValueError) as e:
		frappe.logger("notification_engine").warning(f"Rejected Teams bot request: {e}")
		raise frappe.AuthenticationError

	from notification_engine.teams.install import BOT_USER

	frappe.local.teams_bot_claims = claims
	frappe.set_user(BOT_USER)


def validate_request(auth_header: str, activity: dict) -> dict:
	"""Validate a Bot Connector `Authorization` header. Returns the token claims or raises BotAuthError."""
	settings = get_bot_settings()
	if not settings.app_id:
		raise BotAuthError("bot not configured")

	scheme, _, token = (auth_header or "").partition(" ")
	if scheme.lower() != "bearer" or not token:
		raise BotAuthError("missing bearer token")

	try:
		header = jwt.get_unverified_header(token)
		unverified = jwt.decode(token, options={"verify_signature": False})
	except jwt.PyJWTError as e:
		raise BotAuthError(f"malformed token: {e}")

	issuer = unverified.get("iss")
	if issuer == BOTFRAMEWORK_ISSUER:
		keys_url, require_endorsement = _botframework_jwks_uri(), True
	elif settings.tenant_id and issuer in [i.format(tenant=settings.tenant_id) for i in ENTRA_ISSUERS]:
		keys_url, require_endorsement = ENTRA_KEYS.format(tenant=settings.tenant_id), False
	else:
		raise BotAuthError(f"untrusted issuer {issuer!r}")

	if header.get("alg") != "RS256":
		raise BotAuthError("unexpected signing algorithm")

	key = _find_key(keys_url, header.get("kid"))
	if require_endorsement and "endorsements" in key and "msteams" not in key["endorsements"]:
		raise BotAuthError("signing key is not endorsed for msteams")

	try:
		claims = jwt.decode(
			token,
			jwt.PyJWK(key).key,
			algorithms=["RS256"],
			audience=settings.app_id,
			issuer=issuer,
			leeway=LEEWAY_SECONDS,
			options={"require": ["exp", "iss", "aud"]},
		)
	except jwt.PyJWTError as e:
		raise BotAuthError(f"invalid token: {e}")

	if issuer != BOTFRAMEWORK_ISSUER and claims.get("tid") != settings.tenant_id:
		raise BotAuthError("token tenant does not match")

	claim_url = (claims.get("serviceurl") or claims.get("serviceUrl") or "").rstrip("/")
	activity_url = (activity.get("serviceUrl") or "").rstrip("/")
	if issuer == BOTFRAMEWORK_ISSUER and claim_url != activity_url:
		raise BotAuthError("serviceUrl claim does not match the activity")
	return claims


def _botframework_jwks_uri() -> str:
	def fetch():
		return _get_json(BOTFRAMEWORK_OPENID)["jwks_uri"]

	key = "teams_notify:bot_openid_jwks_uri"
	uri = frappe.cache.get_value(key, expires=True)
	if not uri:
		uri = fetch()
		frappe.cache.set_value(key, uri, expires_in_sec=KEYS_TTL)
	return uri


def _find_key(keys_url: str, kid: str | None) -> dict:
	"""Signing key by kid from a JWKS document, cached for 24 h and refetched once on a miss."""
	cache_key = f"teams_notify:bot_jwks:{keys_url}"
	for attempt in range(2):
		keys = None if attempt else frappe.cache.get_value(cache_key, expires=True)
		if not keys:
			keys = _get_json(keys_url).get("keys", [])
			frappe.cache.set_value(cache_key, keys, expires_in_sec=KEYS_TTL)
		for key in keys:
			if key.get("kid") == kid:
				return key
	raise BotAuthError("unknown signing key")


def _get_json(url: str) -> dict:
	try:
		response = requests.get(url, timeout=TIMEOUT_SECONDS)
		response.raise_for_status()
		return response.json()
	except (requests.RequestException, ValueError) as e:
		raise BotAuthError(f"could not load {url}: {type(e).__name__}")
