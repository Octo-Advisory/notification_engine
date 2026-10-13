import json

import frappe

from notification_engine.teams.cards.builder import (
	MAX_CARD_BYTES,
	build_card,
	card_size,
	make_card,
	make_envelope,
)
from notification_engine.teams.tests.utils import TeamsTestCase, make_destination, make_rule, make_todo


def rule(**kwargs):
	"""A Notification Rule as a dict, with only the fields the card builder reads."""
	values = {
		"name": "Card Rule",
		"reference_doctype": "ToDo",
		"event": "After Insert",
		"subject": "",
		"message": "",
		"teams_title": "ToDo {{ doc.name }}",
		"teams_include_open_button": 1,
		"teams_fields": [],
	}
	values.update(kwargs)
	return frappe._dict(values)


def facts(card):
	for block in card["body"]:
		if block["type"] == "FactSet":
			return {f["title"]: f["value"] for f in block["facts"]}
	return {}


class TestCards(TeamsTestCase):
	def setUp(self):
		super().setUp()
		self.todo = make_todo(priority="High", status="Open", description="<p>Hello <b>team</b></p>")

	def test_default_layout(self):
		card = build_card(rule(teams_body="Priority is {{ doc.priority }}", teams_title_color="Good"), self.todo)
		self.assertEqual(card["type"], "AdaptiveCard")
		self.assertEqual(card["version"], "1.4")
		title, body = card["body"][0], card["body"][1]
		self.assertEqual(title["text"], f"ToDo {self.todo.name}")
		self.assertEqual(title["weight"], "Bolder")
		self.assertEqual(title["color"], "Good")
		self.assertEqual(body["text"], "Priority is High")

	def test_default_title(self):
		card = build_card(rule(teams_title=""), self.todo)
		self.assertEqual(card["body"][0]["text"], f"ToDo: {self.todo.name}")

	def test_title_and_body_fall_back_to_subject_and_message(self):
		card = build_card(
			rule(teams_title="", subject="Subject {{ doc.priority }}", message="<p>Hello <b>{{ doc.status }}</b></p>"),
			self.todo,
		)
		self.assertEqual(card["body"][0]["text"], "Subject High")
		# HTML (as written for email) becomes Markdown, which Teams cards show.
		self.assertEqual(card["body"][1]["text"], "Hello **Open**")

	def test_teams_title_and_body_win_over_subject_and_message(self):
		card = build_card(rule(subject="Email subject", message="Email body", teams_body="Teams body"), self.todo)
		self.assertEqual([b["text"] for b in card["body"][:2]], [f"ToDo {self.todo.name}", "Teams body"])

	def test_rule_document(self):
		make_destination()
		doc = make_rule(fields=[{"fieldname": "priority"}], title_color="Warning")
		card = build_card(doc, self.todo)
		self.assertEqual(card["body"][0]["color"], "Warning")
		self.assertEqual(facts(card), {"Priority": "High"})

	def test_only_allow_listed_fields(self):
		card = build_card(
			rule(teams_fields=[{"fieldname": "priority"}, {"fieldname": "description", "label": "What"}]), self.todo
		)
		values = facts(card)
		self.assertEqual(values, {"Priority": "High", "What": "Hello team"})
		self.assertNotIn("status", json.dumps(card))

	def test_owner_shows_full_name_and_empty_skipped(self):
		card = build_card(rule(teams_fields=[{"fieldname": "owner"}, {"fieldname": "reference_type"}]), self.todo)
		values = facts(card)
		self.assertEqual(list(values), ["Created By"])
		self.assertEqual(values["Created By"], frappe.utils.get_fullname(self.todo.owner))

	def test_user_link_shows_full_name(self):
		self.todo.allocated_to = "Administrator"
		values = facts(build_card(rule(teams_fields=[{"fieldname": "allocated_to"}]), self.todo))
		self.assertEqual(list(values.values()), [frappe.utils.get_fullname("Administrator")])

	def test_open_button_uses_site_url(self):
		frappe.db.set_single_value("Teams Settings", "site_url", "https://erp.example.com")
		card = build_card(rule(), self.todo)
		self.assertEqual(card["actions"][0]["type"], "Action.OpenUrl")
		self.assertEqual(card["actions"][0]["url"], f"https://erp.example.com/app/todo/{self.todo.name}")

	def test_no_open_button(self):
		self.assertNotIn("actions", build_card(rule(teams_include_open_button=0), self.todo))
		self.assertNotIn("actions", build_card(rule(), self.todo, event="On Trash"))

	def test_title_prefix(self):
		card = build_card(rule(), self.todo, title_prefix="[TEST] ")
		self.assertTrue(card["body"][0]["text"].startswith("[TEST] ToDo"))

	def test_custom_card_template(self):
		template = '{"type": "AdaptiveCard", "version": "1.4", "body": [{"type": "TextBlock", "text": "Custom {{ doc.priority }}"}]}'
		card = build_card(rule(teams_card_template=template), self.todo, title_prefix="[TEST] ")
		self.assertEqual(card["body"][0]["text"], "[TEST] Custom High")

	def test_size_truncation_drops_facts(self):
		many = [{"title": f"Field {i}", "value": "x" * 400} for i in range(200)]
		card = make_card("Big", facts=many)
		self.assertLessEqual(card_size(card), MAX_CARD_BYTES)
		self.assertIn("Open in Frappe for full details.", json.dumps(card))
		factset = next(b for b in card["body"] if b["type"] == "FactSet")
		self.assertLess(len(factset["facts"]), 200)
		self.assertGreater(len(factset["facts"]), 0)

	def test_size_truncation_trims_text(self):
		card = make_card("Big", text="y" * 60000)
		self.assertLessEqual(card_size(card), MAX_CARD_BYTES)

	def test_envelope(self):
		card = make_card("Hi")
		env = make_envelope(card)
		self.assertEqual(env["type"], "message")
		self.assertEqual(env["attachments"][0]["contentType"], "application/vnd.microsoft.card.adaptive")
		self.assertIsNone(env["attachments"][0]["contentUrl"])
		self.assertEqual(env["attachments"][0]["content"], card)
		self.assertNotIn("recipient", env)
		self.assertEqual(make_envelope(card, "a@example.com")["recipient"], "a@example.com")

	def test_template_cannot_reach_dunder(self):
		with self.assertRaises(frappe.ValidationError):
			build_card(rule(teams_title="{{ doc.__class__ }}"), self.todo)
