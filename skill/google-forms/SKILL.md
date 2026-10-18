---
name: google-forms
description: Create and refine native Google Forms safely.
version: 0.3.0
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
- The user asks to change one part of a draft or existing form without regenerating it.
- Do not use for quizzes, file uploads, branching, or response analysis in version 0.3.

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
5. Call `create_form_draft` with the complete specification. Keep the returned `draft_id` for every follow-up.
6. Present the title, sections, questions, required fields, and options in a concise review.
7. For a requested change, call `patch_form_draft` with only the explicit operations needed. Show the returned change list and new version; do not regenerate the specification.
8. If the user rejects the latest edit, call `undo_draft_change`. If they request another change, patch the current version.
9. After explicit approval, call `publish_form_draft` with the draft ID, the exact reviewed `expected_version`, and `confirm=true`.
10. For later changes to the published form, first call `update_existing_google_form` with `confirm=false`. Show the returned canonical operations and `revision_id`; after approval, call it with the returned signed `plan_token` and `confirm=true`. Do not reconstruct or substitute operations during confirmation.
11. Return both the edit URL and responder URL after publication. State the actual tool result; never invent a link after an error.

## Form Specification

Top level:

- `title`: non-empty string.
- `description`: optional string.
- `sections`: one or more section objects.

Each section has `title`, optional `description`, and one or more `questions`.

Every question has `title`, `type`, optional `description`, and optional `required`. Choice questions also require at least two unique `options`. Linear-scale questions may include `lower_bound`, `upper_bound`, `low_label`, and `high_label`.

## Patch Operations

Use the smallest applicable operation: `set_form_title`, `set_form_description`, `rename_section`, `add_question`, `delete_question`, `rename_question`, `set_question_description`, `set_required`, `add_option`, or `remove_option`.

Question and section titles are patch selectors and must identify exactly one item. Never send the whole form through a patch tool. Keep unrelated content out of the operation payload so the server can guarantee it remains unchanged.

## Pitfalls

- A skill cannot create the form by itself; use the MCP tool.
- Never skip review because the user said “just make it.” Publication and existing-form updates require explicit confirmation.
- Do not replace a draft to satisfy a narrow edit; use patch operations and show the change list.
- Draft question and section titles must be unique because they are human-readable patch selectors.
- Once published, a draft is immutable; route later changes through the revision-guarded existing-form update tool.
- Do not encode checkbox choices when only one answer should be allowed.
- Do not request sensitive data unless the user clearly requires it and understands the collection purpose.
- Version 0.3 has no conditional branching. Explain the limitation rather than flattening a flow that depends on branching.

## Verification

A successful run has all of the following:

- The draft validated and has a stable `draft_id` and version.
- Every conversational edit returned an exact `changes` list while unrelated fields remained unchanged.
- The user explicitly approved the current version or existing-form operation list.
- Publication returned `status: published`, or an existing-form update returned `status: updated`.
- Both `edit_url` and `responder_url` are present after publication.
- The reported question and section counts match the approved draft.
