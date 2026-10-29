# Build-team handoff: Google Forms MCP

Updated: 2026-10-29

## Product

A public, multi-user MCP service that lets Claude, ChatGPT, and other MCP clients create and edit native Google Forms in each user's own Google account. Mutations use preview/confirmation rather than silently publishing forms.

## Source and deployment

- Repository: https://github.com/derek-suwho/google-forms-mcp
- Branch: `main`
- Current deployed commit: `5c41bbf`
- Stable URL: https://google-forms-mcp.srv1913479.hstgr.cloud
- MCP endpoint: `https://google-forms-mcp.srv1913479.hstgr.cloud/mcp`
- Health endpoint: `https://google-forms-mcp.srv1913479.hstgr.cloud/health`
- Host: Hostinger VPS Docker Manager, application `google-forms-mcp`
- Container: public GHCR image pinned by immutable digest in `deploy/hostinger-compose.yml`
- CI: `.github/workflows/container.yml`

## Verified working

- Stable deployment and valid TLS
- `/`, `/health`, `/privacy`, and `/terms` return 200
- Unauthenticated `/mcp` returns 401
- `/connect/google` redirects to Google with PKCE S256
- Tenant-isolated encrypted Google credentials
- Hashed per-user MCP bearer tokens
- Tenant-scoped drafts and confirmation keys
- Browser-bound, atomic one-use OAuth state
- Per-user, per-IP, and global rate limits
- Provider-side revocation attempt on disconnect
- Audit events without form contents or secrets
- 55 tests, Ruff, strict mypy, package build, image build, and container smoke test passed
- Latest CI: https://github.com/derek-suwho/google-forms-mcp/actions/runs/39181586815

## Current blocker

The deployed OAuth Web client belongs to the existing **Hermes Agent** Google Cloud project. Accounts with prior Hermes authorization return an inherited `gmail.readonly` scope in Google's callback. The service correctly rejects this unexpected scope and logs:

```text
Google OAuth callback failed: Warning
```

Do not weaken scope validation and do not revoke Hermes Agent's existing grants.

## Required next step

Create a dedicated Google Cloud project named **Google Forms MCP**:

1. Enable the Google Forms API.
2. Configure Google Auth Platform:
   - Audience: External
   - Publishing status: Testing initially
   - Add Derek's chosen Google account as a test user
   - App name: Google Forms MCP
3. Configure only these scopes:
   - `openid`
   - `email`
   - `https://www.googleapis.com/auth/forms.body`
4. Create a **Web application** OAuth client with this exact redirect URI:
   - `https://google-forms-mcp.srv1913479.hstgr.cloud/oauth/google/callback`
5. Rotate the old OAuth credential because its client secret was pasted into Discord. Do not reuse it.
6. In Hostinger Docker Manager, update only these environment values:
   - `GOOGLE_FORMS_WEB_CLIENT_ID`
   - `GOOGLE_FORMS_WEB_CLIENT_SECRET_VALUE`
   - `GOOGLE_FORMS_GOOGLE_PROJECT_ID`
7. Redeploy without deleting the `google-forms-mcp-data` volume.
8. Run a new OAuth flow from `/connect/google` in one uninterrupted browser session.

Never place OAuth secrets, `gfm_` bearer tokens, master keys, databases, or user credentials in Git, Discord, screenshots, or logs.

## Release verification

After switching projects:

1. `GET /health` returns `{"status":"ok","transport":"streamable-http","mode":"multiuser"}`.
2. `/connect/google` requests only `openid email forms.body` and redirects to the stable callback.
3. Google consent succeeds and displays a one-time `gfm_` token.
4. Save the token privately; never post it.
5. Connect an MCP client to the stable `/mcp` endpoint with `Authorization: Bearer <token>`.
6. Call auth status and verify the tenant is Google-authorized.
7. Preview a synthetic test form.
8. Confirm and create the native Google Form.
9. Verify it appears in the authorized user's Google account.
10. Exercise disconnect/revocation and verify the token stops working.

## Known production gaps

- Current remote-client authentication uses product-issued bearer tokens. It does not yet implement full MCP OAuth authorization-server metadata, dynamic client registration, or CIMD.
- SQLite and in-process rate limiting target a single-instance public beta, not horizontal scaling.
- Google production publishing may require domain ownership, polished legal pages, and Google OAuth verification.
- Back up the Docker data volume and its generated encryption master key together.

## Important files

- `src/google_forms_mcp/http_server.py` — public routes, tenant auth, limits, OAuth callback
- `src/google_forms_mcp/web_oauth.py` — Google Web OAuth and least-privilege scope handling
- `src/google_forms_mcp/multiuser.py` — encrypted credentials, hashed tokens, OAuth state, audit store
- `src/google_forms_mcp/multitenancy.py` — tenant credential/runtime integration
- `src/google_forms_mcp/server.py` — MCP tools, confirmation flow, tenant-aware operations
- `deploy/hostinger-compose.yml` — Hostinger production Compose configuration
- `deploy/README.md` — deployment instructions
- `docs/public-product.md` — architecture and production limitations
