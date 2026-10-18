from __future__ import annotations

from typing import Any

from google_forms_mcp.models import FormSpec, QuestionSpec

JsonObject = dict[str, Any]

_CHOICE_TYPES = {
    "multiple_choice": "RADIO",
    "checkboxes": "CHECKBOX",
    "dropdown": "DROP_DOWN",
}


def compile_create_body(spec: FormSpec) -> JsonObject:
    """Build the body for forms.create."""
    return {"info": {"title": spec.title, "documentTitle": spec.title}}


def _question_payload(question: QuestionSpec) -> JsonObject:
    payload: JsonObject = {"required": question.required}

    if question.type in {"short_text", "paragraph"}:
        payload["textQuestion"] = {"paragraph": question.type == "paragraph"}
    elif question.type in _CHOICE_TYPES:
        payload["choiceQuestion"] = {
            "type": _CHOICE_TYPES[question.type],
            "options": [{"value": option} for option in question.options],
            "shuffle": False,
        }
    elif question.type == "linear_scale":
        payload["scaleQuestion"] = {
            "low": question.lower_bound,
            "high": question.upper_bound,
            "lowLabel": question.low_label,
            "highLabel": question.high_label,
        }
    elif question.type == "date":
        payload["dateQuestion"] = {"includeTime": False, "includeYear": True}
    elif question.type == "time":
        payload["timeQuestion"] = {"duration": False}
    else:  # pragma: no cover - protected by the validated literal type
        raise ValueError(f"Unsupported question type: {question.type}")

    return payload


def compile_question_item(question: QuestionSpec) -> JsonObject:
    item: JsonObject = {
        "title": question.title,
        "questionItem": {"question": _question_payload(question)},
    }
    if question.description:
        item["description"] = question.description
    return item


def compile_item_requests(spec: FormSpec) -> list[JsonObject]:
    """Compile a validated form into ordered forms.batchUpdate createItem requests."""
    requests: list[JsonObject] = []
    index = 0

    for section in spec.sections:
        section_item: JsonObject = {"title": section.title, "pageBreakItem": {}}
        if section.description:
            section_item["description"] = section.description
        requests.append({"createItem": {"item": section_item, "location": {"index": index}}})
        index += 1

        for question in section.questions:
            item = compile_question_item(question)
            requests.append({"createItem": {"item": item, "location": {"index": index}}})
            index += 1

    return requests
