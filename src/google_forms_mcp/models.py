from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QuestionType = Literal[
    "short_text",
    "paragraph",
    "multiple_choice",
    "checkboxes",
    "dropdown",
    "linear_scale",
    "date",
    "time",
]

_CHOICE_TYPES = {"multiple_choice", "checkboxes", "dropdown"}


class QuestionSpec(BaseModel):
    """A supported Google Forms question."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=2000)
    type: QuestionType
    required: bool = False
    options: list[str] = Field(default_factory=list)
    lower_bound: int = 1
    upper_bound: int = 5
    low_label: str = Field(default="", max_length=100)
    high_label: str = Field(default="", max_length=100)

    @field_validator("title", "description", "low_label", "high_label")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("options")
    @classmethod
    def normalize_options(cls, options: list[str]) -> list[str]:
        return [option.strip() for option in options if option.strip()]

    @model_validator(mode="after")
    def validate_type_specific_fields(self) -> QuestionSpec:
        if self.type in _CHOICE_TYPES and len(set(self.options)) < 2:
            raise ValueError("choice questions require at least two unique options")
        if self.type not in _CHOICE_TYPES and self.options:
            raise ValueError(f"{self.type} questions do not accept options")
        if self.type == "linear_scale":
            if not 0 <= self.lower_bound <= 10 or not 0 <= self.upper_bound <= 10:
                raise ValueError("linear scale bounds must be between 0 and 10")
            if self.lower_bound >= self.upper_bound:
                raise ValueError("linear scale lower_bound must be less than upper_bound")
        return self


class SectionSpec(BaseModel):
    """A titled form section containing one or more questions."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=2000)
    questions: list[QuestionSpec] = Field(min_length=1, max_length=200)

    @field_validator("title", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class FormSpec(BaseModel):
    """A complete form definition accepted by the MCP tools."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    sections: list[SectionSpec] = Field(min_length=1, max_length=75)

    @field_validator("title", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @property
    def question_count(self) -> int:
        return sum(len(section.questions) for section in self.sections)
