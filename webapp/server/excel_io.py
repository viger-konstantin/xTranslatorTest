"""Minimal XLSX writer/reader used for translation exchange."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Iterable, Iterator, List, Sequence
from xml.etree import ElementTree as ET
import zipfile


@dataclass
class TranslationRow:
    record_type: str
    form_id: str
    subrecord: str
    occurrence: int
    string_type: int
    original: str
    translation: str


HEADERS = [
    "Record Type",
    "Form ID",
    "Subrecord",
    "Occurrence",
    "String Table",
    "Original",
    "Translation",
]


def rows_to_xlsx(rows: Sequence[TranslationRow]) -> bytes:
    with BytesIO() as buffer:
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", _content_types())
            archive.writestr("_rels/.rels", _rels())
            archive.writestr("xl/workbook.xml", _workbook())
            archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels())
            archive.writestr("xl/styles.xml", _styles())
            archive.writestr("xl/worksheets/sheet1.xml", _worksheet(rows))
        return buffer.getvalue()


def xlsx_to_rows(data: bytes) -> Iterator[TranslationRow]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        with archive.open("xl/worksheets/sheet1.xml") as sheet_file:
            tree = ET.parse(sheet_file)
    root = tree.getroot()
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows = root.find("s:sheetData", ns)
    if rows is None:
        return iter(())
    for row in rows.findall("s:row", ns):
        values: List[str] = [""] * len(HEADERS)
        for cell in row.findall("s:c", ns):
            ref = cell.get("r", "")
            col_index = _col_index(ref)
            if col_index >= len(values):
                continue
            text_node = cell.find("s:is/s:t", ns)
            if text_node is None:
                values[col_index] = ""
            else:
                values[col_index] = text_node.text or ""
        if values == HEADERS:
            continue
        if not any(values):
            continue
        try:
            occurrence = int(values[3]) if values[3] else 0
            string_type = int(values[4]) if values[4] else 0
        except ValueError:
            occurrence = 0
            string_type = 0
        yield TranslationRow(
            record_type=values[0],
            form_id=values[1],
            subrecord=values[2],
            occurrence=occurrence,
            string_type=string_type,
            original=values[5],
            translation=values[6],
        )


def _worksheet(rows: Sequence[TranslationRow]) -> str:
    from xml.sax.saxutils import escape

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        "  <sheetData>",
    ]
    lines.append(_row_xml(1, HEADERS))
    for index, row in enumerate(rows, start=2):
        lines.append(
            _row_xml(
                index,
                [
                    row.record_type,
                    row.form_id,
                    row.subrecord,
                    str(row.occurrence),
                    str(row.string_type),
                    row.original,
                    row.translation,
                ],
            )
        )
    lines.append("  </sheetData>")
    lines.append("</worksheet>")
    return "\n".join(lines)


def _row_xml(row_index: int, values: Sequence[str]) -> str:
    from xml.sax.saxutils import escape

    cells = []
    for column, value in enumerate(values, start=1):
        column_ref = _column_name(column)
        escaped = escape(value or "")
        cells.append(
            f'    <c r="{column_ref}{row_index}" t="inlineStr"><is><t>{escaped}</t></is></c>'
        )
    return f"  <row r=\"{row_index}\">\n" + "\n".join(cells) + "\n  </row>"


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _col_index(reference: str) -> int:
    col = 0
    for char in reference:
        if char.isalpha():
            col = col * 26 + (ord(char.upper()) - 64)
    return col - 1


def _content_types() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""


def _rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _workbook() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Translations" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""


def _workbook_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""


def _styles() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1">
    <font>
      <sz val="11"/>
      <color theme="1"/>
      <name val="Calibri"/>
      <family val="2"/>
      <scheme val="minor"/>
    </font>
  </fonts>
  <fills count="1">
    <fill>
      <patternFill patternType="none"/>
    </fill>
  </fills>
  <borders count="1">
    <border/>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellXfs>
  <cellXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
  </cellXfs>
  <cellStyles count="1">
    <cellStyle name="Normal" xfId="0" builtinId="0"/>
  </cellStyles>
</styleSheet>"""
