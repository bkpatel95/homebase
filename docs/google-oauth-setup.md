# Google OAuth setup for homebase

The Gmail and Google Calendar connectors both authenticate through a
single shared OAuth flow at `/api/auth/google/login`. The operator
(`bhavipatel141@gmail.com`) signs in once; the backend keeps a refresh
token at `/data/google_oauth.json` and refreshes access tokens on demand
for both connectors.

This doc covers what has to happen in the Google Cloud Console before
that flow will work. The code in this repo is ready to consume the
credentials — there is nothing to deploy after step 5 except restarting
the container.

## What you'll end up with

- A Google Cloud project (e.g. `homebase-prod`)
- Gmail API and Google Calendar API enabled on that project
- An OAuth consent screen configured in **External** mode and published
- An OAuth 2.0 **Web application** client with:
  - Authorized redirect URI: `https://homebase.lebcp.com/api/auth/google/callback`
  - Client ID + Client Secret pasted into `~/homebase/deploy/.env` on prod

Once those exist, sign in once at
`https://homebase.lebcp.com/api/auth/google/login`. The callback stores
the refresh token in `/srv/containers/homebase/data/google_oauth.json`
(chmod 600) and both connectors flip to "connected".

## Step 1 — create the Google Cloud project

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. In the project picker (top bar) → **New Project**.
3. Name it something memorable: `homebase-prod`. Leave the org blank if
   prompted (this is a personal account).
4. Click **Create**, then switch the project picker to it.

## Step 2 — enable the APIs

In the new project:

1. Navigation menu → **APIs & Services** → **Library**.
2. Search **Gmail API** → **Enable**.
3. Search **Google Calendar API** → **Enable**.

You should now see both under **APIs & Services** → **Enabled APIs**.

## Step 3 — configure the OAuth consent screen

This is the screen Google shows when you first authorize the app.

1. **APIs & Services** → **OAuth consent screen**.
2. **User Type**: **External**. (Internal is only for Google Workspace
   orgs; a personal Gmail account must use External.)
3. Click **Create** and fill in:
   - **App name**: `Homebase` (or `The Daily Bhavi` — only you ever see this).
   - **User support email**: `bhavipatel141@gmail.com`.
   - **App logo**: optional.
   - **App domain → Application home page**: `https://homebase.lebcp.com`.
   - **Developer contact information**: `bhavipatel141@gmail.com`.
4. **Save and continue**.
5. **Scopes** → **Add or remove scopes** → add exactly these:
   - `openid`
   - `.../auth/userinfo.email`
   - `.../auth/gmail.readonly`
   - `.../auth/calendar.readonly`

   These match `SCOPES` in `backend/google_oauth.py`. Don't add write
   scopes — the app never mutates Gmail or Calendar data.
6. **Save and continue**.
7. **Test users** → add `bhavipatel141@gmail.com` as a test user.

   Note: an External app starts in "Testing" mode, which works fine for a
   single-operator personal dashboard. You can leave it that way
   indefinitely. The only side effect is that the refresh token expires
   after **7 days of inactivity** while the app is in Testing. To switch
   to a stable refresh token that lasts ~180 days, click **Publish app**
   on the consent screen. Google does not require verification for
   "sensitive scopes" if your app is only used by accounts you own.

   Recommended: publish it. Personal account → no verification needed
   for the readonly scopes we're using.

## Step 4 — create the OAuth 2.0 client

1. **APIs & Services** → **Credentials** → **Create Credentials** →
   **OAuth client ID**.
2. **Application type**: **Web application**.
3. **Name**: `homebase backend`.
4. **Authorized JavaScript origins**: leave empty (we don't initiate
   from JS).
5. **Authorized redirect URIs**: add
   `https://homebase.lebcp.com/api/auth/google/callback`.

   This must match `GOOGLE_REDIRECT_URI` in the backend's environment
   exactly — including scheme, host, port, and path. Trailing slashes
   count.

   If you also want to do a local dev round-trip, add
   `http://localhost:3000/api/auth/google/callback` here too. You can
   list multiple URIs on the same client.
6. **Create**. The dialog will show **Your Client ID** and **Your
   Client Secret**. Copy both — the secret is only shown once. (You can
   regenerate it later from the Credentials page if needed.)

## Step 5 — put the credentials on the prod box

On the Mac, locally edit `deploy/.env.example` if you need to remember
the shape, then ssh in:

```sh
ssh bp@100.91.251.82
cd ~/homebase/deploy
# .env is chmod 600 and gitignored.
vim .env
```

Set:

```
GOOGLE_CLIENT_ID=<paste client id from step 4>
GOOGLE_CLIENT_SECRET=<paste client secret from step 4>
# GOOGLE_REDIRECT_URI defaults to the prod URL; only set it if you
# changed the redirect URI in the OAuth client.
```

Then redeploy from the Mac (don't edit anything in `~/homebase/` outside
`deploy/.env` — the dirty-tree guard in `deploy.sh` will refuse to
deploy on the next run):

```sh
ssh bp@100.91.251.82 'cd ~/homebase/deploy && ./deploy.sh'
```

The startup log should no longer warn about `GOOGLE_CLIENT_ID` and
`GOOGLE_CLIENT_SECRET`.

## Step 6 — sign in once

Open `https://homebase.lebcp.com/api/auth/google/login` in a browser.
Cloudflare Access will already have you authenticated as
`bhavipatel141@gmail.com`. The backend will 302 to Google's consent
screen; approve. Google will 302 back to
`https://homebase.lebcp.com/api/auth/google/callback?code=...`, which
exchanges the code for tokens and 302s you back to the dashboard with
`?google=connected`.

To verify:

```sh
curl -H 'Cf-Access-Authenticated-User-Email: bhavipatel141@gmail.com' \
  https://homebase.lebcp.com/api/auth/google/status
# {"configured":true,"connected":true,"email":"bhavipatel141@gmail.com", ...}
```

The Sources panel in the UI will now show Gmail and Google Calendar as
**connected**, and `/api/edition` will start including their payloads.

## Troubleshooting

**"redirect_uri_mismatch" on the consent screen.** The redirect URI
configured in Google Cloud Console does not exactly match
`GOOGLE_REDIRECT_URI` in the backend. Compare them character-by-character.

**"Google did not return a refresh_token" on the callback.** You've
consented before with the same scopes, so Google omitted the
refresh_token from the second consent. Visit
[Google Account → Apps with access](https://myaccount.google.com/permissions),
find "Homebase" (or whatever you named it), revoke access, and re-run
the login flow. The backend requests `prompt=consent` to mitigate this,
but Google sometimes still suppresses the refresh_token if you previously
revoked manually and re-consented in the same session.

**Refresh stops working after a week.** The app is in Testing mode on
the consent screen — refresh tokens expire after 7 days of inactivity in
that mode. Publish the app (Step 3, last paragraph) and re-run the login
flow once.

**"invalid_grant" in the connector logs.** The refresh token was
revoked, either manually from
[Google Account permissions](https://myaccount.google.com/permissions)
or after 6 months of inactivity. Just re-run `/api/auth/google/login`.

## Disconnect

To revoke and clear the local tokens:

```sh
curl -X DELETE -H 'Cf-Access-Authenticated-User-Email: bhavipatel141@gmail.com' \
  https://homebase.lebcp.com/api/auth/google
```

This calls Google's revoke endpoint and deletes
`/srv/containers/homebase/data/google_oauth.json` inside the container.
