# Public multi-user product deployment

Version 0.4 supports a public beta in which each user connects a separate Google account and receives a private bearer token for remote MCP clients.

## Architecture

```text
User browser
  → Google Web OAuth (openid + email + forms.body)
  → encrypted Google credentials keyed by internal user ID
  → one-time MCP bearer token

Claude / ChatGPT / another HTTP MCP client
  → public HTTPS /mcp with that bearer token
  → token hash resolves one internal user
  → context-local tenant ID
  → that tenant's drafts, confirmation key, and Google credentials
  → that user's Google Forms
```

No MCP request accepts a user ID from tool arguments. Tenant identity comes only from the authenticated bearer token.

## Google Cloud configuration

1. Use a production-controlled HTTPS hostname. Do not use a temporary Quick Tunnel for the final consent screen.
2. In Google Cloud project settings, enable the Google Forms API.
3. Configure the OAuth consent screen with:
   - Application name and support email
   - Authorized domain
   - Privacy-policy URL
   - Terms-of-service URL
4. Add scopes:
   - `openid`
   - `email`
   - `https://www.googleapis.com/auth/forms.body`
5. Create an OAuth client with application type **Web application**.
6. Add the exact redirect URI:

   ```text
   https://YOUR_DOMAIN/oauth/google/callback
   ```

7. Download the client JSON and store it outside the repository with owner-only permissions.
8. Keep the app in Testing with explicit test users until Google verification and legal pages are ready. Testing refresh tokens may expire or have restricted audiences.

A Desktop-app client cannot be reused for this flow.

## Required environment

```bash
GOOGLE_FORMS_MULTIUSER=true
GOOGLE_FORMS_PUBLIC_BASE_URL=https://YOUR_DOMAIN
GOOGLE_FORMS_WEB_CLIENT_SECRET=/run/secrets/google-web-client.json
GOOGLE_FORMS_MULTIUSER_DATA_DIR=/var/lib/google-forms-mcp
GOOGLE_FORMS_CONNECTOR_HOST=0.0.0.0
GOOGLE_FORMS_CONNECTOR_PUBLIC_HOSTS=YOUR_DOMAIN
GOOGLE_FORMS_RATE_LIMIT_PER_MINUTE=60
GOOGLE_FORMS_PUBLIC_RATE_LIMIT_PER_MINUTE=10
GOOGLE_FORMS_PUBLIC_GLOBAL_RATE_LIMIT_PER_MINUTE=120
GOOGLE_FORMS_TRUST_PROXY_HEADERS=true
PORT=8000
```

Optional explicit paths:

```bash
GOOGLE_FORMS_USERS_DB=/var/lib/google-forms-mcp/users.db
GOOGLE_FORMS_MASTER_KEY=/run/secrets/google-forms-master.key
```

Back up the master key separately from the encrypted database. Losing the key makes stored Google credentials unrecoverable. Exposing it compromises every connected Google credential.

## User onboarding

1. User opens `https://YOUR_DOMAIN/`.
2. User selects **Connect Google Forms**.
3. Google authenticates the user and displays the requested scopes.
4. The callback validates one-use state and PKCE.
5. The service encrypts the Google credential and issues a `gfm_...` token.
6. The token is displayed once. Only its SHA-256 hash is stored.
7. The user configures their AI app with:
   - MCP URL: `https://YOUR_DOMAIN/mcp`
   - Authorization header: `Bearer <their gfm token>`

The public beta works with remote-MCP clients that accept a user-supplied bearer token or fixed Authorization header. Full automatic MCP OAuth discovery/DCR/CIMD is a separate interoperability layer and is not claimed by version 0.4.

## Supported client patterns

- Claude API MCP connector: supply the token through `authorization_token`.
- Claude custom connector: add the token as a fixed Authorization request header.
- ChatGPT custom MCP/plugin: choose bearer authentication and enter the token when the workspace UI supports custom authentication details.
- Hermes or another MCP client: configure the remote Streamable HTTP URL and Authorization header.

Plan availability and UI labels vary by client. Test each target client before advertising it as supported.

## Revocation

Authenticated users can call:

```text
POST /disconnect
Authorization: Bearer <their token>
```

This attempts provider-side Google revocation, then removes the locally stored Google credential and revokes every service token for that user. The response reports whether Google confirmed provider revocation; local disconnection still completes if Google is temporarily unreachable.

## Data and privacy contract

Stored:

- Google stable subject identifier
- Email address
- Encrypted Google OAuth credential
- Hashes and labels for MCP tokens
- Per-user form draft specifications and revision history
- Minimal audit events: connection, token lifecycle, draft mutation, publication, and update identifiers

Not stored in audit logs:

- Plaintext MCP tokens
- OAuth access or refresh tokens
- Form responses
- Prompt or conversation contents
- Question text or option values

The form drafts themselves may contain sensitive planned questions. Encrypting Google credentials does not encrypt SQLite draft content. Production deployments should use encrypted volumes, backups with access controls, documented retention, and account-deletion procedures.

## Operational controls

- Per-user authenticated request limits default to 60 requests per minute across all of that user's tokens.
- Unauthenticated onboarding and callback requests have both per-IP and global limits. Proxy-provided client IP headers are trusted only when `GOOGLE_FORMS_TRUST_PROXY_HEADERS=true`; enable it only behind a proxy such as Cloudflare that overwrites those headers.
- Invalid/revoked tokens return `401`.
- Exceeded limits return `429` with `Retry-After`.
- Each tenant uses a separate drafts database and confirmation-signing key.
- Google edits require signed review plans and Google revision control.
- The server never trusts a tool-supplied tenant identifier.

## Production release gates

Before opening signups:

- Stable domain and named tunnel/reverse proxy
- TLS and HSTS
- Google Web OAuth client and verified redirect
- Published privacy policy and terms
- Google OAuth app verification where required
- Provider-side token revocation
- Database/master-key backups and restore test
- Abuse monitoring and global/IP limits in addition to per-token limits
- User-facing token list, token rotation, account deletion, and audit export
- Independent penetration/security review
- Successful end-to-end login from every advertised MCP client
