"""HTTP request and response models for comic and tag APIs."""

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


class ComicQuery(RequestModel):
    generic_tag_ids: list[Annotated[int, Field(gt=0, le=2**63 - 1)]] = Field(
        default_factory=list, max_length=100,
    )
    tag_match: Literal["all", "any"] = "all"
    author_name: str | None = Field(default=None, min_length=1, pattern=r"\S")
    author_match: Literal["exact", "prefix", "contains"] = "exact"
    title: str | None = Field(default=None, min_length=1, pattern=r"\S")
    title_match: Literal["exact", "prefix", "contains"] = "contains"
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2**63 - 1)
