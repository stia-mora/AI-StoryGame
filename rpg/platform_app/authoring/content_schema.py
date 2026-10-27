"""Portable v2 rows. Additional legacy columns remain import-compatible data."""
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter


class Row(BaseModel):
    model_config = {"extra": "allow", "strict": True}


class Chapter(Row):
    id: int | None = None
    chapter_index: int = Field(ge=1)
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    word_count: int = Field(default=0, ge=0)


class ChapterFact(Row):
    chapter: int = Field(ge=1)
    chapter_id: int | None = None
    summary: str = Field(min_length=1)


class CharacterCard(Row):
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    speech_style: str = ""
    first_revealed_chapter: int = Field(default=0, ge=0)
    enabled: bool = True
    metadata: dict = Field(default_factory=dict)


class Worldbook(Row):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    keys: list[str] = Field(default_factory=list)
    insertion_position: Literal["worldbook", "constant", "before_context", "after_context"] = "worldbook"


class Entity(Row):
    logical_key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    parent_logical_key: str = ""


class Anchor(Row):
    story_phase: str = Field(min_length=1)
    story_time_label: str = Field(min_length=1)
    chapter_min: int = Field(ge=1)
    chapter_max: int = Field(ge=1)


class Document(Row):
    source_kind: str = "chapter"
    source_ref: str
    content: str = Field(min_length=1)
    chapter_id: int | None = None


class Chunk(Document):
    chapter_index: int = Field(ge=1)
    chunk_index: int = Field(ge=0)


class Worldline(Row):
    wl_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    parent_wl: str | None = None


class Node(Row):
    wl_key: str = Field(min_length=1)
    node_key: str = Field(min_length=1)
    seq: int = Field(ge=0)


class Digest(Row):
    phase_label: str = Field(min_length=1)
    chapter_min: int = Field(ge=1)
    chapter_max: int = Field(ge=1)
    summary: str = Field(min_length=1)


FILES = {"chapters.jsonl": Chapter, "chapter_facts.jsonl": ChapterFact,
         "character_cards.jsonl": CharacterCard, "worldbook.jsonl": Worldbook,
         "kb_canon_entities.jsonl": Entity, "timeline_anchors.jsonl": Anchor,
         "documents.jsonl": Document, "chunks.jsonl": Chunk, "worldlines.jsonl": Worldline,
         "worldline_nodes.jsonl": Node, "phase_digests.jsonl": Digest}


def schemas():
    return {name: TypeAdapter(list[model]).json_schema() for name, model in FILES.items()}
