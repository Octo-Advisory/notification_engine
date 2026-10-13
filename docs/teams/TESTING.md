# Teams Notify: manual test guide

> **Notification Engine:** Teams Notify is now part of Notification Engine. Where this guide says
> **Teams Notification Rule**, use **Notification Rule** with **Microsoft Teams** ticked under Channels.
> Field names on that form: Document Type → *Reference Document Type*, New / Save / Submit / Cancel /
> Delete → *After Insert / On Update / On Submit / On Cancel / On Trash*, Title / Body → *Teams Title* /
> *Teams Body* (empty: Subject / Message), Destinations → *Teams Chats / Channels*, Personal Destination
> → *Personal Destination*, Recipients → the rule's *Recipient Source* (e.g. *Document Field (User)* =
> `owner`). The *Method* event no longer exists.


Work through the parts in order. Each step says what to do, then what you should see ( ✅ ).
Tick the boxes as you go.

| Part | What it covers | Needs |
|---|---|---|
| [0](#part-0-before-you-start) | Preparation | Nothing |
| [A](#part-a-webhook-notifications) | Webhook notifications, rules, cards, events | Your Workflows webhook (Team Notify) |
| [B](#part-b-reliability) | Rate limits, retries, alerts, digests, imports, API | Same |
| [C](#part-c-personal-messages-through-power-automate-flow-bot) | Personal messages through the Flow bot | IT: second Power Automate flow |
| [D](#part-d-teams-bot) | Teams bot: connection, install, chats, personal messages | IT: Azure Bot, Teams channel, app upload. **A public HTTPS URL** |
| [E](#part-e-buttons-in-teams-cards) | Approve / Reject / custom buttons from Teams | Same as D |
| [F](#part-f-automated-tests) | The automated test suite | Nothing |

Site used below: `http://172.18.139.166:8003` (site `teamsnotify.com`). Run terminal commands from
`/home/jenith/frappe-bench`.

> **Tip:** most results show in **Teams Message Log** (`/app/teams-message-log`). The list does not
> refresh by itself on this bench (no socket.io), so press the refresh button.

---

## Part 0: Before you start

1. Restart the bench so the web server and workers run the latest code:
   ```bash
   sudo supervisorctl restart all
   ```
2. In the browser press **Ctrl+Shift+R** to reload without cache, then log in as Administrator.
3. Open **Teams Settings** (`/app/teams-settings`):
   - [ ] Tick **Enabled** and save. ✅ Saved with no error.
   - [ ] Check **Default Rate per Second** = `0.07` and **Default Burst** = `4`.
4. Confirm the scheduler is on (needed for retries, digests and date rules):
   ```bash
   bench --site teamsnotify.com scheduler status
   ```
   - [ ] ✅ `Scheduler is enabled for site teamsnotify.com`

---

## Part A: Webhook notifications

### A1. Destination and test message
1. Open **Teams Destination → Team Notify**.
2. Click **Send Test Message**.
   - [ ] ✅ A popup shows the destination as **Sent**.
   - [ ] ✅ A card **"[TEST] Teams Notify test message"** appears in your Teams chat.
   - [ ] ✅ The form's header shows **"Last delivered … ago"** in green.
3. Click the **Webhook URL** field.
   - [ ] ✅ It shows only asterisks; the real URL is never shown again.

### A2. Message Log
1. Open **Teams Message Log**.
   - [ ] ✅ The test message is listed with a green **Sent** badge.
2. Open it.
   - [ ] ✅ **Attempts** = 1, **HTTP Status** = 202 (or 200), **Payload** shows the card JSON.
3. Click **Resend**.
   - [ ] ✅ The same card arrives in Teams again; Attempts resets and the log is Sent again.
4. In the list, tick two logs, then **Actions → Resend**.
   - [ ] ✅ "2 message(s) queued again", and both cards arrive.

### A3. A rule on any record (ToDo, event "New")
1. **Teams Notification Rule → New**:
   - Rule Name: `ToDo created`
   - Document Type: `ToDo`, Event: `New`
   - Condition: `doc.priority == "High"`
   - Title: `New ToDo: {{ doc.name }}`, Title Colour: `Attention`
   - Body: `{{ doc.description | striptags }}`
   - Fields to Show: `priority`, `date`, `allocated_to`, `owner`
   - Destinations: `Team Notify`
2. Save.
   - [ ] ✅ It saves. The **Field** dropdowns list ToDo's fields.
3. Create a ToDo with priority **Medium**.
   - [ ] ✅ Nothing is sent (condition is false).
4. Create a ToDo with priority **High**, a due date and "Assigned To" set to yourself.
   - [ ] ✅ A red-titled card arrives with the description and the fields: Priority, Due Date, Assigned To (full name), Created By (full name).
   - [ ] ✅ **Open in Frappe** opens that ToDo at `http://172.18.139.166:8003/app/todo/...`.

### A4. Send Test from a rule
1. On the rule, click **Send Test**, leave Document empty, click **Send**.
   - [ ] ✅ A card titled **"[TEST] New ToDo: …"** arrives for the latest ToDo.
   - [ ] ✅ If the latest ToDo is not High priority, an orange note says the condition is false for it.
2. Repeat and pick a specific ToDo in the dialog.
   - [ ] ✅ The card shows that ToDo.

### A5. Other events
For each, edit the rule (or copy it) and keep Destinations = Team Notify. Remove the condition
unless stated.

| Event | Setup | Do this | ✅ Expect |
|---|---|---|---|
| **Save** | Event `Save` | Edit any ToDo and save | One card per save (also when created) |
| **Value Change** | Event `Value Change`, Value Changed `status` | Change a ToDo's status Open → Closed | One card. Saving without changing status sends nothing. Creating a new ToDo sends nothing |
| **Delete** | Event `Delete` | Delete a ToDo | One card **without** an Open button. The ToDo deletes normally |
| **Method** | Event `Method`, Method `on_update` | Save a ToDo | One card |
| **Days Before** | Event `Days Before`, Date Field `date`, Days `2` | Make a ToDo due in 2 days, then run the command below | One card for that ToDo |
| **Days After** | Event `Days After`, Date Field `date`, Days `1` | Make a ToDo due yesterday, then run the command below | One card |

Date rules run once a day. To run them now:
```bash
bench --site teamsnotify.com execute notification_engine.engine.events.run_scheduled_checks
```
- [ ] ✅ Running the command a second time the same day sends nothing new (no duplicates).

**Submit** and **Cancel** need a submittable DocType (for example ERPNext's Purchase Order). This
site has none, so the rule form refuses those events for ToDo. That refusal is the expected result.

### A6. Cards: colours, Jinja, custom card
1. On a rule, try each **Title Colour** (Default, Accent, Good, Warning, Attention) with Send Test.
   - [ ] ✅ The title colour changes in Teams.
2. Untick **Include 'Open in Frappe' Button** and Send Test.
   - [ ] ✅ The card has no button.
3. Open **Custom Card (Advanced)** and paste into **Card Template**:
   ```json
   {"type": "AdaptiveCard", "version": "1.4", "body": [
     {"type": "TextBlock", "text": "Custom card for {{ doc.name }}", "weight": "Bolder"},
     {"type": "TextBlock", "text": "Priority: {{ doc.priority }}", "wrap": true}
   ]}
   ```
   Save and Send Test.
   - [ ] ✅ Your custom layout arrives. Clear the template again afterwards.

### A7. Rule validation (each should be refused with a clear message)
- [ ] Condition `doc.status ==` → "Condition is not a valid Python expression".
- [ ] Title `{{ doc.name ` → template error.
- [ ] Card Template `{ not json` → "did not render valid JSON".
- [ ] Fields to Show with a field listed twice → "listed twice".
- [ ] Document Type `Email Account`, Fields to Show `password` → "Password fields cannot be sent to Teams".
- [ ] Event `Submit` on ToDo → "not submittable".
- [ ] No destinations and no recipients → "Add at least one destination or recipient".

### A8. Approval flow (demo Approval Request)
The demo has rules **Demo: Approval needed / Approved / Rejected** posting to Team Notify.
1. Open `/app/approval-request/new`, enter Title and Amount, save.
   - [ ] ✅ State **Draft**, nothing sent.
2. **Actions → Submit for Approval**.
   - [ ] ✅ Yellow card **"⏳ Approval needed: …"** with Title, Amount (₹), Required By, Requested By.
3. **Actions → Approve**.
   - [ ] ✅ Green card **"✅ Approved: …"**, "Approved by Administrator."
4. Create another one, submit it, then **Actions → Reject**.
   - [ ] ✅ Red card **"❌ Rejected: …"**.

Use the same pattern for any DocType: add a **Workflow** (`/app/workflow/new`), then a rule with
Event **Value Change** on `workflow_state` and a condition such as `doc.workflow_state == "Approved"`.

---

## Part B: Reliability

### B1. Rate limit (no 429 storms)
Make sure the **ToDo created** rule from A3 is enabled (condition `doc.priority == "High"`), and
**disable the other ToDo rules from A5** so they don't add cards. Then create 10 High-priority
ToDos at once:
```bash
bench --site teamsnotify.com console
```
```python
for i in range(10):
    frappe.get_doc({"doctype": "ToDo", "description": f"Rate test {i}", "priority": "High"}).insert()
frappe.db.commit()
exit()
```
- [ ] ✅ Within seconds, about **4** logs are **Sent** and the rest are **Throttled** with a
      **Next Attempt At** time.
- [ ] ✅ About 4 more go out each minute until all 10 are Sent, **oldest first**.
- [ ] ✅ No log shows HTTP 429.

### B2. Retries and backoff (server unreachable)
Use a separate destination so your real one is untouched.
1. New **Teams Destination**: name `Broken Test`, type `Webhook`, URL `https://example.invalid/test`.
2. In **Teams Settings** set **Max Retries** = `2` and save (so the test finishes in about 2 minutes).
3. On `Broken Test`, click **Send Test Message**.
   - [ ] ✅ The log becomes **Queued** with **Attempts** 1 and Error
         "Attempt 1 failed, retrying in 5s: ConnectionError".
   - [ ] ✅ About a minute later: Attempts 2, "retrying in 30s".
   - [ ] ✅ After the next try: **Failed**, Attempts 3.
4. Set **Max Retries** back to `5`.

### B3. Client errors fail at once (no retry)
1. New destination `Bad Signature Test`, type `Webhook`. Paste your real Workflows URL but change a
   few characters after `sig=`.
2. **Send Test Message**.
   - [ ] ✅ **Failed** after 1 attempt with an HTTP 4xx error (usually 401). The URL never appears in the error.

### B4. Failure alert to admins
The alert fires once, when a destination's failure count **reaches** the threshold.
`Bad Signature Test` has 1 failure from B3.
1. In **Teams Settings** set **Failure Alert Threshold** = `3`.
2. On `Bad Signature Test`, click **Send Test Message** twice more (failures 2 and 3).
   - [ ] ✅ The bell icon shows **"Teams destination Bad Signature Test has failed 3 times in a row"**.
   - [ ] ✅ The destination form shows a red header with the failure count and last error.
   - [ ] ✅ A 4th failure does not alert again.
   - Email: an alert email is also queued. This site has no outgoing email account, so it won't
     actually send here.
3. Set the threshold back to `5`.

### B5. Resend after a fix
1. Open a **Failed** log of `Bad Signature Test`. Fix the problem: paste the correct URL on that destination and save.
2. On the log, click **Resend**.
   - [ ] ✅ It becomes **Sent**, and the destination's failure count resets to 0.
3. Delete the `Broken Test` and `Bad Signature Test` destinations.

### B6. Disabled switches
- [ ] Untick **Enabled** on a destination and trigger a rule → the log is **Skipped**, "Destination is disabled".
- [ ] Untick **Enabled** in Teams Settings and create a High ToDo → nothing is logged. (**Send Test** still works on purpose.) Tick it again.
- [ ] Untick **Enabled** on a rule → that rule sends nothing.

### B7. Cooldown
1. Rule with Event `Save`, **Cooldown (Minutes)** = `10`.
2. Create a ToDo (Save also fires on create), then edit and save it twice more within a minute.
   - [ ] ✅ Only one card, from the create. Another ToDo still sends straight away.

### B8. Digest (one summary card)
1. Rule with Event `New`, **Digest** = `Hourly`, Destinations `Team Notify`.
2. Create 3 ToDos.
   - [ ] ✅ No cards yet. **Teams Digest Buffer** (`/app/teams-digest-buffer`) has 3 rows.
3. Wait for the next full hour, or flush now as if an hour had passed:
   ```bash
   bench --site teamsnotify.com console
   ```
   ```python
   from frappe.utils import add_to_date, now_datetime
   from notification_engine.teams.delivery.digest import flush
   flush("Hourly", now=add_to_date(now_datetime(), hours=1)); frappe.db.commit(); exit()
   ```
   - [ ] ✅ One card **"<rule name>: 3 update(s)"** listing the 3 ToDos as links. The buffer is empty.
   - [ ] ✅ With more than 20 items, the card ends with "and N more".

### B9. Data Import is silent by default
1. **Data Import → New**, Document Type `ToDo`, import 3 High-priority rows.
   - [ ] ✅ No cards (imports are suppressed).
2. Tick **Send During Data Import** on the rule and import again.
   - [ ] ✅ Cards arrive.

### B10. Python API (for your own code)
```bash
bench --site teamsnotify.com console
```
```python
from notification_engine.teams.api import send_to_teams
send_to_teams("Team Notify", title="Server check", text="Backup finished OK")
frappe.db.commit(); exit()
```
- [ ] ✅ A card "Server check / Backup finished OK" arrives.

### B11. Log purge
Logs older than **Log Retention (Days)** (30) are deleted daily; 0 keeps them forever. To run it now:
```bash
bench --site teamsnotify.com execute notification_engine.teams.tasks.purge_old_logs
```
- [ ] ✅ Recent logs stay. Only Sent/Failed/Skipped logs older than the retention are removed.

---

## Part C: Personal messages through Power Automate (Flow bot)

**Needs IT:** a second flow (spec Appendix B):
- trigger **When a Teams webhook request is received** (Anyone)
- action **Post card in a chat or channel**: Post as **Flow bot**, Post in **Chat with Flow bot**
- Recipient `triggerBody()?['recipient']`
- Adaptive Card `triggerBody()?['attachments'][0]['content']`

1. New **Teams Destination**: type `Webhook (Personal via Flow bot)`, paste that flow's URL.
2. **Send Test Message**.
   - [ ] ✅ The card arrives in **your own** chat with Flow bot, sent to your user's email.
3. On a rule, open **Personal Messages**:
   - Recipients: `Owner`, plus `User` = a colleague, plus `Role` = a role
   - Personal Destination: the Flow-bot destination
4. Trigger the rule.
   - [ ] ✅ One personal card per person, no duplicates. Disabled users get nothing.
   - [ ] ✅ Rule **Send Test** sends the personal card only to **you**, never to the real recipients.

Other recipient types to try:
- **Document Field**: a field that holds a user or an email, for example `allocated_to`.
- **Assigned To**: the people assigned with the sidebar "Assign To".

---

## Part D: Teams bot

**Needs, before D2:**
- IT has enabled **Channels → Microsoft Teams** on the Azure Bot.
- A **public HTTPS URL** for this site (`172.18.139.166` is private, so Teams cannot reach it).
- The Azure Bot's **Messaging endpoint** set to `https://<public-host>/api/method/notification_engine.teams.bot.endpoint.receive`.

### D1. Credentials (works now, no public URL needed)
1. **Teams Settings → Teams Bot**: tick **Enable Teams Bot**. Enter:
   - App (Client) ID and Tenant ID
   - **Client Secret** (type it here; never paste it in chat or email)
   - Secret Expiry Date and Bot Name
   
   Save.
   - [ ] ✅ **Messaging Endpoint** fills in. A **Teams Bot (Personal)** destination is created.
   - [ ] ✅ An ID that is not a GUID is refused.
2. **Teams Bot → Check Bot Connection**.
   - [ ] ✅ "Connected: Microsoft issued a token for this bot."
   - [ ] ✅ With a wrong secret: "Token request failed (HTTP 401): AADSTS…". Then put the right one back.
3. Set **Secret Expiry Date** to 10 days from today.
   - [ ] ✅ An orange banner warns that the secret expires in 10 days. Restore the real date.

### D2. Teams app package
1. **Teams Bot → Download Teams App Package** (or run `bench --site teamsnotify.com notification-engine build-teams-manifest`).
   - [ ] ✅ `teams_notify_app.zip` containing `manifest.json`, `color.png` and `outline.png`.
2. Set **Site URL** in Teams Settings to the public HTTPS address first, so the package's domain is right.
3. IT uploads the zip in **Teams Admin Center → Manage apps → Upload**, and installs it for users
   (setup policy) or for test users.

### D3. Personal install links your user
1. In Teams, open the app (or chat with the bot).
   - [ ] ✅ **Teams User Map** (`/app/teams-user-map`) has a row with your Teams name, **App Installed** ticked.
   - [ ] ✅ Within a minute, **Teams Email** and **Frappe User** fill in (matched by email).
2. Send the bot "hi".
   - [ ] ✅ It replies "I send ERP notifications from … Open it here: …".

### D4. Bot in a group chat or channel
1. Add the bot to the OCTO Team group chat (or a team channel).
   - [ ] ✅ A **Teams Destination** "OCTO Team (bot)" appears, type **Bot Conversation**, **disabled**.
2. Tick **Enabled**, save, **Send Test Message**.
   - [ ] ✅ The test card arrives in that chat, posted by your bot (its name and icon).
3. Remove the bot from the chat.
   - [ ] ✅ The destination is disabled again.

### D5. Personal messages through the bot
1. On a rule, set Recipients (for example `Owner`) and Personal Destination **Teams Bot (Personal)**.
2. Trigger it.
   - [ ] ✅ The card arrives in each recipient's personal chat with the bot.
   - [ ] ✅ For someone who has not installed the app: the log is **Failed**, "Teams app not installed for this user".

---

## Part E: Buttons in Teams cards

**Needs:** Part D working, and the people who will click have a linked **Teams User Map** row.

The demo rule **Demo: Approval needed** already has buttons:
- **Show All Workflow Actions**
- **Approve** (green)
- **Reject** (red; asks for a reason, required)

### E1. Approve from Teams
1. Add **OCTO Team (bot)** to the rule's **Destinations** and save.
2. Create an Approval Request and **Submit for Approval**.
   - [ ] ✅ The bot card shows **Approve**, **Reject** and **Open in Frappe**. (The webhook card in Team Notify still has only Open in Frappe.)
3. Click **Approve** in Teams.
   - [ ] ✅ The card changes to "✅ Approve by <your name> at <time>" and the buttons disappear.
   - [ ] ✅ In Frappe the request is **Approved**, with comment "Approve from Microsoft Teams by <you>".
   - [ ] ✅ The "✅ Approved" notification rule fires as usual.

### E2. Reject with a reason
1. New request → Submit for Approval → in Teams click **Reject**.
   - [ ] ✅ A text box opens. **Submit: Reject** with an empty box shows "A comment is required."
2. Type a reason and submit.
   - [ ] ✅ Card shows the status and "Comment: <your reason>". The document is **Rejected** and has the comment.

### E3. Safety checks
- [ ] **Already done**: click Approve on an old copy of a card whose request was already handled → "Already Approved (last changed by …)". Nothing changes.
- [ ] **Other copies update**: with the card in two places (group chat and a personal chat), approve in one; the other copy loses its buttons within a minute.
- [ ] **No permission**: a linked user without the System Manager role clicks Approve → "You don't have permission…" or "You are not allowed to Approve". Nothing changes.
- [ ] **Not linked**: someone whose Teams account has no Frappe User in Teams User Map clicks → "Your Teams account isn't linked to ERP".
- [ ] **Double click**: two quick clicks → the second says someone is already acting on it; only one action happens.
- [ ] **Test cards**: rule **Send Test** card → clicking a button says "This is a test card. Nothing was changed in ERP."

### E4. Custom "Set Value" button
1. On a ToDo rule that sends to the bot destination, add a **Buttons** row:
   - Type `Set Value`, Field `priority`, Value `High`, Label `Make urgent`, Style `destructive`.
2. Trigger it and click **Make urgent** in Teams.
   - [ ] ✅ The ToDo's priority becomes High, the card shows "✅ Make urgent by …", and a comment is added.

---

## Part F: Automated tests

Runs the whole suite (151 tests, mocked HTTP, no real Teams calls). Your data is not changed.
```bash
bench --site teamsnotify.com run-tests --app notification_engine
```
- [ ] ✅ `Ran 151 tests … OK`

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Nothing happens on save | Teams Settings **Enabled**? Rule **Enabled**? Condition true? The rule's **Send Test** works? |
| Logs stay **Queued** | Background workers running (`sudo supervisorctl status`)? Scheduler enabled? |
| Logs **Throttled** for long | Normal under load (about 4/min per webhook). Use **Digest** for busy rules. |
| **Sent** but no card in Teams | The workflow accepted it; check the flow's **run history** in Power Automate. |
| Page errors after an update | `sudo supervisorctl restart all`, then Ctrl+Shift+R. |
| **Failed**, "Teams app not installed" | Install the app for that user; check their **Teams User Map** row. |
| Bot never creates destinations or user maps | The Messaging endpoint must be public HTTPS, and the Teams channel must be enabled on the Azure Bot. |
| Check Bot Connection fails with AADSTS7000215 | Wrong or expired client secret: create a new one in Entra ID. |
