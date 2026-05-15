# Google OAuth setup for homebase

The Gmail and Google Calendar connectors share one OAuth 2.0 flow at
`/api/auth/google/login`. The operator (`bhavipatel141@gmail.com`) signs
in once; the backend keeps a refresh token at `/data/google_oauth.json`
and refreshes access tokens on demand for both connectors.

The repo is ready to consume the credentials — the only remaining work
is in the Google Cloud Console, then pasting two values into prod's
`.env`. This doc assumes you already have a GCP project; if you don't,
create one first and come back.

## What we need from you

By the end of this doc you'll send back two values:

```
GOOGLE_CLIENT_ID=<from step 3>
GOOGLE_CLIENT_SECRET=<from step 3>
```

That's it. The redirect URI is pinned to
`https://homebase.lebcp.com/api/auth/google/callback`; everything else
is wired up.

## Step 1 — enable the two APIs

In the GCP Console, **make sure your existing project is selected in the
top bar** before doing anything else (the next steps are
project-scoped).

1. **Navigation menu → APIs & Services → Library**.
2. Search **Gmail API** → click it → **Enable**.
3. Back to Library. Search **Google Calendar API** → **Enable**.

Sanity check: **APIs & Services → Enabled APIs & services** should list
both.

## Step 2 — configure the OAuth consent screen

This is the consent dialog Google shows the first time you authorize.
If your project has never had a consent screen, you'll be guided
through this; if it already has one, jump to the "make sure scopes are
right" sub-step below.

1. **APIs & Services → OAuth consent screen**.
2. **User Type**: **External**. (Internal is Workspace-only; a personal
   `@gmail.com` account must use External.) Click **Create**.
3. **App information**:
   - **App name**: `Homebase` (only you will see this).
   - **User support email**: `bhavipatel141@gmail.com`.
   - **App domain → Application home page**: `https://homebase.lebcp.com`
     (optional but quiets a warning).
   - **Developer contact information**: `bhavipatel141@gmail.com`.
4. **Save and continue**.
5. **Scopes → Add or remove scopes**. The set must be **exactly**:
   - `openid`
   - `.../auth/userinfo.email`
   - `.../auth/gmail.readonly`
   - `.../auth/calendar.readonly`

   These mirror `SCOPES` in `backend/google_oauth.py`. Don't add any
   write scopes — the dashboard never mutates Gmail/Calendar data, and
   Google's verification process is much friendlier for readonly.
6. **Save and continue**.
7. **Test users → Add users** → `bhavipatel141@gmail.com`. **Save and
   continue**.

### Testing vs. Published

The consent screen starts in **Testing** mode. That works for a
single-operator personal dashboard, with one catch: in Testing mode
**refresh tokens expire after 7 days of inactivity**, which would force
you to re-auth weekly.

**Recommended**: on the OAuth consent screen page, click **Publish app
→ Confirm**. With only readonly scopes on a personal account, Google
won't require verification, and refresh tokens last ~6 months of
inactivity. You can still keep the app private — "Publish" here just
means "not in Testing mode."

### If your project already had a consent screen

Open **APIs & Services → OAuth consent screen → Edit App** and verify:

- User Type is **External**.
- Scopes include the four listed above. Add any missing ones via **Edit
  → Scopes → Add or remove scopes**.
- `bhavipatel141@gmail.com` is on the test-users list (only relevant
  while in Testing mode).
- Ideally the app is **Published**, not in Testing.

## Step 3 — create the OAuth client

1. **APIs & Services → Credentials → Create credentials → OAuth client
   ID**.
2. **Application type**: **Web application**.
3. **Name**: `homebase backend` (internal label, not user-visible).
4. **Authorized JavaScript origins**: leave empty. We don't kick off
   OAuth from the browser; the backend issues the redirect.
5. **Authorized redirect URIs** → **Add URI**:
   ```
   https://homebase.lebcp.com/api/auth/google/callback
   ```
   This must match the backend's `GOOGLE_REDIRECT_URI` exactly —
   scheme, host, path, no trailing slash.

   If you want to round-trip the flow locally too, add:
   ```
   http://localhost:3000/api/auth/google/callback
   ```
   You can list multiple redirect URIs on the same client.
6. **Create**.

A dialog pops up showing **Your Client ID** and **Your Client Secret**.
**Copy both now** — the secret is only shown once. (You can rotate it
later from Credentials → the client → **Reset client secret** if
needed.)

## Step 4 — hand the credentials to the backend

Send the two values back. I'll write them into `~/homebase/deploy/.env`
on prod and redeploy:

```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

The `.env` file is chmod 600 and gitignored. `GOOGLE_REDIRECT_URI`
defaults to the prod URL — no need to set it unless you used a
different value in step 3.

Deploy:

```sh
ssh bp@100.91.251.82 'cd ~/homebase/deploy && ./deploy.sh'
```

The startup log should no longer warn about missing `GOOGLE_CLIENT_ID`
/ `GOOGLE_CLIENT_SECRET`.

## Step 5 — one-time sign-in

Open `https://homebase.lebcp.com/api/auth/google/login` in a browser.
Cloudflare Access will already have you authenticated. The backend
302s to Google's consent screen → approve → Google 302s back to
`/api/auth/google/callback?code=...` → the backend exchanges the code,
stores the refresh token at
`/srv/containers/homebase/data/google_oauth.json` (chmod 600), and
redirects you back to the dashboard with `?google=connected`.

Verify from the command line:

```sh
curl -H 'Cf-Access-Authenticated-User-Email: bhavipatel141@gmail.com' \
  https://homebase.lebcp.com/api/auth/google/status
# {"configured":true,"connected":true,"email":"bhavipatel141@gmail.com", ...}
```

The Sources panel will now show Gmail and Google Calendar as
**connected**, and `/api/edition` will include their payloads.

## Troubleshooting

**`redirect_uri_mismatch` on the consent screen.** The redirect URI on
the OAuth client (step 3) doesn't exactly match the backend's
`GOOGLE_REDIRECT_URI`. Compare character-by-character — trailing
slashes and `http` vs `https` count.

**"Google did not return a refresh_token" on the callback.** You
consented before with the same scopes and Google omitted the
refresh_token from the new response. Fix:
[Google Account → Apps with access](https://myaccount.google.com/permissions)
→ find "Homebase" → **Remove access** → retry the login.

**Refresh stops working after about a week.** The consent screen is
still in Testing mode. Click **Publish app** on the OAuth consent
screen page, then re-run `/api/auth/google/login` once.

**`invalid_grant` in the connector logs.** The refresh token was
revoked or expired (6 months of inactivity in Published mode). Re-run
`/api/auth/google/login` once.

## Disconnect

To revoke at Google and clear local tokens:

```sh
curl -X DELETE -H 'Cf-Access-Authenticated-User-Email: bhavipatel141@gmail.com' \
  https://homebase.lebcp.com/api/auth/google
```
