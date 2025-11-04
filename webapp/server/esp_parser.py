"""Simplified ESP/ESM parser focused on extractable string fields."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import struct
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
import zlib

from .record_definitions import FieldDefinition, RecordDefinitions

RECORD_HEADER_STRUCT = struct.Struct("<4sI I I I H H")
GROUP_HEADER_STRUCT = struct.Struct("<4sI4sI H H H H")
SUBRECORD_HEADER_STRUCT = struct.Struct("<4sH")

# Record flags
FLAG_COMPRESSED = 0x00040000


@dataclass
class Subrecord:
    name: str
    data: bytearray
    use_extended: bool = False
    size_field: int = 0

    def as_bytes(self) -> bytes:
        return bytes(self.data)


@dataclass
class Record:
    record_type: str
    data_size: int
    flags: int
    form_id: int
    revision: int
    version: int
    unknown: int
    payload: bytes
    subrecords: Optional[List[Subrecord]] = None

    @property
    def compressed(self) -> bool:
        return bool(self.flags & FLAG_COMPRESSED)

    def ensure_subrecords(self) -> List[Subrecord]:
        if self.subrecords is None:
            data = self.get_decompressed_payload()
            self.subrecords = list(parse_subrecords(data))
        return self.subrecords

    def get_decompressed_payload(self) -> bytes:
        if not self.compressed:
            return self.payload
        if len(self.payload) < 4:
            raise ValueError("Compressed payload is too small to contain the expected size prefix")
        expected_size = struct.unpack_from("<I", self.payload, 0)[0]
        compressed_data = self.payload[4:]
        decompressed = zlib.decompress(compressed_data)
        if len(decompressed) != expected_size:
            # Bethesda plugins occasionally misreport the size by a handful of bytes; do not fail hard.
            pass
        return decompressed

    def rebuild_payload(self) -> None:
        if self.subrecords is None:
            return
        rebuilt = build_subrecords(self.subrecords)
        if self.compressed:
            compressed = zlib.compress(rebuilt)
            self.payload = struct.pack("<I", len(rebuilt)) + compressed
        else:
            self.payload = rebuilt
        self.data_size = len(self.payload)

    def collect_strings(
        self, definitions: RecordDefinitions
    ) -> Iterator[Tuple[Subrecord, FieldDefinition, "DecodedString"]]:
        subrecords = self.ensure_subrecords()
        for sub in subrecords:
            definition = definitions.get(self.record_type, sub.name)
            if not definition:
                continue
            decoded = decode_subrecord_string(sub.data)
            if decoded is None:
                continue
            yield sub, definition, decoded


@dataclass
class Group:
    label: bytes
    group_type: int
    timestamp: int
    unknown1: int
    unknown2: int
    unknown3: int
    children: List["Node"] = field(default_factory=list)

    def rebuild_size(self) -> int:
        size = 24
        for child in self.children:
            size += child.total_size
        self._size = size
        return size

    @property
    def total_size(self) -> int:
        return getattr(self, "_size", self.rebuild_size())


Node = Tuple[str, object]


@dataclass
class EspDocument:
    nodes: List[Node]

    @classmethod
    def load(cls, path: Path) -> "EspDocument":
        data = path.read_bytes()
        nodes, _ = parse_nodes(memoryview(data), 0, len(data))
        return cls(nodes)

    @classmethod
    def from_bytes(cls, data: bytes) -> "EspDocument":
        nodes, _ = parse_nodes(memoryview(data), 0, len(data))
        return cls(nodes)

    def iter_records(self) -> Iterator[Record]:
        for node_type, node in self.nodes:
            yield from _iter_records(node_type, node)

    def rebuild(self) -> bytes:
        chunks: List[bytes] = []
        for node_type, node in self.nodes:
            chunks.append(build_node(node_type, node))
        return b"".join(chunks)


def parse_nodes(data: memoryview, offset: int, end: int) -> Tuple[List[Node], int]:
    nodes: List[Node] = []
    cursor = offset
    while cursor < end:
        header = data[cursor:cursor + 4].tobytes()
        if header == b"GRUP":
            group, cursor = parse_group(data, cursor)
            nodes.append(("group", group))
        else:
            record, cursor = parse_record(data, cursor)
            nodes.append(("record", record))
    return nodes, cursor


def parse_group(data: memoryview, offset: int) -> Tuple[Group, int]:
    if offset + GROUP_HEADER_STRUCT.size > len(data):
        raise ValueError("Unexpected end of data while reading group header")
    raw = GROUP_HEADER_STRUCT.unpack_from(data, offset)
    _, size, label, group_type, stamp, unknown1, unknown2, unknown3 = raw
    group = Group(label=label, group_type=group_type, timestamp=stamp, unknown1=unknown1, unknown2=unknown2, unknown3=unknown3)
    start = offset + GROUP_HEADER_STRUCT.size
    end = offset + size
    children, new_cursor = parse_nodes(data, start, end)
    group.children.extend(children)
    group._size = size
    return group, new_cursor


def parse_record(data: memoryview, offset: int) -> Tuple[Record, int]:
    if offset + RECORD_HEADER_STRUCT.size > len(data):
        raise ValueError("Unexpected end of data while reading record header")
    raw = RECORD_HEADER_STRUCT.unpack_from(data, offset)
    record_type, data_size, flags, form_id, revision, version, unknown = raw
    record_type_str = record_type.decode("ascii", errors="ignore")
    payload_offset = offset + RECORD_HEADER_STRUCT.size
    payload_end = payload_offset + data_size
    payload = data[payload_offset:payload_end].tobytes()
    record = Record(
        record_type=record_type_str,
        data_size=data_size,
        flags=flags,
        form_id=form_id,
        revision=revision,
        version=version,
        unknown=unknown,
        payload=payload,
    )
    record.total_size = RECORD_HEADER_STRUCT.size + len(payload)
    return record, payload_end


def parse_subrecords(data: bytes) -> Iterator[Subrecord]:
    cursor = 0
    extended_size: Optional[int] = None
    while cursor < len(data):
        if cursor + SUBRECORD_HEADER_STRUCT.size > len(data):
            break
        name_bytes, size_field = SUBRECORD_HEADER_STRUCT.unpack_from(data, cursor)
        cursor += SUBRECORD_HEADER_STRUCT.size
        name = name_bytes.decode("ascii", errors="ignore")
        if name == "XXXX":
            if cursor + 4 > len(data):
                break
            extended_size = struct.unpack_from("<I", data, cursor)[0]
            cursor += 4
            continue
        actual_size = size_field
        use_extended = False
        if extended_size is not None:
            actual_size = extended_size
            use_extended = True
            extended_size = None
        payload = data[cursor:cursor + actual_size]
        cursor += actual_size
        yield Subrecord(name=name, data=bytearray(payload), use_extended=use_extended, size_field=size_field)


def build_subrecords(subrecords: Sequence[Subrecord]) -> bytes:
    chunks: List[bytes] = []
    for sub in subrecords:
        data = sub.as_bytes()
        size = len(data)
        header_name = sub.name.encode("ascii")
        if len(header_name) != 4:
            raise ValueError(f"Invalid subrecord name: {sub.name}")
        if sub.use_extended or size > 0xFFFF:
            chunks.append(b"XXXX" + struct.pack("<H", 4) + struct.pack("<I", size))
            size_field = sub.size_field if sub.use_extended else size & 0xFFFF
        else:
            size_field = size
        chunks.append(header_name + struct.pack("<H", size_field) + data)
    return b"".join(chunks)


def build_node(node_type: str, node: object) -> bytes:
    if node_type == "record":
        record: Record = node  # type: ignore[assignment]
        record.rebuild_payload()
        header = struct.pack(
            "<4sI I I I H H",
            record.record_type.encode("ascii"),
            record.data_size,
            record.flags,
            record.form_id,
            record.revision,
            record.version,
            record.unknown,
        )
        record.total_size = len(header) + len(record.payload)
        return header + record.payload
    if node_type == "group":
        group: Group = node  # type: ignore[assignment]
        body_parts = [build_node(child_type, child) for child_type, child in group.children]
        body = b"".join(body_parts)
        size = 24 + len(body)
        group._size = size
        header = struct.pack(
            "<4sI4sI H H H H",
            b"GRUP",
            size,
            group.label,
            group.group_type,
            group.timestamp,
            group.unknown1,
            group.unknown2,
            group.unknown3,
        )
        return header + body
    raise ValueError(f"Unknown node type: {node_type}")


def _iter_records(node_type: str, node: object) -> Iterator[Record]:
    if node_type == "record":
        yield node  # type: ignore[misc]
    elif node_type == "group":
        group: Group = node  # type: ignore[assignment]
        for child_type, child in group.children:
            yield from _iter_records(child_type, child)


@dataclass(frozen=True)
class DecodedString:
    text: str
    encoding: str
    terminator: bytes


def decode_subrecord_string(data: bytearray) -> Optional[DecodedString]:
    raw = bytes(data)
    if not raw:
        return DecodedString("", "utf-8", b"")

    terminator = b""
    if raw.endswith(b"\x00\x00"):
        terminator = b"\x00\x00"
        raw = raw[:-2]
    elif raw.endswith(b"\x00"):
        terminator = b"\x00"
        raw = raw[:-1]

    candidates = ("utf-8", "utf-16-le", "cp1251", "cp1252", "latin-1")
    for encoding in candidates:
        try:
            text = raw.decode(encoding)
            return DecodedString(text, encoding, terminator)
        except UnicodeDecodeError:
            continue
    # Final fallback with replacement characters to avoid losing data completely.
    return DecodedString(raw.decode("latin-1", errors="replace"), "latin-1", terminator)


def update_subrecord_string(subrecord: Subrecord, value: str) -> None:
    decoded = decode_subrecord_string(subrecord.data)
    terminator = b""
    encoding_candidates: List[str] = []
    if decoded is not None:
        base_encoding = decoded.encoding.lower()
        terminator = decoded.terminator
    else:
        base_encoding = ""
        terminator = b""
        if bytes(subrecord.data).endswith(b"\x00\x00"):
            terminator = b"\x00\x00"
        elif bytes(subrecord.data).endswith(b"\x00"):
            terminator = b"\x00"

    if base_encoding and base_encoding not in encoding_candidates:
        # Prefer the detected encoding for wide strings, but allow single-byte strings
        # to fall back to locale-specific code pages before UTF-8.
        if terminator == b"\x00\x00":
            encoding_candidates.append(base_encoding)
    if terminator == b"\x00\x00":
        fallback_order = ["utf-16-le", "utf-8", "cp1251", "cp1252", "latin-1"]
    else:
        if base_encoding and base_encoding not in encoding_candidates and base_encoding not in {"utf-8"}:
            encoding_candidates.append(base_encoding)
        fallback_order = ["cp1251", "cp1252", "latin-1", "utf-8", "utf-16-le"]
    for encoding in fallback_order:
        if encoding and encoding not in encoding_candidates:
            encoding_candidates.append(encoding)

    encoded = None
    for encoding in encoding_candidates:
        try:
            encoded = value.encode(encoding)
            break
        except UnicodeEncodeError:
            continue

    if encoded is None:
        encoded = value.encode("utf-8", errors="replace")

    if terminator and not encoded.endswith(terminator):
        encoded += terminator
    subrecord.data[:] = encoded
