"""High level orchestration for the ESP translation workflow."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from .esp_parser import EspDocument, Record, Subrecord, update_subrecord_string
from .excel_io import TranslationRow, rows_to_xlsx, xlsx_to_rows
from .record_definitions import FieldDefinition, RecordDefinitions


@dataclass
class ExtractedString:
    record_type: str
    form_id: int
    subrecord: str
    occurrence: int
    definition: FieldDefinition
    text: str
    encoding: str
    terminator: bytes
    source_subrecord: Subrecord
    record: Record


class TranslationService:
    def __init__(self, data_root: Path):
        self.data_root = data_root

    def _load_definitions(self, game: str) -> RecordDefinitions:
        game_folder = self.data_root / game
        if not game_folder.exists():
            raise FileNotFoundError(f"Unknown game identifier '{game}'. Available: {[p.name for p in self.data_root.iterdir() if p.is_dir()]}")
        return RecordDefinitions.load_from_folder(game_folder)

    def extract(self, esp_bytes: bytes, game: str) -> Tuple[bytes, List[ExtractedString]]:
        document = EspDocument.from_bytes(esp_bytes)
        definitions = self._load_definitions(game)
        extracted: List[ExtractedString] = []
        occurrence_counters: Dict[Tuple[str, str, int], int] = {}
        for record in document.iter_records():
            for subrecord, definition, decoded in record.collect_strings(definitions):
                key = (record.record_type, subrecord.name, definition.string_table)
                occurrence = occurrence_counters.get(key, 0)
                occurrence_counters[key] = occurrence + 1
                extracted.append(
                    ExtractedString(
                        record_type=record.record_type,
                        form_id=record.form_id,
                        subrecord=subrecord.name,
                        occurrence=occurrence,
                        definition=definition,
                        text=decoded.text,
                        encoding=decoded.encoding,
                        terminator=decoded.terminator,
                        source_subrecord=subrecord,
                        record=record,
                    )
                )
        rows = [
            TranslationRow(
                record_type=item.record_type,
                form_id=f"{item.form_id:08X}",
                subrecord=item.subrecord,
                occurrence=item.occurrence,
                string_type=item.definition.string_table,
                original=item.text,
                translation=item.text,
            )
            for item in extracted
        ]
        workbook = rows_to_xlsx(rows)
        return workbook, extracted

    def apply(self, esp_bytes: bytes, excel_bytes: bytes, game: str) -> bytes:
        document = EspDocument.from_bytes(esp_bytes)
        definitions = self._load_definitions(game)
        translations = list(xlsx_to_rows(excel_bytes))
        translation_map: Dict[Tuple[str, int, str, int, int], str] = {}
        for row in translations:
            try:
                form_id = int(row.form_id, 16)
            except ValueError:
                continue
            key = (row.record_type.upper(), form_id, row.subrecord.upper(), row.occurrence, row.string_type)
            translation_map[key] = row.translation
        for record in document.iter_records():
            subrecords = record.ensure_subrecords()
            counters: Dict[Tuple[str, int], int] = {}
            for subrecord in subrecords:
                definition = definitions.get(record.record_type, subrecord.name)
                if not definition:
                    continue
                key_base = (subrecord.name.upper(), definition.string_table)
                occurrence = counters.get(key_base, 0)
                counters[key_base] = occurrence + 1
                lookup = (
                    record.record_type.upper(),
                    record.form_id,
                    subrecord.name.upper(),
                    occurrence,
                    definition.string_table,
                )
                new_value = translation_map.get(lookup)
                if new_value is None or new_value == "":
                    continue
                update_subrecord_string(subrecord, new_value)
            record.rebuild_payload()
        return document.rebuild()
