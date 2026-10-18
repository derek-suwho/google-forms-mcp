---
name: google-forms
description: Preview and create native Google Forms safely.
version: 0.1.0
author: Derek Su, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [google-forms, mcp, productivity]
    related_skills: []
---

# Google Forms Skill

Use the connected Google Forms MCP tools to turn a user's intent into a validated native Google Form. This skill governs form design and confirmation; the MCP server owns OAuth and API execution.

## When to Use

- The user asks to create a survey, RSVP, application, intake form, or questionnaire in Google Forms.
- The user wants an editable Google Form link rather than a prose list of questions.
- Do not use for quizzes, file uploads, branching, response analysis, or editing an existing form in version 0.1.

## Prerequisites

- The `google-forms` MCP server is connected.
- `google_forms_auth_status` reports both the OAuth client and token files exist before creation.
- The user has explicitly approved a preview before any mutating call.

## Procedure

1. Extract the form's audience, outcome, deadline, and required information from the request. Ask a clarification question only when an unanswered choice materially changes the form.
2. Choose the narrowest suitable question type:
   - `short_text` for names and concise identifiers.
   - `paragraph` for explanations.
   - `multiple_choice` for exactly one visible choice.
   - `dropdown` for exactly one choice from a longer list.
   - `checkboxes` for any number of choices.
   - `linear_scale` for ratings with bounds from 0 through 10.
   - `date` or `time` for structured calendar inputs.
3. Write neutral, specific questions. Do not invent privacy promises, consent language, deadlines, or organizational policies.
4. Group related questions into sections. Keep required fields limited to information necessary for the stated outcome.
5. Call `preview_google_form` with the complete specification.
6. Present the title, sections, questions, required fields, and options in a concise review. Do not call the creation tool in the same step.
7. After explicit approval, call `create_google_form` with the identical reviewed specification and `confirm=true`.
8. Return both the edit URL and responder URL. State the actual tool result; never invent a link after an error.

## Form Specification

Top level:

- `title`: non-empty string.
- `description`: optional string.
- `sections`: one or more section objects.

Each section has `title`, optional `description`, and one or more `questions`.

Every question has `title`, `type`, optional `description`, and optional `required`. Choice questions also require at least two unique `options`. Linear-scale questions may include `lower_bound`, `upper_bound`, `low_label`, and `high_label`.

## Pitfalls

- A skill cannot create the form by itself; use the MCP tool.
- Never skip preview because the user said “just make it.” Creation remains a two-step operation.
- Do not encode checkbox choices when only one answer should be allowed.
- Do not request sensitive data unless the user clearly requires it and understands the collection purpose.
- Version 0.1 has no conditional branching. Explain the limitation rather than flattening a flow that depends on branching.

## Verification

A successful run has all of the following:

- The preview validated without errors.
- The user explicitly approved that preview.
- The creation result has `status: created`.
- Both `edit_url` and `responder_url` are present.
- The reported question and section counts match the approved draft.
