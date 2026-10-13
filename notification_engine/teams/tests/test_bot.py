import io
import json
import time
import zipfile
from unittest.mock import patch

import frappe
from PIL import Image

from notification_engine.teams.bot import auth, endpoint, handlers
from notification_engine.teams.cards.builder import make_card, make_envelope
from notification_engine.teams.delivery import ratelimit
from notification_engine.teams.delivery.queue import deliver, enqueue_message
from notification_engine.teams.install import BOT_USER
from notification_engine.teams.tests.bot_utils import (
	APP_ID,
	OTHER_TENANT,
	SERVICE_URL,
	TENANT_ID,
	activity,
	bot_request,
	clear_bot_cache,
	enable_bot,
	fake_connector,
	fake_microsoft,
	fake_token,
	http_response,
	jwks,
	make_token,
)
from notification_engine.teams.tests.utils import TeamsTestCase, make_destination, make_user


class BotTestCase(TeamsTestCase):
	def setUp(self):
		super().setUp()
		for dt in ("Teams User Map",):
			frappe.db.delete(dt)
		frappe.db.delete("Teams Destination", {"destination_type": ("like", "Bot%")})
		enable_bot()
		clear_bot_cache()

	def tearDown(self):
		clear_bot_cache()
		super().tearDown()


class TestIncomingAuth(BotTestCase):
	def validate(self, token, body=None):
		return auth.validate_request(f"Bearer {token}", body or {"serviceUrl": SERVICE_URL})

	def assertRejected(self, token, body=None, **fake):
		with fake_microsoft(**fake):
			self.assertRaises(auth.BotAuthError, self.validate, token, body)

	def test_valid_token(self):
		with fake_microsoft():
			claims = self.validate(make_token())
		self.assertEqual(claims["aud"], APP_ID)

	def test_bad_audience(self):
		self.assertRejected(make_token(aud="someone-else"))

	def test_bad_issuer(self):
		self.assertRejected(make_token(iss="https://evil.example.com"))

	def test_expired(self):
		self.assertRejected(make_token(exp=int(time.time()) - 3600))

	def test_clock_skew_allowed(self):
		with fake_microsoft():
			self.validate(make_token(exp=int(time.time()) - 120))

	def test_service_url_must_match(self):
		self.assertRejected(make_token(), {"serviceUrl": "https://attacker.example.com/"})

	def test_endorsement_required(self):
		self.assertRejected(make_token(), keys=jwks(endorsements=("skype",)))

	def test_unknown_key(self):
		with fake_microsoft() as get_json:
			self.assertRaises(auth.BotAuthError, self.validate, make_token(kid="other-key"))
		# The JWKS was refetched once before giving up.
		self.assertEqual(sum(1 for c in get_json.call_args_list if c.args[0].endswith("/keys")), 2)

	def test_unsigned_or_wrong_alg(self):
		token = make_token()
		header, payload, _sig = token.split(".")
		self.assertRejected(f"{header}.{payload}.")
		import jwt as pyjwt

		hs = pyjwt.encode({"iss": auth.BOTFRAMEWORK_ISSUER, "aud": APP_ID, "exp": int(time.time()) + 60}, "secret", algorithm="HS256", headers={"kid": "test-key-1"})
		self.assertRejected(hs)

	def test_entra_issuer_bound_to_tenant(self):
		entra = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
		with fake_microsoft():
			self.validate(make_token(iss=entra, tid=TENANT_ID, serviceurl=None))
		self.assertRejected(make_token(iss=entra, tid=OTHER_TENANT, serviceurl=None))
		self.assertRejected(make_token(iss=f"https://login.microsoftonline.com/{OTHER_TENANT}/v2.0", tid=OTHER_TENANT))

	def test_bot_not_configured(self):
		frappe.db.set_single_value("Teams Settings", "bot_app_id", "")
		self.assertRejected(make_token())


class TestOutgoingToken(BotTestCase):
	def test_token_request_and_cache(self):
		with fake_token("tok-1") as post:
			self.assertEqual(auth.get_access_token(), "tok-1")
			self.assertEqual(auth.get_access_token(), "tok-1")
		self.assertEqual(post.call_count, 1)
		url = post.call_args.args[0]
		data = post.call_args.kwargs["data"]
		self.assertEqual(url, f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token")
		self.assertEqual(data["grant_type"], "client_credentials")
		self.assertEqual(data["client_id"], APP_ID)
		self.assertEqual(data["client_secret"], "test-client-secret")
		self.assertEqual(data["scope"], "https://api.botframework.com/.default")

	def test_token_failure_hides_secret(self):
		failure = http_response(401, {"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret provided.\nTrace ID: x"})
		with patch.object(auth.requests, "post", return_value=failure):
			with self.assertRaises(auth.BotAuthError) as ctx:
				auth.get_access_token()
		self.assertIn("AADSTS7000215", str(ctx.exception))
		self.assertNotIn("test-client-secret", str(ctx.exception))
		self.assertNotIn("Trace ID", str(ctx.exception))


class TestEndpoint(BotTestCase):
	def call(self, body, token=None, valid=True):
		with bot_request(body, token if token is not None else make_token()):
			with fake_microsoft():
				if valid:
					auth.auth_hook()
				response = endpoint.receive()
			user_during = frappe.session.user
		return response, user_during

	def test_auth_hook_sets_bot_user(self):
		with bot_request(activity(), make_token()), fake_microsoft():
			auth.auth_hook()
			self.assertEqual(frappe.session.user, BOT_USER)
			self.assertTrue(frappe.local.teams_bot_claims)
		self.assertEqual(frappe.session.user, "Administrator")

	def test_auth_hook_rejects_bad_token(self):
		with bot_request(activity(), make_token(aud="nope")), fake_microsoft():
			self.assertRaises(frappe.AuthenticationError, auth.auth_hook)

	def test_auth_hook_ignores_other_paths(self):
		with bot_request(activity(), make_token(aud="nope")) as request:
			request.environ["PATH_INFO"] = "/api/method/frappe.ping"
			frappe.local.request = type(request)(request.environ)
			auth.auth_hook()  # not our endpoint: no-op

	def test_disabled_bot_returns_403(self):
		frappe.db.set_single_value("Teams Settings", "bot_enabled", 0)
		response, _u = self.call(activity())
		self.assertEqual(response.status_code, 403)

	def test_missing_token_returns_401(self):
		response, _u = self.call(activity(), token="", valid=False)
		self.assertEqual(response.status_code, 401)

	def test_other_tenant_ignored(self):
		body = activity("installationUpdate", "groupChat", tenant=OTHER_TENANT, action="add")
		response, _u = self.call(body)
		self.assertEqual(response.status_code, 200)
		self.assertFalse(frappe.db.exists("Teams Destination", {"destination_type": "Bot Conversation"}))

	def test_bot_added_to_group_chat_creates_disabled_destination(self):
		body = activity("installationUpdate", "groupChat", action="add")
		response, _u = self.call(body)
		self.assertEqual(response.status_code, 200)
		dest = frappe.get_doc("Teams Destination", {"conversation_id": "19:group@thread.v2"})
		self.assertEqual(dest.destination_type, "Bot Conversation")
		self.assertEqual(dest.enabled, 0)
		self.assertEqual(dest.conversation_type, "groupChat")
		self.assertEqual(dest.service_url, SERVICE_URL)
		self.assertEqual(dest.destination_name, "OCTO Team (bot)")

		# Adding again (conversationUpdate) updates instead of duplicating.
		again = activity("conversationUpdate", "groupChat", membersAdded=[{"id": f"28:{APP_ID}"}])
		self.call(again)
		self.assertEqual(frappe.db.count("Teams Destination", {"conversation_id": "19:group@thread.v2"}), 1)

		removed = activity("installationUpdate", "groupChat", action="remove")
		self.call(removed)
		self.assertEqual(frappe.db.get_value("Teams Destination", dest.name, "enabled"), 0)

	def test_channel_install(self):
		body = activity(
			"conversationUpdate",
			"channel",
			membersAdded=[{"id": f"28:{APP_ID}"}],
			channelData={"tenant": {"id": TENANT_ID}, "team": {"id": "19:team@thread", "name": "Purchase"},
				"channel": {"id": "19:general@thread", "name": "General"}},
		)
		body["conversation"]["name"] = None
		self.call(body)
		dest = frappe.get_doc("Teams Destination", {"conversation_id": body["conversation"]["id"]})
		self.assertEqual(dest.conversation_type, "channel")
		self.assertEqual(dest.team_id, "19:team@thread")
		self.assertEqual(dest.destination_name, "Purchase / General (bot)")

	def test_personal_install_creates_user_map_and_links_user(self):
		alice = make_user("raj.patel@example.com").name
		with patch("frappe.enqueue") as enqueue:
			self.call(activity("installationUpdate", "personal", action="add"))
		user_map = frappe.get_doc("Teams User Map", {"aad_object_id": "aad-user-1"})
		self.assertEqual((user_map.teams_user_id, user_map.installed), ("29:user-1", 1))
		self.assertEqual(user_map.conversation_id, "a:personal-conv")
		jobs = [c.args[0] for c in enqueue.call_args_list]
		self.assertIn("notification_engine.teams.bot.handlers.link_user", jobs)

		member = http_response(200, {"id": "29:user-1", "email": "Raj.Patel@example.com", "userPrincipalName": "raj.patel@example.com"})
		with fake_token(), fake_connector(member) as request:
			handlers.link_user(user_map.name)
		self.assertTrue(request.call_args.args[1].endswith("/v3/conversations/a%3Apersonal-conv/members/29%3Auser-1"))
		user_map.reload()
		self.assertEqual(user_map.user, alice)
		self.assertEqual(user_map.teams_email, "Raj.Patel@example.com")

		with patch("frappe.enqueue"):
			self.call(activity("installationUpdate", "personal", action="remove"))
		self.assertEqual(frappe.db.get_value("Teams User Map", user_map.name, "installed"), 0)

	def test_message_gets_help_reply(self):
		with patch("frappe.enqueue") as enqueue:
			self.call(activity("message", "personal", text="hi"))
		jobs = {c.args[0]: c.kwargs for c in enqueue.call_args_list}
		self.assertIn("notification_engine.teams.bot.handlers.send_help_reply", jobs)
		with fake_token(), fake_connector(http_response(200, {"id": "reply-1"})) as request:
			handlers.send_help_reply(SERVICE_URL, "a:personal-conv", "activity-1")
		body = request.call_args.kwargs["json"]
		self.assertIn("ERP Test Bot", body["text"])

	def test_invoke_returns_json(self):
		body = activity("invoke", "personal", name="adaptiveCard/action", value={"action": {"type": "Action.Execute", "verb": "x"}})
		response, _u = self.call(body)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(json.loads(response.get_data())["statusCode"], 200)


class TestBotSender(BotTestCase):
	def setUp(self):
		super().setUp()
		self.group = frappe.get_doc(
			{
				"doctype": "Teams Destination",
				"destination_name": "OCTO Team (bot)",
				"destination_type": "Bot Conversation",
				"enabled": 1,
				"conversation_type": "groupChat",
				"conversation_id": "19:group@thread.v2",
				"service_url": SERVICE_URL,
			}
		).insert()
		from notification_engine.teams.doctype.teams_settings.teams_settings import ensure_personal_bot_destination

		ensure_personal_bot_destination()
		self.personal = frappe.db.get_value("Teams Destination", {"destination_type": "Bot (Personal Chat)"})
		# A desk role: Notification Engine only notifies System Users.
		self.alice = make_user("tn-alice@example.com", roles=("Teams Admin",)).name

	def queue(self, destination, **kwargs):
		return enqueue_message(destination, make_envelope(make_card("Hello bot")), title="Hello bot", **kwargs)

	def log(self, name):
		return frappe.get_doc("Teams Message Log", name)

	def map_alice(self, conversation_id=None, installed=1):
		return frappe.get_doc(
			{
				"doctype": "Teams User Map",
				"user": self.alice,
				"teams_email": self.alice,
				"aad_object_id": "aad-alice",
				"teams_user_id": "29:alice",
				"service_url": SERVICE_URL,
				"conversation_id": conversation_id,
				"installed": installed,
			}
		).insert()

	def test_group_chat_send(self):
		name = self.queue(self.group.name)
		with fake_token(), fake_connector(http_response(201, {"id": "1700000000001"})) as request:
			deliver(name)
		method, url = request.call_args.args
		self.assertEqual(method, "POST")
		self.assertEqual(url, "https://smba.trafficmanager.net/amer/v3/conversations/19%3Agroup%40thread.v2/activities")
		self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer access-token-1")
		body = request.call_args.kwargs["json"]
		self.assertEqual(body["type"], "message")
		self.assertEqual(body["attachments"][0]["content"]["body"][0]["text"], "Hello bot")
		log = self.log(name)
		self.assertEqual((log.status, log.activity_id, log.conversation_id), ("Sent", "1700000000001", "19:group@thread.v2"))

	def test_personal_existing_conversation(self):
		self.map_alice(conversation_id="a:alice-chat")
		name = self.queue(self.personal, recipient_user=self.alice, recipient_email=self.alice)
		with fake_token(), fake_connector(http_response(201, {"id": "act-9"})) as request:
			deliver(name)
		self.assertIn("/v3/conversations/a%3Aalice-chat/activities", request.call_args.args[1])
		self.assertEqual(self.log(name).status, "Sent")

	def test_personal_creates_conversation(self):
		user_map = self.map_alice()
		name = self.queue(self.personal, recipient_user=self.alice)
		with fake_token(), fake_connector(
			http_response(201, {"id": "a:new-chat"}), http_response(201, {"id": "act-1"})
		) as request:
			deliver(name)
		create = request.call_args_list[0]
		self.assertEqual(create.args[1], "https://smba.trafficmanager.net/amer/v3/conversations")
		self.assertEqual(
			create.kwargs["json"],
			{"bot": {"id": f"28:{APP_ID}"}, "members": [{"id": "29:alice"}], "channelData": {"tenant": {"id": TENANT_ID}}},
		)
		self.assertEqual(frappe.db.get_value("Teams User Map", user_map.name, "conversation_id"), "a:new-chat")
		self.assertEqual(self.log(name).conversation_id, "a:new-chat")

	def test_personal_not_installed(self):
		name = self.queue(self.personal, recipient_user=self.alice)
		with fake_token(), fake_connector() as request:
			deliver(name)
		request.assert_not_called()
		log = self.log(name)
		self.assertEqual(log.status, "Failed")
		self.assertIn("Teams app not installed", log.error)

	def test_personal_blocked_marks_uninstalled(self):
		user_map = self.map_alice(conversation_id="a:alice-chat")
		name = self.queue(self.personal, recipient_user=self.alice)
		blocked = http_response(403, {"error": {"code": "ConversationBlockedByUser", "message": "User blocked the conversation with the bot."}})
		with fake_token(), fake_connector(blocked):
			deliver(name)
		self.assertEqual(self.log(name).status, "Failed")
		self.assertEqual(frappe.db.get_value("Teams User Map", user_map.name, "installed"), 0)

	def test_429_retried(self):
		name = self.queue(self.group.name)
		with fake_token(), fake_connector(http_response(429, {}, headers={"Retry-After": "3"})):
			deliver(name)
		log = self.log(name)
		self.assertEqual((log.status, log.http_status), ("Throttled", 429))

	def test_401_refreshes_token_once(self):
		name = self.queue(self.group.name)
		with patch.object(auth.requests, "post", side_effect=[
			http_response(200, {"access_token": "old", "expires_in": 3600}),
			http_response(200, {"access_token": "new", "expires_in": 3600}),
		]), fake_connector(http_response(401, {}), http_response(201, {"id": "act-2"})) as request:
			deliver(name)
		tokens = [c.kwargs["headers"]["Authorization"] for c in request.call_args_list]
		self.assertEqual(tokens, ["Bearer old", "Bearer new"])
		self.assertEqual(self.log(name).status, "Sent")

	def test_bad_credentials_not_retried(self):
		name = self.queue(self.group.name)
		with patch.object(auth.requests, "post", return_value=http_response(401, {"error": "invalid_client"})):
			deliver(name)
		self.assertEqual(self.log(name).status, "Failed")
		self.assertEqual(self.log(name).attempts, 1)

	def test_bot_disabled_skips(self):
		frappe.db.set_single_value("Teams Settings", "bot_enabled", 0)
		name = self.queue(self.group.name)
		deliver(name)
		self.assertEqual(self.log(name).status, "Skipped")

	def test_rate_defaults_per_type(self):
		self.assertEqual(ratelimit.get_limits(self.group), (0.5, 5))
		self.assertEqual(ratelimit.get_limits(frappe.get_doc("Teams Destination", self.personal)), (10.0, 20))

	def test_rule_personal_via_bot(self):
		from notification_engine.teams.tests.utils import make_rule, make_todo

		self.map_alice(conversation_id="a:alice-chat")
		make_rule(
			event="New",
			destinations=(self.group.name,),
			recipients=[{"user": self.alice, "is_enabled": 1}],
			personal_webhook=self.personal,
		)
		todo = make_todo()
		logs = frappe.get_all("Teams Message Log", {"reference_name": todo.name}, ["destination", "recipient_user"])
		self.assertEqual(sorted(l.destination for l in logs), sorted([self.group.name, self.personal]))


class TestSettingsAndManifest(BotTestCase):
	def test_guid_validation_and_personal_destination(self):
		settings = frappe.get_doc("Teams Settings")
		settings.bot_app_id = "not-a-guid"
		self.assertRaises(frappe.ValidationError, settings.save)
		settings.reload()
		settings.bot_enabled = 1
		settings.save()
		self.assertTrue(settings.messaging_endpoint.endswith("/api/method/notification_engine.teams.bot.endpoint.receive"))
		self.assertTrue(frappe.db.exists("Teams Destination", {"destination_type": "Bot (Personal Chat)"}))

	def test_only_one_personal_bot_destination(self):
		from notification_engine.teams.doctype.teams_settings.teams_settings import ensure_personal_bot_destination

		ensure_personal_bot_destination()
		self.assertRaises(
			frappe.ValidationError,
			frappe.get_doc({"doctype": "Teams Destination", "destination_name": "Another", "destination_type": "Bot (Personal Chat)"}).insert,
		)

	def test_manifest_package(self):
		from notification_engine.teams.teams_manifest.builder import build_package

		frappe.db.set_single_value("Teams Settings", "site_url", "https://erp.example.com")
		with zipfile.ZipFile(io.BytesIO(build_package())) as zf:
			self.assertEqual(sorted(zf.namelist()), ["color.png", "manifest.json", "outline.png"])
			manifest = json.loads(zf.read("manifest.json"))
			self.assertEqual(Image.open(io.BytesIO(zf.read("color.png"))).size, (192, 192))
			self.assertEqual(Image.open(io.BytesIO(zf.read("outline.png"))).size, (32, 32))
		self.assertEqual(manifest["manifestVersion"], "1.30")
		# Required from manifest v1.25 when the bot has the team scope.
		self.assertEqual(manifest["supportsChannelFeatures"], "tier1")
		self.assertEqual(manifest["id"], APP_ID)
		self.assertEqual(manifest["bots"][0]["botId"], APP_ID)
		self.assertEqual(manifest["bots"][0]["scopes"], ["personal", "team", "groupChat"])
		self.assertFalse(manifest["bots"][0]["isNotificationOnly"])
		self.assertEqual(manifest["validDomains"], ["erp.example.com"])
		self.assertEqual(manifest["webApplicationInfo"]["id"], APP_ID)
		self.assertEqual(manifest["name"]["short"], "ERP Test Bot")
