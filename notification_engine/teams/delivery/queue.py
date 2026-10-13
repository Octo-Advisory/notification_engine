"""Queue Teams messages and deliver them from background workers.

Delivery never sleeps in a worker. A message that has to wait (rate limit, 429, retry backoff)
is saved with `next_attempt_at`, and `process_due` (cron, every minute) enqueues it again.
"""

import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime
from frappe.utils.background_jobs import get_queues_timeout

from notification_engine.teams.delivery import ratelimit
from notification_engine.teams.delivery.base import OutboundMessage, SendResult, get_sender

DELIVER_METHOD = "notification_engine.teams.delivery.queue.deliver"
# Seconds to wait before retry 1, 2, 3, ... (the last value repeats).
BACKOFF_SECONDS = (5, 30, 120, 600, 3600)
WAITING = ("Queued", "Throttled")
# A Queued log with no pending retry that is older than this has lost its job (e.g. worker restart).
STUCK_AFTER_MINUTES = 10
SWEEP_LIMIT = 1000


def get_queue_name() -> str:
	"""Configured queue if a worker is configured for it (common_site_config `workers`), else default."""
	queue = (frappe.db.get_single_value("Teams Settings", "queue_name") or "teams").strip()
	return queue if queue in get_queues_timeout() else "default"


def enqueue_message(
	destination: str,
	payload: dict,
	*,
	title: str | None = None,
	rule: str | None = None,
	event: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	recipient_user: str | None = None,
	recipient_email: str | None = None,
	dedupe_key: str | None = None,
	is_test: bool = False,
) -> str | None:
	"""Create a Queued log and enqueue delivery after the current transaction commits.

	Returns the log name, or None when a message with the same dedupe key already exists.
	"""
	if dedupe_key and frappe.db.exists("Teams Message Log", {"dedupe_key": dedupe_key}):
		return None

	log = frappe.get_doc(
		{
			"doctype": "Teams Message Log",
			"status": "Queued",
			"title": (title or "")[:255],
			"rule": rule,
			"event": event,
			"is_test": int(is_test),
			"destination": destination,
			"recipient_user": recipient_user,
			"recipient_email": recipient_email,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"payload": json.dumps(payload, ensure_ascii=False, indent=1),
			"dedupe_key": dedupe_key,
		}
	)
	try:
		log.insert(ignore_permissions=True, ignore_links=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		# Lost a race with another worker for the same dedupe key. Drop Frappe's popup message.
		frappe.clear_last_message()
		return None

	schedule_delivery(log.name)
	return log.name


def schedule_delivery(log_name: str, after_commit: bool = True, from_sweep: bool = False):
	attempts = frappe.db.get_value("Teams Message Log", log_name, "attempts") or 0
	frappe.enqueue(
		DELIVER_METHOD,
		queue=get_queue_name(),
		log_name=log_name,
		from_sweep=from_sweep,
		enqueue_after_commit=after_commit,
		job_id=f"teams_notify:{log_name}:{attempts}",
		deduplicate=True,
	)


def deliver(log_name: str, from_sweep: bool = False):
	"""RQ job: send one logged message, or park it until it may be sent."""
	log = frappe.get_doc("Teams Message Log", log_name)
	if log.status not in WAITING:
		return
	if log.next_attempt_at and log.next_attempt_at > now_datetime():
		return  # not due yet; process_due will pick it up

	if not frappe.db.get_single_value("Teams Settings", "enabled") and not log.is_test:
		return _finish(log, "Skipped", error="Teams Notify is disabled in Teams Settings.")

	if not log.destination or not frappe.db.exists("Teams Destination", log.destination):
		return _finish(log, "Skipped", error="Destination no longer exists.")

	destination = frappe.get_doc("Teams Destination", log.destination)
	if not destination.enabled:
		return _finish(log, "Skipped", error="Destination is disabled.")
	if destination.destination_type.startswith("Bot") and not frappe.db.get_single_value(
		"Teams Settings", "bot_enabled"
	):
		return _finish(log, "Skipped", error="The Teams bot is disabled in Teams Settings.")

	# Keep order: a new message waits behind older rate-limited ones for the same destination.
	if not from_sweep and not log.is_test and _has_older_throttled(log):
		return _park(log, "Throttled", 0)

	rate, burst = ratelimit.get_limits(destination)
	allowed, wait = ratelimit.take(destination.name, rate, burst)
	if not allowed:
		return _park(log, "Throttled", wait)

	message = OutboundMessage(
		log_name=log.name,
		destination=destination,
		payload=json.loads(log.payload),
		recipient_email=log.recipient_email,
		recipient_user=log.recipient_user,
	)
	try:
		result = get_sender(destination).send(message)
	except Exception:
		frappe.log_error(
			title="Teams Notify: sender error", reference_doctype="Teams Message Log", reference_name=log.name
		)
		result = SendResult(ok=False, error="Unexpected error while sending. See Error Log.")

	record_result(log, destination, result)


def record_result(log, destination, result: SendResult):
	now = now_datetime()
	attempts = (log.attempts or 0) + 1
	http_status = result.http_status or 0

	if result.ok:
		_finish(
			log,
			"Sent",
			attempts=attempts,
			http_status=http_status,
			sent_at=now,
			error=None,
			next_attempt_at=None,
			activity_id=result.activity_id,
			conversation_id=result.conversation_id,
		)
		destination.db_set({"last_success": now, "consecutive_failures": 0}, update_modified=False)
		return

	failures = (destination.consecutive_failures or 0) + 1
	destination.db_set(
		{"consecutive_failures": failures, "last_error_at": now, "last_error": result.error},
		update_modified=False,
	)
	threshold = frappe.db.get_single_value("Teams Settings", "failure_alert_threshold") or 0
	if threshold and failures == threshold:
		notify_admins(destination, result.error)

	max_retries = frappe.db.get_single_value("Teams Settings", "max_retries") or 0
	if result.retryable and attempts <= max_retries:
		delay = retry_delay(attempts, result.retry_after)
		if http_status == 429:
			ratelimit.block(destination.name, delay)
		status = "Throttled" if http_status == 429 else "Queued"
		error = _("Attempt {0} failed, retrying in {1}s: {2}").format(attempts, int(delay), result.error)
		return _park(log, status, delay, attempts=attempts, http_status=http_status, error=error)

	_finish(log, "Failed", attempts=attempts, http_status=http_status, error=result.error, next_attempt_at=None)


def retry_delay(attempts: int, retry_after: float | None = None) -> float:
	"""Backoff before the next try after `attempts` failed sends. Honours Retry-After when longer."""
	backoff = BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS)) - 1]
	return max(float(backoff), float(retry_after or 0))


def process_due():
	"""Cron (every minute): enqueue messages whose wait is over, and recover lost jobs."""
	now = now_datetime()
	due = frappe.get_all(
		"Teams Message Log",
		filters={"status": ("in", WAITING), "next_attempt_at": ("<=", now)},
		fields=["name", "destination"],
		order_by="creation asc",
		limit=SWEEP_LIMIT,
	)
	stuck = frappe.get_all(
		"Teams Message Log",
		filters={
			"status": "Queued",
			"next_attempt_at": ("is", "not set"),
			"modified": ("<", add_to_date(now, minutes=-STUCK_AFTER_MINUTES)),
		},
		fields=["name", "destination"],
		order_by="creation asc",
		limit=SWEEP_LIMIT,
	)

	# Enqueue at most `burst` per destination per tick; the rest would only be throttled again.
	budget: dict[str, int] = {}
	for row in due + stuck:
		if row.destination not in budget:
			budget[row.destination] = _burst_for(row.destination)
		if budget[row.destination] <= 0:
			continue
		budget[row.destination] -= 1
		schedule_delivery(row.name, after_commit=False, from_sweep=True)


def resend(log_name: str):
	"""Reset a log to Queued and deliver it again."""
	log = frappe.get_doc("Teams Message Log", log_name)
	if log.status == "Queued":
		return
	log.db_set(
		{"status": "Queued", "attempts": 0, "error": None, "http_status": 0, "next_attempt_at": None},
		update_modified=True,
	)
	schedule_delivery(log.name)


def notify_admins(destination, error: str | None):
	"""Tell Teams Admins (or System Managers if there are none) that a destination keeps failing."""
	from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

	users = _users_with_role("Teams Admin") or _users_with_role("System Manager")
	if not users:
		return
	subject = _("Teams destination {0} has failed {1} times in a row").format(
		destination.name, destination.consecutive_failures
	)
	message = _("Last error: {0}").format(frappe.utils.escape_html(error or ""))
	try:
		enqueue_create_notification(
			users,
			{
				"type": "Alert",
				"document_type": "Teams Destination",
				"document_name": destination.name,
				"subject": subject,
				"email_content": message,
			},
		)
		emails = [e for e in frappe.get_all("User", {"name": ("in", users)}, pluck="email") if e]
		if emails:
			frappe.sendmail(
				recipients=emails,
				subject=subject,
				message=f"<p>{subject}.</p><p>{message}</p><p>{frappe.utils.get_url_to_form('Teams Destination', destination.name)}</p>",
				reference_doctype="Teams Destination",
				reference_name=destination.name,
			)
	except Exception:
		frappe.log_error(title="Teams Notify: failure alert could not be sent")


def _users_with_role(role: str) -> list[str]:
	users = frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent", distinct=True)
	if not users:
		return []
	return frappe.get_all(
		"User",
		filters=[["name", "in", users], ["name", "!=", "Guest"], ["enabled", "=", 1], ["user_type", "=", "System User"]],
		pluck="name",
	)


def _has_older_throttled(log) -> bool:
	return bool(
		frappe.db.exists(
			"Teams Message Log",
			{"destination": log.destination, "status": "Throttled", "creation": ("<", log.creation)},
		)
	)


def _burst_for(destination: str) -> int:
	if not frappe.db.exists("Teams Destination", destination or ""):
		return SWEEP_LIMIT  # deliver() will mark these Skipped
	return ratelimit.get_limits(frappe.get_doc("Teams Destination", destination))[1]


def _park(log, status: str, seconds: float, **values):
	next_at = now_datetime() + timedelta(seconds=max(0.0, seconds))
	log.db_set({"status": status, "next_attempt_at": next_at, **values}, update_modified=True)


def _finish(log, status: str, **values):
	# The RQ job wrapper commits when the job returns.
	log.db_set({"status": status, **values}, update_modified=True)
