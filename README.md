# Google Forms MCP

Give an existing AI assistant the ability to preview and create native Google Forms. The assistant handles natural language; this server handles validation, explicit confirmation, Google OAuth, and deterministic Forms API calls.

## What works

- Native Google Form creation in the authenticated user's account
- Multi-section forms
- Short text, paragraph, multiple choice, checkboxes, dropdown, linear scale, date, and time questions
- Required questions and descriptions
- Preview-before-create safety boundary
- Minimal OAuth scope: `forms.body`
- MCP 2.x stdio transport
- Authenticated Streamable HTTP transport for Claude and ChatGPT connectors
- Companion skill in [`skill/google-forms/SKILL.md`](skill/google-forms/SKILL.md)

## Current MVP limits

Version 0.2 does not yet update existing forms, configure branching, create quizzes, upload files, change themes, or read responses. Google may create an empty form if the follow-up item population request fails; the tool reports the API error rather than pretending creation succeeded.

## Install

```bash
uv sync --extra dev
```

The MCP executable is then available at:

```text
<project>/.venv/bin/google-forms-mcp
```

## Google OAuth setup

1. Create or select a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Enable the **Google Forms API**.
3. Configure the OAuth consent screen.
4. Create an OAuth client with application type **Desktop app**.
5. Download the JSON file to:

   ```text
   ~/.config/google-forms-mcp/credentials.json
   ```

   Override the location with `GOOGLE_FORMS_CLIENT_SECRET` if needed.
6. Authorize once:

   ```bash
   uv run google-forms-auth
   ```

The refresh token is stored at `~/.config/google-forms-mcp/token.json` with owner-only permissions when the platform supports them. Override it with `GOOGLE_FORMS_TOKEN`.

## Connect an MCP client

### Hermes Agent

Use Hermes' MCP CLI rather than editing its configuration manually:

```bash
hermes mcp add google-forms \
  --command /absolute/path/to/google-forms-mcp/.venv/bin/google-forms-mcp

hermes mcp test google-forms
```

Restart the active Hermes agent after adding the server so its tools are discovered.

### Other stdio MCP clients

Configure the command as:

```json
{
  "command": "/absolute/path/to/google-forms-mcp/.venv/bin/google-forms-mcp",
  "args": []
}
```

The exact configuration file varies by client.

### Claude and ChatGPT remote connector

Run the authenticated HTTP entrypoint and publish it behind HTTPS:

```bash
GOOGLE_FORMS_CONNECTOR_TOKEN='<random-token>' \
GOOGLE_FORMS_CONNECTOR_PUBLIC_HOSTS='forms.example.com' \
uv run google-forms-connector
```

Connect Claude or ChatGPT to `https://your-domain.example/mcp` with the request header `Authorization: Bearer <random-token>`. The hosted connector currently represents one Google account. See [`docs/connectors.md`](docs/connectors.md) for deployment, platform setup, and security details.

## Tools

### `preview_google_form`

Validates a structured form specification and returns a normalized draft. It never authenticates or creates anything.

### `create_google_form`

Creates the form only when `confirm` is `true`. Agents should call `preview_google_form` first and display the draft to the user.

### `google_forms_auth_status`

Reports credential paths and whether the expected files exist. It does not expose token contents.

## Example request

Ask the connected assistant:

> Create a two-section retreat RSVP. In Basics, require name and email and ask whether the person is attending. In Logistics, ask for transportation as multiple choice and available days as checkboxes. Preview it before creating anything.

A valid tool payload looks like:

```json
{
  "spec": {
    "title": "Retreat RSVP",
    "description": "Please respond by Friday.",
    "sections": [
      {
        "title": "Basics",
        "questions": [
          {"title": "Name", "type": "short_text", "required": true},
          {"title": "Email", "type": "short_text", "required": true},
          {
            "title": "Will you attend?",
            "type": "multiple_choice",
            "options": ["Yes", "No"]
          }
        ]
      },
      {
        "title": "Logistics",
        "questions": [
          {
            "title": "Transportation",
            "type": "dropdown",
            "options": ["Driving", "Need a ride", "Public transit"]
          },
          {
            "title": "Available days",
            "type": "checkboxes",
            "options": ["Friday", "Saturday", "Sunday"]
          }
        ]
      }
    ]
  }
}
```

After the user approves the returned draft, the assistant calls `create_google_form` with the same `spec` and `"confirm": true`.

## Development

```bash
uv run pytest -q
uv run ruff check .
uv run mypy
```

The tests use in-memory fakes and never contact Google.

## Security

- Never commit `credentials.json` or `token.json`; both are ignored by Git.
- The server requests only the Forms body scope and does not read responses.
- Creation requires an explicit confirmation flag.
- For shared installations, run one server per Google account or isolate each account's token path.
