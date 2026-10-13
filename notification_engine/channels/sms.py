import frappe
import requests

from notification_engine.notification_engine.doctype.notification_engine_log.notification_engine_log import (
	create_log,
)


def send(rule, doc, users, subject, message):
	settings = frappe.get_cached_doc("Notification Engine Settings")

	if not settings.sms_gateway:
		for user in users:
			create_log(
				notification_rule=rule.name,
				channel="SMS",
				status="Skipped",
				user=user,
				reference_doctype=doc.doctype,
				reference_name=doc.name,
				error_message="No SMS gateway configured in Notification Engine Settings",
			)
		return

	for user in users:
		mobile_no = get_mobile_no(user)
		if not mobile_no:
			create_log(
				notification_rule=rule.name,
				channel="SMS",
				status="Skipped",
				user=user,
				reference_doctype=doc.doctype,
				reference_name=doc.name,
				error_message="No mobile number found on Employee or Contact record",
			)
			continue

		try:
			_send_via_gateway(settings, mobile_no, f"{subject}\n{message}")
			create_log(
				notification_rule=rule.name,
				channel="SMS",
				status="Success",
				user=user,
				reference_doctype=doc.doctype,
				reference_name=doc.name,
				subject=subject,
				content=message,
				recipient_address=mobile_no,
			)
		except Exception as e:
			create_log(
				notification_rule=rule.name,
				channel="SMS",
				status="Failed",
				user=user,
				reference_doctype=doc.doctype,
				reference_name=doc.name,
				subject=subject,
				content=message,
				recipient_address=mobile_no,
				error_message=str(e),
			)


def get_mobile_no(user_email):
	"""Resolution chain: Employee.cell_number, then Contact.mobile_no.

	ERPNext HR-driven orgs almost always have Employee.user_id populated;
	Contact is the fallback for users who aren't employees (e.g. external
	approvers, customers with portal logins).
	"""
	mobile_no = frappe.db.get_value("Employee", {"user_id": user_email}, "cell_number")
	if mobile_no:
		return mobile_no

	contact_name = frappe.db.get_value("Contact", {"user": user_email}, "name")
	if contact_name:
		mobile_no = frappe.db.get_value("Contact", contact_name, "mobile_no")
		if mobile_no:
			return mobile_no

	return None


def _send_via_gateway(settings, mobile_no, text):
	api_key = settings.get_password("sms_api_key", raise_exception=False)

	if settings.sms_gateway == "Twilio":
		# Twilio expects Basic Auth (Account SID as username, Auth Token as
		# password) and a From number; adjust field usage to match your
		# actual Twilio account setup.
		response = requests.post(
			settings.sms_api_url,
			data={"To": mobile_no, "From": settings.sms_sender_id, "Body": text},
			auth=(settings.sms_sender_id, api_key),
			timeout=10,
		)
	elif settings.sms_gateway == "MSG91":
		response = requests.post(
			settings.sms_api_url,
			json={"mobiles": mobile_no, "message": text, "sender": settings.sms_sender_id},
			headers={"authkey": api_key},
			timeout=10,
		)
	else:  # Custom HTTP
		response = requests.post(
			settings.sms_api_url,
			json={"to": mobile_no, "message": text, "sender": settings.sms_sender_id, "api_key": api_key},
			timeout=10,
		)

	response.raise_for_status()
