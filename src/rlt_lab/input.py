"""Validate the evaluator's procurement/TRU CSV pair without supplier input.

Column meanings come from the supplied schema. Reordered columns are accepted;
unknown columns require an explicit schema update instead of guessing mappings.
Raw identifiers and repeated item rows are preserved.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
import re

from .data import ITEM_COLUMNS, NOTICE_COLUMNS


def _read_csv(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            sample = stream.read(16384)
            stream.seek(0)
            if not sample.strip():
                raise ValueError(f"Empty CSV: {path}")
            try:
                dialect = csv.Sniffer().sniff(sample.splitlines()[0], delimiters=",;")
            except csv.Error as error:
                raise ValueError(f"Cannot determine comma/semicolon delimiter: {path}") from error
            # Header-only sniffing determines the delimiter, not quote escaping.
            # A header without quotes cannot establish doublequote semantics.
            reader = csv.DictReader(stream, delimiter=dialect.delimiter, strict=True)
            header = reader.fieldnames
            if (header is None or len(header) != len(columns)
                    or set(header) != set(columns)):
                raise ValueError(f"Unsupported CSV schema in {path}: {header!r}; expected {list(columns)!r}")
            rows = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"Wrong CSV width in {path} at line {reader.line_num}")
                identifier = row["lot_id"]
                if not identifier or identifier != identifier.strip():
                    raise ValueError(f"Invalid lot_id in {path} at line {reader.line_num}; preserve the exact join key")
                rows.append(row)
    except (UnicodeError, csv.Error) as error:
        raise ValueError(f"Invalid UTF-8 CSV in {path}: {error}") from error
    return rows


def read_procurements(notices_path: Path, items_path: Path) -> list[dict]:
    """Read new lots, validate 1:N links, and retain all original TRU rows."""
    notices = _read_csv(Path(notices_path), NOTICE_COLUMNS)
    items = _read_csv(Path(items_path), ITEM_COLUMNS)
    if not notices:
        raise ValueError("Procurement CSV contains no lots")
    lots: dict[str, dict] = {}
    for notice in notices:
        identifier = notice["lot_id"]
        if identifier in lots:
            raise ValueError(f"Duplicate procurement lot_id: {identifier!r}")
        value = notice["publish_date"]
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError(f"Invalid publish_date for lot {identifier!r}: expected YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"Invalid publish_date for lot {identifier!r}: {value!r}") from error
        lots[identifier] = {"notice": notice, "items": []}
    for item in items:
        identifier = item["lot_id"]
        if identifier not in lots:
            raise ValueError(f"TRU lot_id {identifier!r} has no matching procurement in the input CSV pair")
        lots[identifier]["items"].append(item)
    return list(lots.values())
