"""学习空间请求模型。"""
from pydantic import BaseModel, Field


class SpaceCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    capacity: int = Field(default=50, ge=1, le=500)


class SpaceUpdateBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class SpaceJoinBody(BaseModel):
    code: str = Field(min_length=1, max_length=32)
