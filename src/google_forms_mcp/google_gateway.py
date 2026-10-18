from __future__ import annotations

from copy import deepcopy
from typing import Any

from google_forms_mcp.compiler import (
    compile_create_body,
    compile_item_requests,
    compile_question_item,
)
from google_forms_mcp.models import FormSpec
from google_forms_mcp.patches import (
    AddOption,
    AddQuestion,
    DeleteQuestion,
    PatchOperation,
    PatchTargetError,
    RemoveOption,
    RenameQuestion,
    RenameSection,
    SetFormDescription,
    SetFormTitle,
    SetQuestionDescription,
    SetRequired,
)


class FormCreationError(RuntimeError):
    """Raised when Google form creation fails, possibly after allocating a form ID."""

    def __init__(self, message: str, *, form_id: str | None, stage: str) -> None:
        super().__init__(message)
        self.form_id = form_id
        self.stage = stage


class FormRevisionConflict(RuntimeError):
    """Raised when Google changed after the user reviewed an update plan."""


class GoogleFormsGateway:
    """Thin adapter around the generated Google Forms API client."""

    def __init__(self, google_service: Any) -> None:
        self._google = google_service

    def create_form(self, spec: FormSpec) -> dict[str, Any]:
        resource = self._google.forms()
        try:
            created = resource.create(body=compile_create_body(spec)).execute()
        except Exception as exc:
            raise FormCreationError(
                "Google failed before allocating a form ID",
                form_id=None,
                stage="create",
            ) from exc
        form_id = str(created["formId"])

        requests: list[dict[str, Any]] = []
        if spec.description:
            requests.append(
                {
                    "updateFormInfo": {
                        "info": {"description": spec.description},
                        "updateMask": "description",
                    }
                }
            )
        requests.extend(compile_item_requests(spec))

        try:
            resource.batchUpdate(
                formId=form_id,
                body={"includeFormInResponse": True, "requests": requests},
            ).execute()
        except Exception as exc:
            raise FormCreationError(
                f"Google allocated form {form_id}, but population failed",
                form_id=form_id,
                stage="populate",
            ) from exc
        try:
            resource.setPublishSettings(
                formId=form_id,
                body={
                    "publishSettings": {
                        "publishState": {
                            "isPublished": True,
                            "isAcceptingResponses": True,
                        }
                    },
                    "updateMask": "publishState",
                },
            ).execute()
        except Exception as exc:
            raise FormCreationError(
                f"Google allocated and populated form {form_id}, but publication failed",
                form_id=form_id,
                stage="publish",
            ) from exc

        return {
            "formId": form_id,
            "editUri": f"https://docs.google.com/forms/d/{form_id}/edit",
            "responderUri": created["responderUri"],
        }

    @staticmethod
    def _find_question(items: list[dict[str, Any]], title: str) -> tuple[int, dict[str, Any]]:
        matches = [
            (index, item)
            for index, item in enumerate(items)
            if "questionItem" in item and item.get("title") == title
        ]
        if not matches:
            raise PatchTargetError(f"Question not found: {title}")
        if len(matches) > 1:
            raise PatchTargetError(f"Question title is ambiguous: {title}")
        return matches[0]

    @staticmethod
    def _find_section(items: list[dict[str, Any]], title: str) -> tuple[int, dict[str, Any]]:
        matches = [
            (index, item)
            for index, item in enumerate(items)
            if "pageBreakItem" in item and item.get("title") == title
        ]
        if not matches:
            raise PatchTargetError(f"Section not found: {title}")
        if len(matches) > 1:
            raise PatchTargetError(f"Section title is ambiguous: {title}")
        return matches[0]

    @staticmethod
    def _update_item_request(item: dict[str, Any], index: int, update_mask: str) -> dict[str, Any]:
        return {
            "updateItem": {
                "item": deepcopy(item),
                "location": {"index": index},
                "updateMask": update_mask,
            }
        }

    def get_form_revision(self, form_id: str) -> str:
        form = self._google.forms().get(formId=form_id).execute()
        revision_id = form.get("revisionId")
        if not revision_id:
            raise FormRevisionConflict(f"Google did not return a revision ID for form {form_id}")
        return str(revision_id)

    def patch_form(
        self,
        form_id: str,
        operations: list[PatchOperation],
        *,
        expected_revision_id: str,
    ) -> dict[str, Any]:
        """Apply explicit, minimal updates to an existing native Google Form."""
        if not operations:
            raise PatchTargetError("At least one patch operation is required")
        resource = self._google.forms()
        form = resource.get(formId=form_id).execute()
        current_revision = str(form.get("revisionId", ""))
        if current_revision != expected_revision_id:
            raise FormRevisionConflict(
                f"Form {form_id} expected revision {expected_revision_id}, "
                f"but current revision is {current_revision or 'missing'}"
            )
        items: list[dict[str, Any]] = deepcopy(form.get("items", []))
        requests: list[dict[str, Any]] = []

        for operation in operations:
            if isinstance(operation, SetFormTitle):
                requests.append(
                    {
                        "updateFormInfo": {
                            "info": {"title": operation.new_title.strip()},
                            "updateMask": "title",
                        }
                    }
                )
                form.setdefault("info", {})["title"] = operation.new_title.strip()
                continue

            if isinstance(operation, SetFormDescription):
                requests.append(
                    {
                        "updateFormInfo": {
                            "info": {"description": operation.description.strip()},
                            "updateMask": "description",
                        }
                    }
                )
                form.setdefault("info", {})["description"] = operation.description.strip()
                continue

            if isinstance(operation, RenameSection):
                index, item = self._find_section(items, operation.section_title)
                item["title"] = operation.new_title.strip()
                requests.append(self._update_item_request(item, index, "title"))
                continue

            if isinstance(operation, AddQuestion):
                section_index, _ = self._find_section(items, operation.section_title)
                insert_at = section_index + 1
                while insert_at < len(items) and "pageBreakItem" not in items[insert_at]:
                    insert_at += 1
                if any(
                    item.get("title") == operation.question.title and "questionItem" in item
                    for item in items
                ):
                    raise PatchTargetError(
                        f"Question title already exists: {operation.question.title}"
                    )
                item = compile_question_item(operation.question)
                requests.append(
                    {"createItem": {"item": deepcopy(item), "location": {"index": insert_at}}}
                )
                items.insert(insert_at, item)
                continue

            index, item = self._find_question(items, operation.question_title)
            question = item["questionItem"]["question"]

            if isinstance(operation, SetRequired):
                question["required"] = operation.required
                requests.append(
                    self._update_item_request(item, index, "questionItem.question.required")
                )
            elif isinstance(operation, AddOption):
                choice = question.get("choiceQuestion")
                if choice is None:
                    raise PatchTargetError(
                        f"Question does not accept options: {operation.question_title}"
                    )
                option = operation.option.strip()
                values = [entry.get("value") for entry in choice.get("options", [])]
                if option in values:
                    raise PatchTargetError(
                        f"Option already exists for {operation.question_title}: {option}"
                    )
                choice.setdefault("options", []).append({"value": option})
                requests.append(
                    self._update_item_request(
                        item, index, "questionItem.question.choiceQuestion.options"
                    )
                )
            elif isinstance(operation, RemoveOption):
                choice = question.get("choiceQuestion")
                if choice is None:
                    raise PatchTargetError(
                        f"Question does not accept options: {operation.question_title}"
                    )
                option = operation.option.strip()
                options = choice.get("options", [])
                matches = [entry for entry in options if entry.get("value") == option]
                if not matches:
                    raise PatchTargetError(
                        f"Option not found for {operation.question_title}: {option}"
                    )
                if len(options) <= 2:
                    raise PatchTargetError("Choice questions must retain at least two options")
                choice["options"] = [entry for entry in options if entry.get("value") != option]
                requests.append(
                    self._update_item_request(
                        item, index, "questionItem.question.choiceQuestion.options"
                    )
                )
            elif isinstance(operation, RenameQuestion):
                new_title = operation.new_title.strip()
                if any(
                    candidate.get("title") == new_title
                    and "questionItem" in candidate
                    and candidate is not item
                    for candidate in items
                ):
                    raise PatchTargetError(f"Question title already exists: {new_title}")
                item["title"] = new_title
                requests.append(self._update_item_request(item, index, "title"))
            elif isinstance(operation, SetQuestionDescription):
                item["description"] = operation.description.strip()
                requests.append(self._update_item_request(item, index, "description"))
            elif isinstance(operation, DeleteQuestion):
                requests.append({"deleteItem": {"location": {"index": index}}})
                items.pop(index)

        if requests:
            body: dict[str, Any] = {
                "includeFormInResponse": True,
                "requests": requests,
            }
            if form.get("revisionId"):
                body["writeControl"] = {"requiredRevisionId": str(form["revisionId"])}
            resource.batchUpdate(formId=form_id, body=body).execute()

        return {
            "status": "updated",
            "form_id": form_id,
            "edit_url": f"https://docs.google.com/forms/d/{form_id}/edit",
            "applied_operations": len(operations),
            "operations": [operation.model_dump(exclude_none=True) for operation in operations],
        }
