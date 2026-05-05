"""Pydantic event models emitted by sim ``run()`` generators.

The framework persists ``ResolutionEvent`` and ``EffectEvent`` rows to the
database. ``RoundCompleteMarker`` and ``SimulationCompleteMarker`` drive
progress UI and run-state tracking but are not persisted.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter


class ResolutionEvent(BaseModel):
    type: Literal["resolution"] = "resolution"
    event_seq: int
    iteration_num: int
    round_num: int = 1
    actor_file_id: str
    actor_index: int
    target_file_id: str | None = None
    target_index: int | None = None
    resolution_name: str
    outcome_id: int
    caused_by_seq: int | None = None
    notes: dict[str, Any] = Field(default_factory=dict)


class EffectEvent(BaseModel):
    type: Literal["effect"] = "effect"
    event_seq: int
    iteration_num: int
    round_num: int = 1
    actor_file_id: str
    actor_index: int
    target_file_id: str | None = None
    target_index: int | None = None
    effect_definition_name: str
    effect_type_id: int
    damage_type_id: int | None = None
    amount: float | None = None
    source_branch_id: int
    caused_by_seq: int
    trigger_name: str | None = None
    trigger_result: bool | None = None
    notes: dict[str, Any] = Field(default_factory=dict)


class RoundCompleteMarker(BaseModel):
    type: Literal["round_complete"] = "round_complete"
    event_seq: int
    iteration_num: int
    round_num: int


class SimulationCompleteMarker(BaseModel):
    type: Literal["sim_complete"] = "sim_complete"
    event_seq: int
    iteration_num: int
    rounds_executed: int
    outcome_summary: dict[str, Any] = Field(default_factory=dict)


type Event = Annotated[
    ResolutionEvent | EffectEvent | RoundCompleteMarker | SimulationCompleteMarker,
    Field(discriminator="type"),
]

EventAdapter: TypeAdapter[Event] = TypeAdapter(Event)
