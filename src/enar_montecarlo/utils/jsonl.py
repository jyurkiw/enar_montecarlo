"""JSONL serialization helpers for events.

One event per line, no embedded newlines, discriminator-tagged so
``loads_event`` returns the correct concrete subclass.
"""

from enar_montecarlo.events import Event, EventAdapter


def dumps_event(event: Event) -> str:
    """Serialize an event to a single compact JSON line."""
    return event.model_dump_json()


def loads_event(line: str) -> Event:
    """Parse a JSONL line back into the appropriate Event subclass."""
    return EventAdapter.validate_json(line)
