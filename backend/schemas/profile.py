"""Public single-tenant teacher profile contract."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UserProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    nickname: str = Field(min_length=1, max_length=40)
    teaching_stage: Literal["", "primary", "junior", "senior"] = ""
    grade: str = Field(default="", pattern=r"^(?:[1-9]|1[0-2])?$")

    @field_validator("nickname", mode="before")
    @classmethod
    def normalize_nickname(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError("昵称不能包含控制字符")
        return value

    @model_validator(mode="after")
    def check_teaching_grade(self) -> Self:
        if self.grade:
            grades = {"primary": range(1, 7), "junior": range(7, 10), "senior": range(10, 13)}
            if int(self.grade) not in grades.get(self.teaching_stage, ()):
                raise ValueError("年级必须与任教学段匹配")
        return self


class UserProfile(UserProfileUpdate):
    nickname: str = "教师"
    role: Literal["teacher"] = Field(default="teacher", json_schema_extra={"readOnly": True})
    avatar_url: str | None = Field(default=None, json_schema_extra={"readOnly": True})
