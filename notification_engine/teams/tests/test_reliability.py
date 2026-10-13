import json
from datetime import datetime, timedelta
from unittest.mock import patch

import frappe
import requests
from frappe.utils import add_days, now_datetime

from notification_engine.teams.cards.builder import make_card, make_envelope
from notification_engine.teams.delivery import queue, ratelimit
from notification_engine.teams.delivery.queue import deliver, enqueue_message, process_due, retry_delay
from notification_engine.teams.tests.utils import TeamsTestCase, make_destination, mock_post, mock_response


def queue_one(destination="Test Chat", **kwargs):
	return enqueue_message(destination, make_envelope(make_card("Hello")), title="Hello", **kwargs)


def get_log(name):
	return frappe.get_doc("Teams Message Log", name)


class FakeClock:
	"""Drives ratelimit.clock and queue.now_datetime together."""

	def __init__(self):
		self.t = 1_900_000_000.0
		self.start = datetime(2030, 1, 1, 9, 0, 0)

	def time(self):
		return self.t

	def now(self):
		return self.start + timedelta(seconds=self.t - 1_900_000_000.0)

	def advance(self, seconds):
		self.t += seconds

	def patches(self):
		return (
			patch.object(ratelimit, "clock", self.time),
			patch.object(queue, "now_datetime", self.now),
		)


class TestTokenBucket(TeamsTestCase):
	def test_burst_then_wait_then_refill(self):
		clock = FakeClock()
		with patch.object(ratelimit, "clock", clock.time):
			for _ in range(4):
				self.assertTrue(ratelimit.take("bucket-a", 0.5, 4)[0])
			allowed, wait = ratelimit.take("bucket-a", 0.5, 4)
			self.assertFalse(allowed)
			self.assertAlmostEqual(wait, 2.0, places=3)

			clock.advance(2)
			self.assertTrue(ratelimit.take("bucket-a", 0.5, 4)[0])
			self.assertFalse(ratelimit.take("bucket-a", 0.5, 4)[0])

			clock.advance(3600)  # refill is capped at burst
			for _ in range(4):
				self.assertTrue(ratelimit.take("bucket-a", 0.5, 4)[0])
			self.assertFalse(ratelimit.take("bucket-a", 0.5, 4)[0])

	def test_destinations_are_independent(self):
		self.assertTrue(ratelimit.take("bucket-b", 0.01, 1)[0])
		self.assertFalse(ratelimit.take("bucket-b", 0.01, 1)[0])
		self.assertTrue(ratelimit.take("bucket-c", 0.01, 1)[0])

	def test_block(self):
		ratelimit.block("bucket-d", 30)
		allowed, wait = ratelimit.take("bucket-d", 100, 100)
		self.assertFalse(allowed)
		self.assertGreater(wait, 25)
		ratelimit.reset("bucket-d")
		self.assertTrue(ratelimit.take("bucket-d", 100, 100)[0])

	def test_limits_fall_back_to_settings(self):
		dest = make_destination(rate_per_second=0, burst=0)
		self.assertEqual(ratelimit.get_limits(dest), (0.07, 4))
		dest = make_destination(rate_per_second=2, burst=7)
		self.assertEqual(ratelimit.get_limits(dest), (2.0, 7))


class TestRetries(TeamsTestCase):
	def setUp(self):
		super().setUp()
		self.dest = make_destination()

	def test_retry_schedule(self):
		self.assertEqual([retry_delay(n) for n in range(1, 7)], [5, 30, 120, 600, 3600, 3600])
		self.assertEqual(retry_delay(1, retry_after=90), 90)
		self.assertEqual(retry_delay(3, retry_after=10), 120)

	def test_500_retries_with_backoff_then_fails(self):
		clock = FakeClock()
		frappe.db.set_single_value("Teams Settings", "max_retries", 2)
		name = queue_one()
		with clock.patches()[0], clock.patches()[1], mock_post(mock_response(500, text="boom")) as post:
			deliver(name)
			log = get_log(name)
			self.assertEqual((log.status, log.attempts, log.http_status), ("Queued", 1, 500))
			self.assertEqual(log.next_attempt_at, clock.now() + timedelta(seconds=5))
			self.assertIn("retrying in 5s", log.error)

			deliver(name)  # not due yet
			self.assertEqual(post.call_count, 1)

			clock.advance(5)
			deliver(name)
			log = get_log(name)
			self.assertEqual((log.status, log.attempts), ("Queued", 2))
			self.assertEqual(log.next_attempt_at, clock.now() + timedelta(seconds=30))

			clock.advance(30)
			deliver(name)
			log = get_log(name)
			self.assertEqual((log.status, log.attempts), ("Failed", 3))
			self.assertIsNone(log.next_attempt_at)
			self.assertEqual(post.call_count, 3)

	def test_429_honours_retry_after_and_blocks_destination(self):
		clock = FakeClock()
		name = queue_one()
		with clock.patches()[0], clock.patches()[1], mock_post(mock_response(429, headers={"Retry-After": "90"})):
			deliver(name)
		log = get_log(name)
		self.assertEqual(log.status, "Throttled")
		self.assertEqual(log.next_attempt_at, clock.now() + timedelta(seconds=90))
		allowed, wait = ratelimit.take(self.dest.name, 100, 100)
		self.assertFalse(allowed)
		self.assertGreater(wait, 80)

	def test_timeout_is_retried(self):
		name = queue_one()
		with mock_post(side_effect=requests.Timeout()):
			deliver(name)
		self.assertEqual(get_log(name).status, "Queued")
		self.assertEqual(get_log(name).attempts, 1)

	def test_4xx_fails_immediately(self):
		name = queue_one()
		with mock_post(mock_response(404, text="Not found")):
			deliver(name)
		log = get_log(name)
		self.assertEqual((log.status, log.attempts), ("Failed", 1))

	def test_success_after_retry(self):
		clock = FakeClock()
		name = queue_one()
		with clock.patches()[0], clock.patches()[1]:
			with mock_post(mock_response(503)):
				deliver(name)
			clock.advance(5)
			with mock_post(mock_response(202)):
				deliver(name)
		log = get_log(name)
		self.assertEqual((log.status, log.attempts, log.http_status), ("Sent", 2, 202))
		self.dest.reload()
		self.assertEqual(self.dest.consecutive_failures, 0)


class TestRateLimitedDelivery(TeamsTestCase):
	def test_throttled_when_no_token_and_fifo(self):
		make_destination(rate_per_second=0.01, burst=1)
		first, second, third = queue_one(), queue_one(), queue_one()
		with mock_post(mock_response(202)) as post:
			deliver(first)
			deliver(second)
			self.assertEqual(post.call_count, 1)
			self.assertEqual(get_log(second).status, "Throttled")
			self.assertIsNotNone(get_log(second).next_attempt_at)

			# A newer message waits behind the older throttled one even if a token were free.
			ratelimit.reset("Test Chat")
			deliver(third)
			self.assertEqual(get_log(third).status, "Throttled")
			self.assertEqual(post.call_count, 1)

	def test_process_due_enqueues_due_and_stuck(self):
		make_destination(rate_per_second=0.01, burst=2)
		due = [queue_one() for _ in range(3)]
		later = queue_one()
		stuck = queue_one()
		past = now_datetime() - timedelta(seconds=1)
		for name in due:
			frappe.db.set_value("Teams Message Log", name, {"status": "Throttled", "next_attempt_at": past})
		frappe.db.set_value(
			"Teams Message Log", later, {"status": "Throttled", "next_attempt_at": now_datetime() + timedelta(hours=1)}
		)
		frappe.db.set_value(
			"Teams Message Log", stuck, "modified", now_datetime() - timedelta(minutes=30), update_modified=False
		)
		self.scheduled.reset_mock()
		process_due()
		scheduled = self.scheduled_logs()
		# Burst 2: only the two oldest due logs are enqueued this tick.
		self.assertEqual(scheduled, due[:2])

		make_destination("Other Chat")
		frappe.db.set_value("Teams Message Log", stuck, "destination", "Other Chat", update_modified=False)
		self.scheduled.reset_mock()
		process_due()
		self.assertIn(stuck, self.scheduled_logs())
		self.assertNotIn(later, self.scheduled_logs())

	def test_200_rapid_events_stay_under_workflow_limit(self):
		"""Spec M3: 200 rapid events to one destination are delivered without a 429 storm.

		Workflows' Flow bot allows about 25 posts per 300 s per connection. With the default
		0.07/s and burst 4, no 300 s window may contain more than 25 posts.
		"""
		make_destination(rate_per_second=0, burst=0)  # use Teams Settings defaults
		clock = FakeClock()
		names = [queue_one() for _ in range(200)]
		sent_at = []

		def post(*args, **kwargs):
			sent_at.append(clock.time())
			return mock_response(202)

		with clock.patches()[0], clock.patches()[1], mock_post(side_effect=post):
			for name in names:  # the 200 initial jobs run at once
				deliver(name)
			for _tick in range(240):  # scheduler: once a minute, for up to 4 hours
				if len(sent_at) == 200:
					break
				clock.advance(60)
				self.scheduled.reset_mock()
				process_due()
				for name in self.scheduled_logs():
					deliver(name, from_sweep=True)

		statuses = frappe.get_all("Teams Message Log", filters={"name": ("in", names)}, pluck="status")
		self.assertEqual(set(statuses), {"Sent"})
		self.assertEqual(len(sent_at), 200)
		worst = max(sum(1 for t in sent_at if start <= t < start + 300) for start in sent_at)
		self.assertLessEqual(worst, 25, f"{worst} posts in one 300 s window")
		# Order is kept: logs are sent oldest first.
		order = frappe.get_all(
			"Teams Message Log", filters={"name": ("in", names)}, order_by="sent_at asc, creation asc", pluck="name"
		)
		self.assertEqual(order, names)


class TestFailureAlerts(TeamsTestCase):
	def test_admins_alerted_once_at_threshold(self):
		make_destination()
		frappe.db.set_single_value("Teams Settings", {"failure_alert_threshold": 3, "max_retries": 0})
		with (
			patch("frappe.desk.doctype.notification_log.notification_log.enqueue_create_notification") as notify,
			patch("frappe.sendmail") as sendmail,
			mock_post(mock_response(400)),
		):
			for _ in range(5):
				deliver(queue_one())
		self.assertEqual(notify.call_count, 1)
		users, doc = notify.call_args.args
		self.assertTrue(users)
		self.assertEqual(doc["document_name"], "Test Chat")
		self.assertIn("3 times", doc["subject"])
		self.assertEqual(sendmail.call_count, 1)


class TestPurge(TeamsTestCase):
	def test_purge_old_logs(self):
		from notification_engine.teams.tasks import purge_old_logs

		make_destination()
		old_sent, old_queued, recent = queue_one(), queue_one(), queue_one()
		frappe.db.set_value("Teams Message Log", old_sent, "status", "Sent")
		for name in (old_sent, old_queued):
			frappe.db.set_value("Teams Message Log", name, "creation", add_days(now_datetime(), -40))
		purge_old_logs()
		self.assertFalse(frappe.db.exists("Teams Message Log", old_sent))
		self.assertTrue(frappe.db.exists("Teams Message Log", old_queued))
		self.assertTrue(frappe.db.exists("Teams Message Log", recent))

	def test_zero_retention_keeps_everything(self):
		from notification_engine.teams.tasks import purge_old_logs

		make_destination()
		name = queue_one()
		frappe.db.set_value("Teams Message Log", name, {"status": "Sent", "creation": add_days(now_datetime(), -400)})
		frappe.db.set_single_value("Teams Settings", "log_retention_days", 0)
		purge_old_logs()
		self.assertTrue(frappe.db.exists("Teams Message Log", name))
