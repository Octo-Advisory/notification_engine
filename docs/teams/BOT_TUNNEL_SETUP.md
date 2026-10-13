# Teams bot on the dev site through a Cloudflare quick tunnel

A quick tunnel gives `teamsnotify.com` a temporary public HTTPS address, so Microsoft Teams can reach
the bot endpoint. It is for **testing only**. For production, use a real domain with HTTPS.

- `cloudflared` is installed at `~/.local/bin/cloudflared` (version 2026.10.0, checksum verified).
- The tunnel forwards to `http://127.0.0.1:8003`, the nginx port that serves `teamsnotify.com`.
- **The URL changes every time the tunnel starts.** Each time it does, update **Site URL** (step 2)
  and the **Azure Bot messaging endpoint** (step 4).
- While the tunnel runs, the dev site's login page is reachable from the internet. Use a strong
  Administrator password, and stop the tunnel when you are not testing.

---

## 1. Start, check and stop the tunnel

Start it (runs in the background, survives closing the terminal, stops on reboot or WSL shutdown):
```bash
setsid nohup cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8003 \
  > ~/teamsnotify-tunnel.log 2>&1 < /dev/null & echo $! > ~/teamsnotify-tunnel.pid
```

Get the current URL:
```bash
grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' ~/teamsnotify-tunnel.log | head -1
```

Check it reaches the site (expect `{"message":"pong"}`):
```bash
curl -s "$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' ~/teamsnotify-tunnel.log | head -1)/api/method/ping"
```

Is it running?
```bash
kill -0 "$(cat ~/teamsnotify-tunnel.pid)" && echo running || echo stopped
```

Stop it:
```bash
kill "$(cat ~/teamsnotify-tunnel.pid)"
```

The log line `failed to sufficiently increase receive buffer size` is a harmless performance warning.

---

## 2. Teams Settings (Frappe)

Open `http://172.18.139.166:8003/app/teams-settings`.

1. **Site URL**: paste the tunnel URL, for example `https://statute-ali-deleted-pal.trycloudflare.com`
   (no trailing slash). Save.
   - **Messaging Endpoint** now shows `https://<tunnel>/api/method/notification_engine.teams.bot.endpoint.receive`.
     Click **Teams Bot → Copy Messaging Endpoint**.
   - "Open in Frappe" links in cards now use the tunnel URL too. Put Site URL back to empty when you
     stop testing, or the links will break.
2. **Secret Expiry Date**: enter the client secret's expiry date from Entra ID. Save.
3. **Teams Bot → Check Bot Connection**.
   - ✅ "Connected: Microsoft issued a token for this bot."
   - ❌ `AADSTS7000215`: wrong secret value. Paste the secret **Value**, not the Secret ID.
   - ❌ `AADSTS700016`: App ID not found in this tenant. Check the App ID and Tenant ID.

---

## 3. Your own Frappe user (needed for buttons)

Buttons act **as the person who clicks**, so your Teams account must map to a Frappe user that has
the right roles. Administrator's email (`admin@example.com`) will not match your Teams email.

1. **User → New**: Email = **the email you sign in to Teams with**, plus your first name.
2. Roles: tick **System Manager**. The demo Approval Request and its workflow allow System Manager.
3. Save, and set a password if you want to log in as this user.

When you install the app in Teams (step 6), the bot links your Teams account to this user automatically.

---

## 4. Azure portal (IT or you)

Open the **Azure Bot** resource (not the App registration).

1. **Settings → Configuration**:
   - **Messaging endpoint**: paste the endpoint from step 2.
   - Check that the **Microsoft App ID** matches Teams Settings.
   - **Apply**.
2. **Settings → Channels**: under *Available channels* click **Microsoft Teams**, accept the terms,
   choose **Microsoft Teams Commercial**, then **Apply**.
   - ✅ Microsoft Teams shows as **Healthy** in the channel list.

Optional check: Azure Bot → **Test in Web Chat**, send "hi". Frappe should answer with the help
text. (Web Chat is not Teams, so it does not create a Teams User Map row.)

---

## 5. Teams app package

1. In Teams Settings, click **Teams Bot → Download Teams App Package**. Do this **after** step 2,
   so the package uses the tunnel domain.
   - Or from the terminal: `bench --site teamsnotify.com notification-engine build-teams-manifest`, which prints
     the path of `teams_notify_app.zip`.
2. Upload it, choosing one of these:
   - **For yourself (fastest)**: Teams → **Apps → Manage your apps → Upload an app → Upload a custom
     app**, pick the zip. This needs your org to allow custom app uploads. If the option is
     missing, ask IT.
   - **By IT for the organisation**: **Teams admin center → Teams apps → Manage apps → Upload new
     app**. Then allow it in a permission policy and, optionally, pre-install it with a setup policy.

You do not need a new package when the tunnel URL changes. The bot uses the endpoint configured in
Azure. Rebuild the package only if you change the Bot Name or App ID.

---

## 6. Test: personal chat (links your account)

1. In Teams, open the app (**ERP Notifications**, or your Bot Name) and click **Add / Open**.
2. Send it `hi`.
   - ✅ It replies "I send ERP notifications from … Open it here: …".
3. In Frappe open **Teams User Map** (`/app/teams-user-map`).
   - ✅ A row with your Teams name and **App Installed** ticked.
   - ✅ Within a minute, **Teams Email** and **Frappe User** (your user from step 3) fill in.
   - If Frappe User stays empty, the emails differ. Set **Frappe User** by hand and save.
4. **Teams Destination → Teams Bot (Personal) → Send Test Message**.
   - ✅ The test card arrives in your personal chat with the bot.

---

## 7. Test: group chat (OCTO Team)

1. In Teams, open the **OCTO Team** group chat and add the app to it. In the chat header, use
   **Apps / +** (or **… → Manage apps**), search for the bot's name, then **Add**.
2. In Frappe open **Teams Destination**.
   - ✅ A new destination **"OCTO Team (bot)"**, type **Bot Conversation**, **disabled**.
3. Open it, tick **Enabled**, save, click **Send Test Message**.
   - ✅ The card arrives in the group chat, posted by the bot.

---

## 8. Test: Approve / Reject buttons

1. Open the rule **Demo: Approval needed** and add **OCTO Team (bot)** to **Destinations**. Save.
   It already has **Show All Workflow Actions**, **Approve** (green) and **Reject** (red, reason required).
2. Create an **Approval Request** (`/app/approval-request/new`), save, then **Actions → Submit for Approval**.
   - ✅ In the OCTO Team chat, the bot's card has **Approve**, **Reject** and **Open in Frappe**.
3. Click **Approve** in Teams.
   - ✅ The card changes to "✅ Approve by <your name> at <time>" without buttons.
   - ✅ In Frappe the request is **Approved** with the comment "Approve from Microsoft Teams by <you>".
4. Make another request and click **Reject**, type a reason, then **Submit: Reject**.
   - ✅ The card shows the reason; the request is **Rejected** with your comment.

For more checks (no permission, unlinked user, double click, "Already Approved"), see
[TESTING.md](TESTING.md) Part E.

---

## Troubleshooting

| Symptom | What to check |
|---|---|
| Bot does not reply, no Teams User Map row | Tunnel running? Azure **Messaging endpoint** = current tunnel URL + `/api/method/notification_engine.teams.bot.endpoint.receive`? Teams channel **Healthy**? |
| Teams shows "Unable to reach app" on a button | Same as above, plus `tail -f ~/teamsnotify-tunnel.log` while clicking |
| Requests reach Frappe but are refused | `tail -f ~/frappe-bench/logs/notification_engine.log` shows "Rejected Teams bot request: <reason>" (e.g. wrong App ID → audience mismatch) |
| Bot replies, but group chat creates no destination | The app must be **added to the chat**, not only mentioned |
| "Your Teams account isn't linked to ERP" | Teams User Map row has no **Frappe User**: set it (step 6.3) |
| "You don't have permission…" / "not allowed to Approve" | Your Frappe user needs **System Manager** for the demo workflow |
| Everything stopped after a restart | The tunnel URL changed: redo step 2 (Site URL) and step 4.1 (messaging endpoint) |
| Code changes not active | `sudo supervisorctl restart all` |
