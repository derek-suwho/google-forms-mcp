# Claude and ChatGPT connector

The same tools can run as a remote **Streamable HTTP MCP server**, which Claude and ChatGPT can connect to over HTTPS.

## Architecture and scope

This release is a **personal, single-Google-account connector**:

```text
Claude or ChatGPT
  → HTTPS /mcp + connector bearer token
  → Google Forms MCP server
  → one stored Google OAuth refresh token
  → that Google account's Forms
```

The connector bearer token authenticates Claude or ChatGPT to this server. The Google OAuth token separately authorizes this server to create forms in one Google account. Do not share one deployment with users who should not share access to that Google account.

A public multi-user connector requires per-user OAuth sessions, encrypted token storage, account disconnect/revocation, and an MCP-compatible OAuth authorization server. Those are intentionally outside version 0.2.

## 1. Authorize the Google account

Follow the root README to create a Google Desktop OAuth client, then run:

```bash
uv run google-forms-auth
```

This produces the token used by the hosted connector. Keep both OAuth files outside Git.

## 2. Generate connector authentication

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Store the result in `GOOGLE_FORMS_CONNECTOR_TOKEN`. Use a secret manager in production; never put it in a deployment manifest or repository.

## 3. Run locally

```bash
GOOGLE_FORMS_CONNECTOR_TOKEN='<random-token>' \
GOOGLE_FORMS_CLIENT_SECRET="$HOME/.config/google-forms-mcp/credentials.json" \
GOOGLE_FORMS_TOKEN="$HOME/.config/google-forms-mcp/token.json" \
uv run google-forms-connector
```

Endpoints:

- MCP: `http://127.0.0.1:8000/mcp`
- Health: `http://127.0.0.1:8000/health`

The MCP endpoint rejects missing or incorrect bearer tokens. The health endpoint is intentionally public and returns no credential details.

## 4. Deploy behind HTTPS

Claude and ChatGPT connect from their cloud infrastructure, so `localhost`, private LAN addresses, and a laptop-only server are insufficient. Publish `/mcp` at a stable HTTPS URL such as:

```text
https://forms.example.com/mcp
```

The included Dockerfile runs the connector on `PORT` and expects these secrets or mounted files:

- `GOOGLE_FORMS_CONNECTOR_TOKEN`
- `GOOGLE_FORMS_CLIENT_SECRET`
- `GOOGLE_FORMS_TOKEN`

Example container invocation:

```bash
docker build -t google-forms-connector .

docker run --rm -p 8000:8000 \
  -e GOOGLE_FORMS_CONNECTOR_TOKEN='<random-token>' \
  -e GOOGLE_FORMS_CLIENT_SECRET=/run/secrets/google-client.json \
  -e GOOGLE_FORMS_TOKEN=/run/secrets/google-token.json \
  -v "$HOME/.config/google-forms-mcp/credentials.json:/run/secrets/google-client.json:ro" \
  -v "$HOME/.config/google-forms-mcp/token.json:/run/secrets/google-token.json" \
  google-forms-connector
```

Terminate TLS in a reverse proxy or deployment platform. Do not expose plain HTTP to the public internet.

## 5. Add it to Claude

1. Open **Customize → Connectors**.
2. Choose **Add custom connector**.
3. Enter the HTTPS MCP URL ending in `/mcp`.
4. Choose fixed request-header authentication rather than OAuth.
5. Add this request header:

   ```text
   Authorization: Bearer <GOOGLE_FORMS_CONNECTOR_TOKEN>
   ```

6. Connect it, enable it in a conversation, and ask Claude to call `google_forms_auth_status`.

On Team or Enterprise plans, an owner may need to add the connector for the organization first.

## 6. Add it to ChatGPT

1. Open **Plugins** and choose **Add custom MCP server**.
2. Enter the HTTPS MCP URL ending in `/mcp`.
3. Configure bearer authentication with the connector token:

   ```text
   Authorization: Bearer <GOOGLE_FORMS_CONNECTOR_TOKEN>
   ```

4. Keep approval enabled for `create_google_form`, because it writes to Google Drive.
5. Install the plugin and test `google_forms_auth_status`, then `preview_google_form`.

Workspace availability and the names of settings may vary by ChatGPT plan. The required protocol endpoint remains Streamable HTTP MCP at `/mcp`.

## Verification prompt

Use this before creating anything:

> Preview a Google Form called Connector Test with one section called Basics. Add a required short-text Name question and an Attending multiple-choice question with Yes and No. Do not create it.

Expected result:

- Tool: `preview_google_form`
- Status: `draft`
- Sections: `1`
- Questions: `2`

Then explicitly approve creation and verify that the result contains both `edit_url` and `responder_url`.

## Security notes

- Rotate the connector token if it appears in logs, chat, shell history, or screenshots.
- Do not configure the hosted connector with `No sign in` unless another trusted gateway enforces authentication.
- Keep tool approval enabled for writes even though the MCP tool also requires `confirm=true`.
- The bearer token protects access to the connector; it does not create user-specific Google permissions.
- Use separate deployments and Google tokens for accounts that must remain isolated.
