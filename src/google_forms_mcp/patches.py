from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from google_forms_mcp.models import FormSpec, QuestionSpec, SectionSpec


class PatchTargetError(ValueError):
    """Raised when a requested patch cannot be applied unambiguously."""


class _PatchBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "question_title",
        "option",
        "new_title",
        "section_title",
        "description",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def strip_string_values(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SetRequired(_PatchBase):
    operation: Literal["set_required"]
    question_title: str = Field(min_length=1)
    required: bool


class AddOption(_PatchBase):
    operation: Literal["add_option"]
    question_title: str = Field(min_length=1)
    option: str = Field(min_length=1)


class RemoveOption(_PatchBase):
    operation: Literal["remove_option"]
    question_title: str = Field(min_length=1)
    option: str = Field(min_length=1)


class RenameQuestion(_PatchBase):
    operation: Literal["rename_question"]
    question_title: str = Field(min_length=1)
    new_title: str = Field(min_length=1, max_length=300)


class SetQuestionDescription(_PatchBase):
    operation: Literal["set_question_description"]
    question_title: str = Field(min_length=1)
    description: str = Field(max_length=2000)


class DeleteQuestion(_PatchBase):
    operation: Literal["delete_question"]
    question_title: str = Field(min_length=1)


class AddQuestion(_PatchBase):
    operation: Literal["add_question"]
    section_title: str = Field(min_length=1)
    question: QuestionSpec


class RenameSection(_PatchBase):
    operation: Literal["rename_section"]
    section_title: str = Field(min_length=1)
    new_title: str = Field(min_length=1, max_length=300)


class SetFormTitle(_PatchBase):
    operation: Literal["set_form_title"]
    new_title: str = Field(min_length=1, max_length=300)


class SetFormDescription(_PatchBase):
    operation: Literal["set_form_description"]
    description: str = Field(max_length=5000)


PatchOperation: TypeAlias = Annotated[
    SetRequired
    | AddOption
    | RemoveOption
    | RenameQuestion
    | SetQuestionDescription
    | DeleteQuestion
    | AddQuestion
    | RenameSection
    | SetFormTitle
    | SetFormDescription,
    Field(discriminator="operation"),
]


@dataclass(frozen=True)
class PatchResult:
    spec: FormSpec
    changes: list[dict[str, object]]


def _find_question(spec: FormSpec, title: str) -> tuple[SectionSpec, QuestionSpec]:
    matches = [
        (section, question)
        for section in spec.sections
        for question in section.questions
        if question.title == title
    ]
    if not matches:
        raise PatchTargetError(f"Question not found: {title}")
    if len(matches) > 1:
        raise PatchTargetError(f"Question title is ambiguous: {title}")
    return matches[0]


def _find_section(spec: FormSpec, title: str) -> SectionSpec:
    matches = [section for section in spec.sections if section.title == title]
    if not matches:
        raise PatchTargetError(f"Section not found: {title}")
    if len(matches) > 1:
        raise PatchTargetError(f"Section title is ambiguous: {title}")
    return matches[0]


def apply_patches(spec: FormSpec, operations: list[PatchOperation]) -> PatchResult:
    """Apply explicit operations while preserving every unrelated field."""
    if not operations:
        raise PatchTargetError("At least one patch operation is required")
    updated = spec.model_copy(deep=True)
    changes: list[dict[str, object]] = []

    for operation in operations:
        if isinstance(operation, SetFormTitle):
            before = updated.title
            updated.title = operation.new_title.strip()
            changes.append(
                {
                    "operation": operation.operation,
                    "before": before,
                    "after": updated.title,
                }
            )
            continue

        if isinstance(operation, SetFormDescription):
            before = updated.description
            updated.description = operation.description.strip()
            changes.append(
                {
                    "operation": operation.operation,
                    "before": before,
                    "after": updated.description,
                }
            )
            continue

        if isinstance(operation, RenameSection):
            section = _find_section(updated, operation.section_title)
            before = section.title
            section.title = operation.new_title.strip()
            changes.append(
                {
                    "operation": operation.operation,
                    "section": before,
                    "before": before,
                    "after": section.title,
                }
            )
            continue

        if isinstance(operation, AddQuestion):
            section = _find_section(updated, operation.section_title)
            if any(
                question.title == operation.question.title
                for current in updated.sections
                for question in current.questions
            ):
                raise PatchTargetError(f"Question title already exists: {operation.question.title}")
            section.questions.append(operation.question.model_copy(deep=True))
            changes.append(
                {
                    "operation": operation.operation,
                    "section": section.title,
                    "question": operation.question.title,
                }
            )
            continue

        section, question = _find_question(updated, operation.question_title)

        if isinstance(operation, SetRequired):
            required_before = question.required
            question.required = operation.required
            changes.append(
                {
                    "operation": operation.operation,
                    "question": question.title,
                    "before": required_before,
                    "after": question.required,
                }
            )
        elif isinstance(operation, AddOption):
            option = operation.option.strip()
            if question.type not in {"multiple_choice", "checkboxes", "dropdown"}:
                raise PatchTargetError(f"Question does not accept options: {question.title}")
            if option in question.options:
                raise PatchTargetError(f"Option already exists for {question.title}: {option}")
            question.options.append(option)
            changes.append(
                {
                    "operation": operation.operation,
                    "question": question.title,
                    "after": option,
                }
            )
        elif isinstance(operation, RemoveOption):
            option = operation.option.strip()
            if option not in question.options:
                raise PatchTargetError(f"Option not found for {question.title}: {option}")
            if len(question.options) <= 2:
                raise PatchTargetError("Choice questions must retain at least two options")
            question.options.remove(option)
            changes.append(
                {
                    "operation": operation.operation,
                    "question": question.title,
                    "before": option,
                }
            )
        elif isinstance(operation, RenameQuestion):
            new_title = operation.new_title.strip()
            if any(
                candidate.title == new_title
                for current in updated.sections
                for candidate in current.questions
                if candidate is not question
            ):
                raise PatchTargetError(f"Question title already exists: {new_title}")
            before = question.title
            question.title = new_title
            changes.append(
                {
                    "operation": operation.operation,
                    "question": before,
                    "before": before,
                    "after": new_title,
                }
            )
        elif isinstance(operation, SetQuestionDescription):
            before = question.description
            question.description = operation.description.strip()
            changes.append(
                {
                    "operation": operation.operation,
                    "question": question.title,
                    "before": before,
                    "after": question.description,
                }
            )
        elif isinstance(operation, DeleteQuestion):
            section.questions.remove(question)
            changes.append(
                {
                    "operation": operation.operation,
                    "section": section.title,
                    "question": question.title,
                }
            )

    try:
        normalized = FormSpec.model_validate(updated.model_dump(exclude_computed_fields=True))
    except ValidationError as exc:
        raise PatchTargetError(f"Patch would create an invalid form: {exc}") from exc
    return PatchResult(spec=normalized, changes=changes)
