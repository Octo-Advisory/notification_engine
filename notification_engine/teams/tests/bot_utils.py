"""Helpers for bot tests: settings, signed Bot Framework tokens, fake HTTP."""

import json
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from frappe.utils.password import set_encrypted_password
from werkzeug.test import EnvironBuilder

from notification_engine.teams.bot import auth

APP_ID = "3f7a9c21-1111-2222-3333-444455556666"
TENANT_ID = "a1b2c3d4-aaaa-bbbb-cccc-ddddeeeeffff"
OTHER_TENANT = "99999999-aaaa-bbbb-cccc-ddddeeeeffff"
SERVICE_URL = "https://smba.trafficmanager.net/amer/"
JWKS_URI = "https://login.botframework.com/v1/.well-known/keys"
KID = "test-key-1"

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_private_key.public_key()))


def jwks(endorsements=("msteams",), kid=KID):
	key = {**_public_jwk, "kid": kid, "use": "sig", "kty": "RSA"}
	if endorsements is not None:
		key["endorsements"] = list(endorsements)
	return {"keys": [key]}


def make_token(**overrides) -> str:
	now = int(time.time())
	claims = {
		"iss": auth.BOTFRAMEWORK_ISSUER,
		"aud": APP_ID,
		"exp": now + 600,
		"nbf": now - 10,
		"serviceurl": SERVICE_URL,
	}
	headers = {"kid": overrides.pop("kid", KID)}
	claims.update(overrides)
	claims = {k: v for k, v in claims.items() if v is not None}
	return jwt.encode(claims, _private_key, algorithm="RS256", headers=headers)


def enable_bot(enabled=1):
	frappe.db.set_single_value(
		"Teams Settings",
		{
			"bot_enabled": enabled,
			"bot_app_id": APP_ID,
			"bot_tenant_id": TENANT_ID,
			"bot_service_url": "https://smba.trafficmanager.net/teams/",
			"bot_name": "ERP Test Bot",
		},
	)
	set_encrypted_password("Teams Settings", "Teams Settings", "test-client-secret", "bot_client_secret")


def clear_bot_cache():
	frappe.cache.delete_value(auth._token_key(APP_ID))
	frappe.cache.delete_value("teams_notify:bot_openid_jwks_uri")
	for url in (JWKS_URI, auth.ENTRA_KEYS.format(tenant=TENANT_ID)):
		frappe.cache.delete_value(f"teams_notify:bot_jwks:{url}")


@contextmanager
def fake_microsoft(keys=None, entra_keys=None):
	"""Serve OpenID metadata and JWKS for both issuers without network calls."""

	def get_json(url):
		if url == auth.BOTFRAMEWORK_OPENID:
			return {"jwks_uri": JWKS_URI}
		if url == JWKS_URI:
			return keys if keys is not None else jwks()
		if url == auth.ENTRA_KEYS.format(tenant=TENANT_ID):
			return entra_keys if entra_keys is not None else jwks(endorsements=None)
		raise AssertionError(f"unexpected URL {url}")

	with patch.object(auth, "_get_json", side_effect=get_json) as mocked:
		yield mocked


def http_response(status=200, body=None, headers=None):
	response = MagicMock()
	response.status_code = status
	response.content = json.dumps(body).encode() if body is not None else b""
	response.text = json.dumps(body) if body is not None else ""
	response.json.side_effect = (lambda: body) if body is not None else ValueError
	response.headers = headers or {}
	return response


@contextmanager
def fake_token(token="access-token-1", expires_in=3600):
	with patch.object(auth.requests, "post", return_value=http_response(200, {"access_token": token, "expires_in": expires_in})) as post:
		yield post


@contextmanager
def fake_connector(*responses):
	with patch("notification_engine.teams.bot.connector.requests.request", side_effect=list(responses)) as request:
		yield request


def activity(kind="message", conversation_type="personal", tenant=TENANT_ID, **extra) -> dict:
	conversation = {"id": "a:personal-conv" if conversation_type == "personal" else "19:group@thread.v2",
		"conversationType": conversation_type, "tenantId": tenant}
	if conversation_type != "personal":
		conversation["name"] = "OCTO Team"
	data = {
		"type": kind,
		"id": "activity-1",
		"serviceUrl": SERVICE_URL,
		"channelId": "msteams",
		"from": {"id": "29:user-1", "aadObjectId": "aad-user-1", "name": "Raj Patel"},
		"recipient": {"id": f"28:{APP_ID}", "name": "ERP Test Bot"},
		"conversation": conversation,
		"channelData": {"tenant": {"id": tenant}},
	}
	data.update(extra)
	return data


@contextmanager
def bot_request(body: dict, token: str | None = None):
	"""Make frappe.local.request look like a Bot Connector POST to the endpoint."""
	headers = {"Authorization": f"Bearer {token}"} if token else {}
	request = EnvironBuilder(
		path=auth.ENDPOINT_PATH, method="POST", data=json.dumps(body), headers=headers, content_type="application/json"
	).get_request()
	old_request = getattr(frappe.local, "request", None)
	frappe.local.request = request
	frappe.local.teams_bot_claims = None
	try:
		yield request
	finally:
		frappe.local.request = old_request
		frappe.local.teams_bot_claims = None
		frappe.set_user("Administrator")
