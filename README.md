# Student Wellbeing API

Python backend and browser frontend MVP for student workload and well-being tracking. It includes the Balm academic wellbeing chatbot, daily check-ins, a weekly schedule, app email/password accounts, and a separately linked Google Calendar connection.

The Wellbeing section also supports meal suggestions from a typed dish name, a photo, or both. JPEG, PNG, and WebP uploads up to 8 MB are analyzed with the configured OpenAI model at high image detail. The prompt is tuned to Singapore hawker and kopitiam dishes, and a typed dish name gives the model local context. Pace saves the meal description and supportive suggestion, not the image. The feature is a lightweight coaching aid and does not assess medical nutrition needs.

## Run locally

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Add your OpenAI and Google OAuth values to .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://localhost:8000/](http://localhost:8000/) or API docs at `/docs`. Use `localhost` consistently rather than mixing it with `127.0.0.1`, so the OAuth state and app session cookies are sent to the callback.

## Deploy to Vercel with Supabase

The Vercel entry point is configured as `app.main:app`. The app continues to use its own email/password accounts; Supabase is used as the PostgreSQL database, not as the authentication provider. Keep the Supabase connection string in server-side Vercel environment variables and never add it to browser JavaScript.

1. Create a Supabase project. In the Supabase dashboard, choose **Connect** and copy the **Transaction pooler** URI (port `6543`) for serverless use.
2. Import this repository into Vercel, keeping the repository root as the project root. Vercel detects FastAPI and uses the Python runtime.
3. Add these environment variables in Vercel (Production and Preview as appropriate):
   - `DATABASE_URL`: the Supabase transaction-pooler URI. Replace the password placeholder; the app adapts the URI for the psycopg driver and uses SSL.
   - `OPENAI_API_KEY` and any optional `OPENAI_MODEL` value.
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_TOKEN_ENCRYPTION_KEY`.
   - `PUBLIC_BASE_URL`: your stable production origin, such as `https://pace.example.com`.
   - `GOOGLE_REDIRECT_URI`: `https://pace.example.com/api/v1/google/callback`.
   - `COOKIE_SECURE=true` and `CRON_SECRET`: a long random secret, generated with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   - `APP_TIMEZONE=Asia/Singapore`.
4. In Google Cloud Console, add the production callback above as an authorized redirect URI and add the production site origin as an authorized JavaScript origin.
5. Deploy. On first startup, the app creates its SQLAlchemy tables in Supabase. Check the Vercel deployment logs and `/health` if startup fails.

Vercel Functions have a 4.5 MB request-body limit. The meal-photo form compresses photos larger than 3 MB before upload so the multipart request fits under that limit. The local SQLite `burnout.db` is not copied to Supabase automatically; this deployment starts with an empty cloud database unless you separately migrate existing data.

Vercel does not keep the app's 12-hour in-process loop alive. Its configured daily Cron calls a secret-protected Google Calendar maintenance route to refresh events and renew push channels; schedule opens and manual syncs also pull Google changes. The Cron route requires `CRON_SECRET` to match the Vercel environment variable.

## Configure Google Calendar OAuth

1. In Google Cloud Console, create/select a project, enable **Google Calendar API**, and configure the OAuth consent screen.
2. Create an OAuth client with application type **Web application**.
3. Add this exact authorized redirect URI: `http://localhost:8000/api/v1/google/callback`.
4. Put the client ID and secret in `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Add the OpenAI key separately as `OPENAI_API_KEY`.
5. Generate a Fernet key with `.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and set it as `GOOGLE_TOKEN_ENCRYPTION_KEY`. Keep this key stable and private; changing it makes stored Google tokens unreadable.
6. Restart Uvicorn. Create an app account with email/password, then click **Connect Google Calendar**. Google authorization is a separate OAuth grant and does not replace the app login.

If authorization succeeds but calendar sync returns HTTP 403 with `insufficientPermissions`, the token does not include the Calendar scope. Click **Connect Google Calendar** and explicitly approve the Calendar permission on Google's consent screen. If Google omits the permission again, confirm **Google Calendar API** is enabled in the same Cloud project as the OAuth client and, for an External consent screen in Testing mode, add the Google account as a test user. The app checks granted scopes and will show a reconnect prompt if Calendar access is missing.

The app requests OpenID/email identity and `calendar.events` access. Access and refresh tokens are encrypted at rest. The app stores its own password hash and HTTP-only session separately from the Google connection. Use HTTPS and set `COOKIE_SECURE=true` in production.

If your `.env` was created before these settings were added, copy the Google settings from `.env.example` into it. Keep `GOOGLE_REDIRECT_URI` exactly the same in `.env` and the Google Cloud OAuth client. The encryption key can be generated using the command above; it is different from both the Google client secret and the OpenAI API key.

## Sync behavior

- Opening **My schedule** and pressing **Sync Google Calendar** pulls incremental Google changes using Google's sync token.
- **Pace's four-week forecast** assigns 1.5 effort points per hour for academic/work events, 1.25 for classes, 0.5 for personal events, and zero for rest. Weekly labels are Light (<20), Balanced (20–<40), Busy (40–<60), and Very full (60+).
- The **planning signal** combines next-week workload (40%), the past three days' sleep deficit from a 7.5-hour target (30%), and the inverse of recent 1–5 mood/energy check-ins (30%). Missing check-in components are omitted and remaining weights are normalized. This is a planning aid, not a medical assessment.
- Each chatbot turn requests up to 40 current events from the connected Google primary calendar for the next 14 days, then passes only title, start/end, category, and all-day status to Balm as private context. If Google is not connected or temporarily unavailable, chat uses the app's local schedule snapshot instead.
- **Protected rest blocks** previews open two-hour windows between 09:00 and 21:00 during the next seven days on days with at least 8 effort points or when recent energy averages 2/5 or lower. A user must explicitly confirm before blocks are written to Google Calendar; existing blocks are skipped.
- APP_TIMEZONE controls forecast day boundaries and protected rest times (defaults to Asia/Singapore).
- App-created events are inserted into the primary Google calendar after connection; app edits and deletes update/delete the linked Google event.
- Google-created or Google-edited events are imported on sync. Google deletions are removed from the local schedule.
- For near-real-time Google-to-app updates, set `PUBLIC_BASE_URL` to a publicly reachable HTTPS deployment. The app registers Google push notification channels and validates their channel token; opening the schedule renews an expiring channel, and a background task renews channels and performs a recovery sync every 12 hours. The page also refreshes while open. Google requires a public HTTPS webhook, channels expire and must be renewed, and notifications can be dropped, so recovery sync remains enabled. Localhost cannot receive Google webhooks; local development syncs on schedule load, while open, or when the user presses Sync.
- Disconnecting stops the push channel when possible, revokes the Google grant, and removes stored tokens. Existing schedule entries remain as a local snapshot; disconnecting never deletes events from the user's Google Calendar.

## Main endpoints

- `POST /api/v1/auth/signup`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`
- `GET /api/v1/google/connect`, `GET /api/v1/google/callback`, `GET /api/v1/google/status`, `POST /api/v1/google/sync`, `DELETE /api/v1/google/disconnect`
- `POST /api/v1/students/{id}/calendar/events`, `GET .../calendar/events`, `PATCH/DELETE .../calendar/events/{event_id}`
- `PUT /api/v1/students/{id}/wellbeing`, `GET .../wellbeing`
- `POST /api/v1/students/{id}/nutrition/analyze-image`, `GET .../nutrition/logs`
- `POST /api/v1/students/{id}/chat`, `GET .../chat/history`

Calendar, chat, and wellbeing data routes require a signed-in app account that owns the requested student profile. This MVP is not ready for production student accounts without broader abuse controls, rate limits, account recovery, database migrations, and a privacy/security review.
