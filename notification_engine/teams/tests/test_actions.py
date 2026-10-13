import json
from unittest.mock import patch

import frappe

from notification_engine.teams.bot import actions, auth, endpoint
from notification_engine.teams.cards.buttons import VERB
from notification_engine.teams.install import BOT_USER
from notification_engine.teams.tests.bot_utils import (
	APP_ID,
	SERVICE_URL,
	activity,
	bot_request,
	enable_bot,
	fake_connector,
	fake_microsoft,
	fake_token,
	http_response,
	make_token,
)
from notification_engine.teams.tests.bot_utils import clear_bot_cache
from notification_engine.teams.tests.utils import TeamsTestCase, make_destination, make_rule, make_todo, make_user

WORKFLOW = "Teams Test ToDo Workflow"


def ensure_master(doctype, name, field):
	if not frappe.db.exists(doctype, name):
		frappe.get_doc({"doctype": doctype, field: name}).insert(ignore_permissions=True)


def make_todo_workflow():
	"""A workflow on ToDo's existing status field: no schema change, so no implicit commit."""
	for state in ("Open", "Closed", "Cancelled"):
		ensure_master("Workflow State", state, "workflow_state_name")
	for action in ("Close", "Cancel It"):
		ensure_master("Workflow Action Master", action, "workflow_action_name")
	frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": WORKFLOW,
			"document_type": "ToDo",
			"is_active": 1,
			"workflow_state_field": "status",
			"send_email_alert": 0,
			"override_status": 1,
			"states": [
				{"state": "Open", "doc_status": "0", "allow_edit": "All"},
				{"state": "Closed", "doc_status": "0", "allow_edit": "All"},
				{"state": "Cancelled", "doc_status": "0", "allow_edit": "All"},
			],
			"transitions": [
				{"state": "Open", "action": "Close", "next_state": "Closed", "allowed": "System Manager", "allow_self_approval": 1},
				{"state": "Open", "action": "Cancel It", "next_state": "Cancelled", "allowed": "System Manager", "allow_self_approval": 1},
			],
		}
	).insert(ignore_permissions=True)


def clear_workflow_cache():
	frappe.cache.hdel("workflow", "ToDo")
	frappe.clear_document_cache("Workflow", WORKFLOW)
	frappe.clear_cache(doctype="ToDo")


def payload(log_name):
	return json.loads(frappe.db.get_value("Teams Message Log", log_name, "payload"))


def card_of(log_name):
	return payload(log_name)["attachments"][0]["content"]


def execute_actions(card):
	found = []
	for action in card.get("actions") or []:
		if action["type"] == "Action.Execute":
			found.append(action)
		elif action["type"] == "Action.ShowCard":
			found.extend(a for a in action["card"]["actions"] if a["type"] == "Action.Execute")
	return found


class TestButtons(TeamsTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Workflow", {"document_type": "ToDo"})
		frappe.db.delete("Teams User Map")
		frappe.db.delete("Teams Destination", {"destination_type": ("like", "Bot%")})
		clear_workflow_cache()
		make_todo_workflow()
		clear_workflow_cache()
		enable_bot()
		clear_bot_cache()
		make_destination("Webhook Chat")
		self.group = frappe.get_doc(
			{
				"doctype": "Teams Destination",
				"destination_name": "Approvers (bot)",
				"destination_type": "Bot Conversation",
				"enabled": 1,
				"conversation_type": "groupChat",
				"conversation_id": "19:approvers@thread.v2",
				"service_url": SERVICE_URL,
			}
		).insert()
		self.boss = make_user("tn-boss@example.com", roles=("System Manager",)).name
		self.alice = make_user("tn-alice@example.com").name
		self.map_user(self.boss, "aad-boss", "29:boss")
		self.map_user(self.alice, "aad-alice", "29:alice")

	def tearDown(self):
		clear_workflow_cache()
		clear_bot_cache()
		super().tearDown()

	def map_user(self, user, aad, teams_id):
		frappe.get_doc(
			{"doctype": "Teams User Map", "user": user, "aad_object_id": aad, "teams_user_id": teams_id, "installed": 1}
		).insert()

	def rule(self, **kwargs):
		values = {
			"event": "New",
			"destinations": ("Webhook Chat", "Approvers (bot)"),
			"all_workflow_actions": 1,
			"buttons": [{"button_type": "Workflow Action", "workflow_action": "Close", "style": "positive", "label": "Close it"}],
			"fields": [{"fieldname": "priority"}],
		}
		values.update(kwargs)
		return make_rule(**values)

	def logs(self, todo):
		rows = frappe.get_all("Teams Message Log", {"reference_name": todo.name}, ["name", "destination"])
		return {r.destination: r.name for r in rows}

	def click(self, data, aad="aad-boss", teams_id="29:boss", reply_to="act-bot-1"):
		body = activity(
			"invoke",
			"groupChat",
			name="adaptiveCard/action",
			replyToId=reply_to,
			value={"action": {"type": "Action.Execute", "verb": VERB, "data": data}, "trigger": "manual"},
		)
		body["from"] = {"id": teams_id, "aadObjectId": aad, "name": "Clicker"}
		with bot_request(body, make_token()), fake_microsoft(), patch("frappe.enqueue") as enqueue:
			auth.auth_hook()
			response = endpoint.receive()
			user_after = frappe.session.user
		self.assertEqual(user_after, BOT_USER, "the clicking user must be restored")
		self.assertEqual(response.status_code, 200)
		self.last_enqueue = enqueue
		return json.loads(response.get_data())

	def button_data(self, log_name, title):
		for action in execute_actions(card_of(log_name)):
			if action["title"] in (title, f"Submit: {title}"):
				return dict(action["data"])
		raise AssertionError(f"no button {title}")

	# ------------------------------------------------------------ building

	def test_bot_card_gets_buttons_webhook_card_does_not(self):
		self.rule()
		todo = make_todo()
		logs = self.logs(todo)
		bot_card, webhook_card = card_of(logs["Approvers (bot)"]), card_of(logs["Webhook Chat"])

		titles = [a["title"] for a in execute_actions(bot_card)]
		self.assertEqual(titles, ["Close it", "Cancel It"])
		self.assertEqual(bot_card["version"], "1.5")
		self.assertEqual(execute_actions(bot_card)[0]["style"], "positive")
		self.assertEqual(bot_card["actions"][-1]["type"], "Action.OpenUrl")
		data = execute_actions(bot_card)[0]["data"]
		self.assertEqual((data["doctype"], data["name"], data["key"]), ("ToDo", todo.name, "wf:Close"))

		self.assertEqual(execute_actions(webhook_card), [])
		self.assertEqual(webhook_card["version"], "1.4")

	def test_listed_actions_only(self):
		self.rule(all_workflow_actions=0)
		todo = make_todo()
		titles = [a["title"] for a in execute_actions(card_of(self.logs(todo)["Approvers (bot)"]))]
		self.assertEqual(titles, ["Close it"])

	def test_comment_button_uses_show_card(self):
		self.rule(buttons=[{"button_type": "Workflow Action", "workflow_action": "Cancel It", "ask_comment": 1, "comment_required": 1}])
		todo = make_todo()
		card = card_of(self.logs(todo)["Approvers (bot)"])
		show = next(a for a in card["actions"] if a["type"] == "Action.ShowCard")
		self.assertEqual(show["title"], "Cancel It")
		text_input = show["card"]["body"][0]
		self.assertEqual((text_input["type"], text_input["id"], text_input["isRequired"]), ("Input.Text", "comment", True))

	def test_validation(self):
		self.assertRaises(
			frappe.ValidationError,
			self.rule,
			buttons=[{"button_type": "Workflow Action", "workflow_action": "Explode"}],
		)
		self.assertRaises(
			frappe.ValidationError,
			self.rule,
			buttons=[{"button_type": "Set Value", "fieldname": "no_such_field", "label": "x"}],
		)
		frappe.db.delete("Workflow", {"document_type": "ToDo"})
		clear_workflow_cache()
		self.assertRaises(frappe.ValidationError, self.rule)

	# ------------------------------------------------------------ clicking

	def test_approve_flow(self):
		self.rule()
		todo = make_todo()
		logs = self.logs(todo)
		frappe.db.set_value("Teams Message Log", logs["Approvers (bot)"], {"status": "Sent", "activity_id": "act-bot-1", "conversation_id": "19:approvers@thread.v2"})
		# A second bot copy, e.g. in a personal chat, that should be updated too.
		other = frappe.get_doc("Teams Message Log", logs["Approvers (bot)"]).as_dict()
		copy = frappe.get_doc({**other, "name": None, "dedupe_key": None, "activity_id": "act-bot-2"}).insert(ignore_permissions=True)

		response = self.click(self.button_data(logs["Approvers (bot)"], "Close it"))

		self.assertEqual(response["type"], "application/vnd.microsoft.card.adaptive")
		card = response["value"]
		self.assertEqual(execute_actions(card), [])
		self.assertIn("Close by", card["body"][-1]["text"])
		self.assertEqual(frappe.db.get_value("ToDo", todo.name, "status"), "Closed")
		comments = frappe.get_all("Comment", {"reference_name": todo.name, "comment_type": "Comment"}, ["content", "comment_email"])
		self.assertTrue(any("Close from Microsoft Teams by" in c.content and c.comment_email == self.boss for c in comments))

		jobs = {c.args[0]: c.kwargs for c in self.last_enqueue.call_args_list}
		self.assertEqual(jobs["notification_engine.teams.bot.actions.update_card_copies"]["log_names"], [copy.name])

		with fake_token(), fake_connector(http_response(200, {"id": "act-bot-2"})) as request:
			actions.update_card_copies([copy.name], card)
		method, url = request.call_args.args
		self.assertEqual(method, "PUT")
		self.assertTrue(url.endswith("/v3/conversations/19%3Aapprovers%40thread.v2/activities/act-bot-2"))
		self.assertEqual(request.call_args.kwargs["json"]["attachments"][0]["content"], card)

	def test_already_done(self):
		self.rule()
		todo = make_todo()
		data = self.button_data(self.logs(todo)["Approvers (bot)"], "Close it")
		self.click(data)
		response = self.click(data)
		self.assertEqual(response["type"], "application/vnd.microsoft.card.adaptive")
		self.assertIn("Already Closed", response["value"]["body"][-1]["text"])

	def test_not_permitted(self):
		self.rule()
		todo = make_todo(allocated_to=self.alice)  # Alice can read it but has no System Manager role
		data = self.button_data(self.logs(todo)["Approvers (bot)"], "Close it")
		response = self.click(data, aad="aad-alice", teams_id="29:alice")
		self.assertEqual(response["type"], "application/vnd.microsoft.activity.message")
		self.assertIn("not allowed", response["value"])
		self.assertEqual(frappe.db.get_value("ToDo", todo.name, "status"), "Open")

	def test_no_read_permission(self):
		self.rule()
		todo = make_todo()  # not shared with Alice
		data = self.button_data(self.logs(todo)["Approvers (bot)"], "Close it")
		response = self.click(data, aad="aad-alice", teams_id="29:alice")
		self.assertIn("permission", response["value"])

	def test_unknown_teams_user(self):
		self.rule()
		todo = make_todo()
		data = self.button_data(self.logs(todo)["Approvers (bot)"], "Close it")
		response = self.click(data, aad="aad-stranger", teams_id="29:stranger")
		self.assertIn("isn't linked to ERP", response["value"])
		self.assertEqual(frappe.db.get_value("ToDo", todo.name, "status"), "Open")

	def test_required_comment(self):
		self.rule(buttons=[{"button_type": "Workflow Action", "workflow_action": "Cancel It", "ask_comment": 1, "comment_required": 1}])
		todo = make_todo()
		data = self.button_data(self.logs(todo)["Approvers (bot)"], "Cancel It")
		self.assertIn("enter a comment", self.click(data)["value"])
		self.assertEqual(frappe.db.get_value("ToDo", todo.name, "status"), "Open")

		response = self.click({**data, "comment": "Duplicate request"})
		self.assertIn("Comment: Duplicate request", response["value"]["body"][-1]["text"])
		self.assertEqual(frappe.db.get_value("ToDo", todo.name, "status"), "Cancelled")
		comments = frappe.get_all("Comment", {"reference_name": todo.name, "comment_type": "Comment"}, pluck="content")
		self.assertTrue(any("Duplicate request" in c for c in comments))

	def test_set_value_button(self):
		self.rule(
			all_workflow_actions=0,
			buttons=[{"button_type": "Set Value", "fieldname": "priority", "value": "High", "label": "Make urgent", "style": "destructive"}],
		)
		todo = make_todo(priority="Low")
		data = self.button_data(self.logs(todo)["Approvers (bot)"], "Make urgent")
		self.assertTrue(data["key"].startswith("set:"))
		response = self.click(data)
		self.assertEqual(frappe.db.get_value("ToDo", todo.name, "priority"), "High")
		self.assertIn("Make urgent by", response["value"]["body"][-1]["text"])

	def test_tampered_key_does_nothing(self):
		self.rule()
		todo = make_todo()
		data = self.button_data(self.logs(todo)["Approvers (bot)"], "Close it")
		response = self.click({**data, "key": "set:not-a-row"})
		self.assertEqual(frappe.db.get_value("ToDo", todo.name, "status"), "Open")
		self.assertEqual(response["type"], "application/vnd.microsoft.card.adaptive")

	def test_double_click_lock(self):
		self.rule()
		todo = make_todo()
		data = self.button_data(self.logs(todo)["Approvers (bot)"], "Close it")
		lock = f"teams_notify:action_lock:{frappe.local.site}:ToDo:{todo.name}"
		frappe.cache.set(lock, "someone", ex=30)
		try:
			self.assertIn("already acting", self.click(data)["value"])
		finally:
			frappe.cache.delete(lock)
		self.assertEqual(frappe.db.get_value("ToDo", todo.name, "status"), "Open")
		self.click(data)
		self.assertIsNone(frappe.cache.get(lock), "lock is released after the action")

	def test_test_card_changes_nothing(self):
		self.rule()
		todo = make_todo()
		from notification_engine.teams import api

		result = api.send_test_for_rule("Test ToDo Rule", todo.name)
		bot_log = next(l for l in result["logs"] if frappe.db.get_value("Teams Message Log", l, "destination") == "Approvers (bot)")
		data = self.button_data(bot_log, "Close it")
		self.assertEqual(data.get("test"), 1)
		self.assertIn("test card", self.click(data)["value"])
		self.assertEqual(frappe.db.get_value("ToDo", todo.name, "status"), "Open")
