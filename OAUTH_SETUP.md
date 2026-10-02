# GitHub and Google sign-in

The backend implements both providers. Real sign-in requires OAuth clients registered with the providers. No client ID or secret was configured when this feature was built. Google login authenticates identity; it does not authorize GitHub repositories. GitHub login currently requests read:user only. Repository onboarding retains its separate server-side GitHub App/local CLI connection.

## 1. Set the application origin

For this Mac:

RESCUE_PUBLIC_URL=http://127.0.0.1:8093

For cloud deployment, use the public HTTPS origin of the backend serving the frontend and /auth routes. The current static Vercel site cannot host this persistent backend. Do not register Vercel callback URLs until an authenticated backend/gateway actually serves them. Use the same origin when opening the app as the one configured here; localhost and 127.0.0.1 are different cookie origins.

## 2. GitHub

Register an OAuth App at https://github.com/settings/developers . For local development:

Homepage URL: http://127.0.0.1:8093
Authorization callback URL: http://127.0.0.1:8093/auth/github/callback

Set these values in the ignored, private .env file:

RESCUE_GITHUB_OAUTH_CLIENT_ID=<client ID>
RESCUE_GITHUB_OAUTH_CLIENT_SECRET=<client secret>

The application uses authorization code + S256 PKCE and read:user scope. It obtains the immutable GitHub user ID from /user. It discards the provider access token after identity verification. It does not request the broad repo scope or reuse your login token for repository execution.

## 3. Google

In https://console.cloud.google.com/auth/clients create an OAuth client of type Web application. Configure the consent screen and test users if the application is in Testing status.

Authorized redirect URI: http://127.0.0.1:8093/auth/google/callback

RESCUE_GOOGLE_OAUTH_CLIENT_ID=<client ID>
RESCUE_GOOGLE_OAUTH_CLIENT_SECRET=<client secret>

Google uses authorization code + PKCE, openid/email/profile scopes and a nonce. ID tokens are verified against Google's signing keys, issuer, audience, expiry and nonce; the email must be verified. No Google access/refresh token is retained.

## 4. Approve workspace accounts

The application is a single-organization workspace containing private repair evidence. Successful provider authentication alone does not grant access. Administrators must assign roles in RESCUE_OAUTH_ROLES (JSON). For example:

RESCUE_OAUTH_ROLES={"github-login:niteshnankani-svg":["viewer","operator","reviewer"],"google-email:you@example.com":["viewer","operator"]}

Prefer immutable identities for long-term access: github:<numeric user ID> and google:<sub>. Login-name/email aliases are setup conveniences and must be reviewed if an account changes its name/email. Viewer can inspect workspace evidence, operator can prepare/start repairs, reviewer can approve/export. Never grant reviewer to every person who can sign in.

Use scripts/configure_oauth.py to enter values using hidden secret input. Restart the backend after configuration. Enabling OAuth disables the automatic loopback development login. Organization service-key access remains available if configured.

## Security and deployment

OAuth state is random, hashed, browser-bound, expires after 10 minutes, and is consumed atomically once. PKCE verifiers/nonces stay in private server storage. The temporary state cookie uses SameSite=Lax to support the provider redirect; the final session cookie is HttpOnly, SameSite=Strict and Secure over HTTPS. Opaque session tokens are stored as hashes, expire after one hour, and are revoked on logout. Role revocation is checked on every request. No provider token or client secret goes into browser storage, URLs, model inputs, source snapshots, or Git.

Keep runtime/oauth.sqlite on private storage. The backup script excludes login sessions and pending OAuth exchanges; users sign in again after a restore. Run a single API process (as required by the existing SQLite/worker design). Configure proxy access logs to omit /auth callback query strings. Start Uvicorn with --no-access-log so authorization codes are not logged. Keep RESCUE_ALLOWED_HOSTS explicit and serve HTTPS in production. The reverse proxy must preserve the established Origin/Host CSRF policy.

Verification uses mocked provider exchanges and real signed Google ID tokens in tests. A live provider sign-in cannot be verified until administrator credentials and approved accounts are configured.

Official references:
https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
https://developers.google.com/identity/openid-connect/openid-connect
