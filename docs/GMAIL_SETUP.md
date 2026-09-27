# Connecting Gmail (once, on the desktop)

The app reads Gmail through Google's official API with **read-only** permission
(`gmail.readonly`). It cannot send, delete or change mail. The authorisation files stay
in the desktop's `secrets\` folder and are never committed to Git.

## 1. Create an OAuth client in Google Cloud (about 5 minutes)

1. Open https://console.cloud.google.com/ and sign in with the Gmail account that
   receives the timesheets. Create a project (e.g. "Timesheet Tracker").
2. **APIs & Services → Library** → search **Gmail API** → **Enable**.
3. **APIs & Services → OAuth consent screen** (Google Auth Platform):
   * User type **External** (or Internal for Google Workspace), app name "Timesheet Tracker".
   * Add your own address as a **Test user** (while the app is in "Testing").
   * Scopes: you can leave this; the app asks for `gmail.readonly` itself.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   * Application type: **Desktop app**. Create.
   * **Download JSON**.
5. Save the downloaded file as:

   ```text
   <TIMESHEET_HOME>\secrets\gmail_credentials.json
   ```

   (the `secrets` folder is created on first start; with the default settings it is
   inside the project folder).

> While the consent screen is in **Testing**, Google expires the authorisation after
> **7 days**. To avoid re-connecting weekly, set the app to **In production** on the
> consent screen (for personal use Google shows an "unverified app" warning you can
> accept for your own account), or use a Google Workspace account with an **Internal** app.

## 2. Authorise (1 minute)

On the desktop, double-click **`scripts\gmail_auth.bat`**. A browser opens; sign in to
the timesheet mailbox and allow read-only access. The window prints
`Gmail connected: you@…`. The token is saved as `secrets\gmail_token.json`.

## 3. Check

Open the app → **Imports**. "Gmail connection" should say **Connected**. Press
**Sync Gmail Now**. From then on the desktop checks Gmail every 15 minutes (Settings).

## What is imported

* Search (Settings → Gmail search): `has:attachment (filename:xlsx OR filename:xlsm)`
  plus `after:<today − lookback days>`. Narrow it, e.g. add `subject:timesheet`.
* **Only accept from** (Settings): restrict to `@yourcompany.com` or specific addresses.
* Each message is processed once (tracked by Gmail message ID in the database).
* Every attachment is saved under `imports\YYYY\MM\` before processing.
* `.xls` (old Excel format) files are recorded as failed with a message asking for `.xlsx`.

## Troubleshooting

| Message | Fix |
|---|---|
| "Gmail is not connected" | Step 2 not done, or token file deleted. Run `scripts\gmail_auth.bat`. |
| "OAuth client file not found" | Save the JSON from step 1.4 as `secrets\gmail_credentials.json`. |
| "authorisation has expired" / `invalid_grant` | Consent screen in Testing (7-day limit) or access revoked. Run `scripts\gmail_auth.bat` again. |
| Nothing imported | Check the Gmail search and allowed senders in Settings; check Imports → Background activity. |
