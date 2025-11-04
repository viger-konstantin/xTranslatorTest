"""Utilities to load translation-relevant record definitions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional


@dataclass(frozen=True)
class FieldDefinition:
    """Description of a translatable subrecord field."""

    name: str
    record_type: str
    string_table: int
    mandatory: bool
    procedures: List[str]


class RecordDefinitions:
    """In-memory representation of all field definitions for a game."""

    def __init__(self, per_record: Mapping[str, Mapping[str, FieldDefinition]], wildcard: Mapping[str, FieldDefinition]):
        self._per_record = per_record
        self._wildcard = wildcard

    def get(self, record_type: str, field: str) -> Optional[FieldDefinition]:
        """Return the definition for ``field`` within ``record_type`` if present."""

        record_type = record_type.upper()
        field = field.upper()
        record_specific = self._per_record.get(record_type)
        if record_specific and field in record_specific:
            return record_specific[field]
        return self._wildcard.get(field)

    @staticmethod
    def load_from_folder(game_folder: Path) -> "RecordDefinitions":
        definition_path = game_folder / "_recorddefs.txt"
        if not definition_path.exists():
            raise FileNotFoundError(f"Record definition file not found: {definition_path}")
        per_record: Dict[str, Dict[str, FieldDefinition]] = {}
        wildcard: Dict[str, FieldDefinition] = {}
        for definition in _parse_definition_file(definition_path):
            target_map: MutableMapping[str, FieldDefinition]
            if definition.record_type == "****":
                target_map = wildcard
            else:
                target_map = per_record.setdefault(definition.record_type, {})
            # ``_recorddefs`` can contain duplicates; prefer the first explicit definition.
            target_map.setdefault(definition.name, definition)
        return RecordDefinitions(per_record, wildcard)


def _parse_definition_file(path: Path) -> Iterable[FieldDefinition]:
    """Yield :class:`FieldDefinition` objects parsed from ``_recorddefs.txt``."""

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("Def_:"):
            continue
        body = line[5:]
        parts = body.split("=")
        if len(parts) < 3:
            continue
        field_name = parts[0].strip().upper()
        record_type = parts[1].strip().upper()
        remainder = parts[2].strip()
        string_table, mandatory, procedures = _parse_field_attributes(remainder)
        yield FieldDefinition(
            name=field_name,
            record_type=record_type,
            string_table=string_table,
            mandatory=mandatory,
            procedures=procedures,
        )


def _parse_field_attributes(token: str) -> tuple[int, bool, List[str]]:
    procedures: List[str] = []
    mandatory = False
    value = ""
    for part in token.split("-"):
        if not value:
            value = part
            continue
        if part:
            procedures.append(part)
    if value.endswith("*"):
        mandatory = True
        value = value[:-1]
    try:
        string_table = int(value)
    except ValueError:
        string_table = 0
    return string_table, mandatory, procedures
