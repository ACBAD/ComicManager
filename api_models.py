"""HTTP request and response models for the comic entry workflow."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sites import SourceSite
from tags import SpecificTagUnion, TagGroup


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any]


class ErrorResponse(BaseModel):
    error: ErrorDetail


class GenericTagQuery(RequestModel):
    tag_group: TagGroup
    name: str | None = None
    name_match: Literal["exact", "prefix", "contains"] = "exact"
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SpecificTagExactQuery(RequestModel):
    match: Literal["exact"]
    specific_tag: SpecificTagUnion


class SpecificTagOriginQuery(RequestModel):
    match: Literal["same_origin"]
    site: SourceSite
    origin_name: str = Field(min_length=1, pattern=r"\S")
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


SpecificTagQuery = Annotated[
    SpecificTagExactQuery | SpecificTagOriginQuery,
    Field(discriminator="match"),
]


class SpecificTagCreate(RequestModel):
    specific_tag: SpecificTagUnion
    generic_tag_id: int = Field(gt=0)


class SourceDocument(BaseModel):
    """The fields consumed from DMB's document response; other fields are ignored."""

    document_id: int
    source: SourceSite
    source_document_id: str
    source_meta: dict[str, Any] = Field(min_length=1)


class ComicCommitRequest(RequestModel):
    source_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
