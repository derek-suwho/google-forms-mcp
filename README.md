# Google Forms MCP

Give an existing AI assistant the ability to create, refine, publish, and update native Google Forms. The assistant handles natural language; this server maintains versioned drafts, applies explicit patches, enforces confirmation, and performs deterministic Forms API calls.

## What works

- Native Google Form creation in the authenticated user's account
- Multi-section forms
- Short text, paragraph, multiple choice, checkboxes, dropdown, linear scale, date, and time questions
- Required questions and descriptions
- Persistent SQLite drafts with version numbers and undo
- Targeted patches that preserve unrelated questions and settings
- Direct targeted updates to existing native Google Forms
- Preview-before-publish and confirmation safety boundaries
- Minimal OAuth scope: `forms.body`
- MCP 2.x stdio transport
- Authenticated Streamable HTTP transport for Claude and ChatGPT connectors
- Companion skill in [`skill/google-forms/SKILL.md`](skill/google-forms/SKILL.md)

## Current MVP limits

Version 0.3 does not yet configure conditional branching, create quizzes, upload files, change themes, read responses, or provide per-user OAuth. Google may create an empty form if the follow-up item population request fails; the tool reports the API error rather than pretending creation succeeded.

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

Connect Claude or ChatGPT to `https://your-domain.example/mcp` and configure the `Authorization` request header with the connector bearer token. The hosted connector currently represents one Google account. See [`docs/connectors.md`](docs/connectors.md) for deployment, platform setup, and security details.

## Tools

### `preview_google_form`

Validates a structured form specification and returns a normalized draft. It never authenticates or creates anything.

### `create_form_draft`

Saves a validated draft at version 1 without contacting Google.

### `get_form_draft`

Returns the current version, normalized specification, publication state, and summary.

### `patch_form_draft`

Applies only the requested operations and creates a new version. Supported operations include form titles/descriptions, section renames, adding/deleting/renaming questions, question descriptions, required flags, and adding/removing choice options.

### `undo_draft_change`

Moves the draft back one version. A subsequent patch creates a new history branch and discards the abandoned future revisions.

### `publish_form_draft`

Creates and publishes the native Google Form from the reviewed draft only when `confirm=true` and `expected_version` matches the reviewed version, then records the resulting form ID on the draft. Published drafts become immutable; further changes use the existing-form update tool.

### `update_existing_google_form`

Previews or applies explicit patch operations to a published native Google Form. The preview returns the current Google `revision_id`, exact operations, and a signed `plan_token`. The confirmed call executes the immutable signed plan and fails closed if either the plan is altered or Google changed after review.

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

The assistant saves this with `create_form_draft`. A targeted follow-up such as “remove Public transit and make Transportation required” becomes:

```json
{
  "draft_id": "<draft-id>",
  "operations": [
    {
      "operation": "remove_option",
      "question_title": "Transportation",
      "option": "Public transit"
    },
    {
      "operation": "set_required",
      "question_title": "Transportation",
      "required": true
    }
  ]
}
```

`patch_form_draft` returns the exact change list and version 2 while every unrelated field remains unchanged. After approval, the assistant calls `publish_form_draft` with the draft ID, `expected_version: 2`, and `confirm: true`.

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
- Draft databases, SQLite sidecars, and confirmation keys are restricted to owner read/write permissions where supported.
- Creation, publication, and existing-form updates require explicit confirmation tied to reviewed versions or signed plans.
- If Google allocates a form but later setup fails, the form ID is retained and automatic retries are blocked to avoid duplicate forms.
- For shared installations, run one server per Google account or isolate each account's token path.
