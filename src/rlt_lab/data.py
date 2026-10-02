"""Stream the supplied CSV archive into SQLite and produce an auditable summary.

Archive member names are unreliable. Only exact column headers select a table.
Supplier content is excluded after its header unless history is explicitly enabled.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from zipfile import ZipFile


ITEM_COLUMNS = ("lot_id", "product_name", "okpd2_code")
NOTICE_COLUMNS = (
    "publish_date", "procedure_id", "lot_id", "start_price", "reqnum",
    "procedure_name", "subject", "is_smp", "customer_inn", "customer_kpp",
    "is_eshop_or_aisgz",
)
SUPPLIER_COLUMNS = ("lot_id", "supplier_inn", "supplier_kpp", "is_winner")
_HEADERS = {ITEM_COLUMNS: "items", NOTICE_COLUMNS: "notices",
            SUPPLIER_COLUMNS: "suppliers"}
_TABLE_COLUMNS = {"items": ITEM_COLUMNS, "notices": NOTICE_COLUMNS,
                  "suppliers": SUPPLIER_COLUMNS}
_BATCH_SIZE = 5000


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_signature(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns


def _insert_batch(connection: sqlite3.Connection, role: str, batch: list,
                  member_name: str, line_number: int) -> None:
    columns = _TABLE_COLUMNS[role]
    placeholders = ",".join("?" for _ in columns)
    try:
        connection.executemany(
            f"INSERT INTO {role} ({','.join(columns)}) VALUES ({placeholders})", batch
        )
    except sqlite3.IntegrityError as error:
        raise ValueError(
            f"Duplicate notices lot_id in {member_name!r}, batch ending at CSV line "
            f"{line_number}: {error}"
        ) from error


def _read_members(connection: sqlite3.Connection, archive_path: Path,
                  include_history: bool) -> tuple[list, dict]:
    manifest = []
    tables = {}
    with ZipFile(archive_path) as archive:
        for member in archive.infolist():
            entry = {"name": member.filename, "size": member.file_size,
                     "compressed_size": member.compress_size, "role": "ignored"}
            manifest.append(entry)
            if (member.is_dir() or member.filename.startswith("__MACOSX/")
                    or not member.filename.casefold().endswith(".csv")):
                continue
            with archive.open(member) as raw:
                # Decode only the header. TextIOWrapper can otherwise prefetch and
                # decode supplier rows even when history has not been enabled.
                header_bytes = raw.readline(65537)
                if len(header_bytes) > 65536:
                    raise ValueError(f"CSV header exceeds 65536 bytes: {member.filename!r}")
                try:
                    header = tuple(next(csv.reader(
                        [header_bytes.decode("utf-8-sig")], delimiter=";", strict=True
                    )))
                except (UnicodeError, csv.Error, StopIteration) as error:
                    raise ValueError(f"Invalid CSV header in {member.filename!r}: {error}") from error
                entry["header"] = list(header)
                role = _HEADERS.get(header)
                if role is None:
                    raise ValueError(f"Unrecognized CSV columns in {member.filename!r}: {header!r}")
                entry["role"] = role
                if role == "suppliers" and not include_history:
                    entry["role"] = "suppliers_ignored"
                    continue
                if role in tables:
                    raise ValueError(f"Duplicate CSV schema {role!r}: multiple archive members")
                stats = {"row_count": 0, "missing_fields": {column: 0 for column in header}}
                if role == "suppliers":
                    stats["inn_format_counts"] = {
                        "ascii_10_digits": 0, "ascii_12_digits": 0, "missing": 0, "other": 0,
                    }
                tables[role] = stats
                lot_index = header.index("lot_id")
                stream = io.TextIOWrapper(raw, encoding="utf-8", newline="")
                reader = csv.reader(stream, delimiter=";", strict=True)
                batch = []
                try:
                    for row in reader:
                        line_number = reader.line_num + 1
                        if len(row) != len(header):
                            raise ValueError(
                                f"Wrong CSV width in {member.filename!r} at line {line_number}: "
                                f"expected {len(header)} fields, got {len(row)}"
                            )
                        if not row[lot_index].strip():
                            raise ValueError(
                                f"Missing required lot_id in {member.filename!r} at line {line_number}"
                            )
                        if row[lot_index] != row[lot_index].strip():
                            raise ValueError(
                                f"lot_id has surrounding whitespace in {member.filename!r} "
                                f"at line {line_number}; refusing an ambiguous join key"
                            )
                        if role == "notices":
                            value = row[0]
                            try:
                                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                                    raise ValueError("expected YYYY-MM-DD")
                                date.fromisoformat(value)
                            except ValueError as error:
                                raise ValueError(
                                    f"Invalid publish_date {value!r} in {member.filename!r} "
                                    f"at line {line_number}: {error}"
                                ) from error
                        for column, value in zip(header, row):
                            stats["missing_fields"][column] += not value.strip()
                        if role == "suppliers":
                            inn = row[1]
                            if not inn.strip():
                                format_name = "missing"
                            elif re.fullmatch(r"[0-9]{10}", inn):
                                format_name = "ascii_10_digits"
                            elif re.fullmatch(r"[0-9]{12}", inn):
                                format_name = "ascii_12_digits"
                            else:
                                format_name = "other"
                            stats["inn_format_counts"][format_name] += 1
                        stats["row_count"] += 1
                        batch.append(row)
                        if len(batch) == _BATCH_SIZE:
                            _insert_batch(connection, role, batch, member.filename, line_number)
                            batch.clear()
                    if batch:
                        _insert_batch(connection, role, batch, member.filename, reader.line_num + 1)
                except (UnicodeError, csv.Error) as error:
                    raise ValueError(
                        f"Invalid CSV data in {member.filename!r} near line {reader.line_num + 1}: {error}"
                    ) from error
    required_tables = {"items", "notices"} | ({"suppliers"} if include_history else set())
    if set(tables) != required_tables:
        requirement = " and one suppliers CSV" if include_history else ""
        raise ValueError("Archive must contain exactly one TRU items CSV and one procurement notices CSV" + requirement)
    return manifest, tables


def _supplier_summary(connection: sqlite3.Connection, stats: dict) -> dict:
    """Describe raw historical participants without interpreting relevance or quality."""
    def scalar(sql: str) -> int:
        return connection.execute(sql).fetchone()[0]

    stats["distinct_lot_count"] = scalar("SELECT COUNT(DISTINCT lot_id) FROM suppliers")
    stats["distinct_nonempty_inn_count"] = sum(
        bool(inn.strip()) for (inn,) in connection.execute("SELECT DISTINCT supplier_inn FROM suppliers")
    )
    stats["inn_format_warning_rows"] = stats["inn_format_counts"]["other"]
    stats["inn_format_warning_definition"] = "Nonempty raw INN is not exactly 10 or 12 ASCII digits; no normalization or checksum validation."
    stats["winner_value_counts"] = dict(connection.execute(
        "SELECT is_winner, COUNT(*) FROM suppliers GROUP BY is_winner ORDER BY is_winner"
    ))
    groups, rows, extras = connection.execute("""
        SELECT COUNT(*), COALESCE(SUM(n),0), COALESCE(SUM(n-1),0)
        FROM (SELECT COUNT(*) AS n FROM suppliers
              GROUP BY lot_id, supplier_inn, supplier_kpp, is_winner HAVING COUNT(*)>1)
    """).fetchone()
    orphan_rows = scalar("SELECT COUNT(*) FROM suppliers s WHERE NOT EXISTS (SELECT 1 FROM notices n WHERE n.lot_id=s.lot_id)")
    return {
        "suppliers": stats,
        "duplicate_suppliers": {"groups": groups, "rows_in_groups": rows, "extra_rows": extras},
        "supplier_relationships": {
            "supplier_rows_without_notice": orphan_rows,
            "supplier_lots_without_notice": scalar("SELECT COUNT(DISTINCT lot_id) FROM suppliers s WHERE NOT EXISTS (SELECT 1 FROM notices n WHERE n.lot_id=s.lot_id)"),
            "supplier_rows_without_items": scalar("SELECT COUNT(*) FROM suppliers s WHERE NOT EXISTS (SELECT 1 FROM items i WHERE i.lot_id=s.lot_id)"),
            "supplier_lots_without_items": scalar("SELECT COUNT(DISTINCT lot_id) FROM suppliers s WHERE NOT EXISTS (SELECT 1 FROM items i WHERE i.lot_id=s.lot_id)"),
            "notice_lots_without_suppliers": scalar("SELECT COUNT(*) FROM notices n WHERE NOT EXISTS (SELECT 1 FROM suppliers s WHERE s.lot_id=n.lot_id)"),
            "item_lots_without_suppliers": scalar("SELECT COUNT(DISTINCT lot_id) FROM items i WHERE NOT EXISTS (SELECT 1 FROM suppliers s WHERE s.lot_id=i.lot_id)"),
            "linked_supplier_rows": stats["row_count"] - orphan_rows,
        },
        "supplier_history_scope": "Raw historical participant rows only. Duplicates retained; INN/KPP and winner claims unchanged. Participation and winner values do not verify assortment, company role or product relevance.",
    }


def _summarize(connection: sqlite3.Connection, tables: dict) -> dict:
    def scalar(sql: str) -> int:
        return connection.execute(sql).fetchone()[0]

    for role in ("items", "notices"):
        tables[role]["distinct_lot_count"] = scalar(f"SELECT COUNT(DISTINCT lot_id) FROM {role}")
    minimum, maximum = connection.execute("SELECT MIN(publish_date), MAX(publish_date) FROM notices").fetchone()
    years = dict(connection.execute(
        "SELECT substr(publish_date,1,4), COUNT(*) FROM notices GROUP BY substr(publish_date,1,4) ORDER BY 1"
    ))
    duplicate_groups, duplicate_rows, duplicate_extras = connection.execute("""
        SELECT COUNT(*), COALESCE(SUM(n),0), COALESCE(SUM(n-1),0)
        FROM (SELECT COUNT(*) AS n FROM items
              GROUP BY lot_id, product_name, okpd2_code HAVING COUNT(*)>1)
    """).fetchone()
    orphan_rows = scalar("SELECT COUNT(*) FROM items i WHERE NOT EXISTS (SELECT 1 FROM notices n WHERE n.lot_id=i.lot_id)")
    orphan_lots = scalar("SELECT COUNT(DISTINCT lot_id) FROM items i WHERE NOT EXISTS (SELECT 1 FROM notices n WHERE n.lot_id=i.lot_id)")
    unmatched_notices = scalar("SELECT COUNT(*) FROM notices n WHERE NOT EXISTS (SELECT 1 FROM items i WHERE i.lot_id=n.lot_id)")
    code_counts = [{"code": code, "item_count": count} for code, count in connection.execute("""
        SELECT okpd2_code, COUNT(*) FROM items WHERE trim(okpd2_code)<>''
        GROUP BY okpd2_code ORDER BY COUNT(*) DESC, okpd2_code
    """)]
    categories = []
    categories_by_prefix = {}
    for prefix, count, lots, joined_lots in connection.execute("""
        SELECT substr(i.okpd2_code,1,2), COUNT(*), COUNT(DISTINCT i.lot_id), COUNT(DISTINCT n.lot_id)
        FROM items i LEFT JOIN notices n ON n.lot_id=i.lot_id
        WHERE trim(i.okpd2_code)<>'' GROUP BY substr(i.okpd2_code,1,2)
        ORDER BY COUNT(*) DESC, substr(i.okpd2_code,1,2)
    """):
        entry = {"prefix": prefix, "item_count": count, "distinct_lot_count": lots,
                 "joined_lot_count": joined_lots, "product_examples": [], "subject_examples": []}
        categories.append(entry)
        categories_by_prefix[prefix] = entry
    # One grouped query per example type, instead of one full scan per prefix.
    for prefix, product, count in connection.execute("""
        SELECT substr(okpd2_code,1,2), product_name, COUNT(*) FROM items
        WHERE trim(okpd2_code)<>'' AND trim(product_name)<>''
        GROUP BY substr(okpd2_code,1,2), product_name
        ORDER BY 1, COUNT(*) DESC, product_name
    """):
        examples = categories_by_prefix[prefix]["product_examples"]
        if len(examples) < 3:
            examples.append({"product_name": product, "item_count": count})
    for prefix, subject, count in connection.execute("""
        SELECT substr(i.okpd2_code,1,2), n.subject, COUNT(DISTINCT i.lot_id)
        FROM items i JOIN notices n ON n.lot_id=i.lot_id
        WHERE trim(i.okpd2_code)<>'' AND trim(n.subject)<>''
        GROUP BY substr(i.okpd2_code,1,2), n.subject
        ORDER BY 1, COUNT(DISTINCT i.lot_id) DESC, n.subject
    """):
        examples = categories_by_prefix[prefix]["subject_examples"]
        if len(examples) < 3:
            examples.append({"subject": subject, "lot_count": count})
    return {
        "items": tables["items"], "notices": tables["notices"],
        "dates": {"minimum": minimum, "maximum": maximum, "year_counts": years},
        "duplicate_items": {"groups": duplicate_groups, "rows_in_groups": duplicate_rows,
                            "extra_rows": duplicate_extras},
        "relationships": {
            "item_rows_without_notice": orphan_rows, "item_lots_without_notice": orphan_lots,
            "notice_lots_without_items": unmatched_notices,
            "joined_item_rows": tables["items"]["row_count"] - orphan_rows,
            "linked_notice_lots": tables["notices"]["row_count"] - unmatched_notices,
        },
        "okpd2": {"distinct_nonempty_codes": len(code_counts),
                  "missing_rows": tables["items"]["missing_fields"]["okpd2_code"], "counts": code_counts},
        "category_summary_source": "TRU items.okpd2_code first two characters; procurement notices.subject joined by lot_id. Product counts count rows; subject counts count distinct lots. Sorted by item_count descending, prefix ascending.",
        "category_summary": categories,
        **(_supplier_summary(connection, tables["suppliers"]) if "suppliers" in tables else {}),
    }


def build_database(archive_path: Path, database_path: Path, audit_path: Path,
                   replace: bool = False, include_history: bool = False) -> dict:
    """Validate and stream TRU + notices, then atomically publish the database.

    Existing databases require ``replace=True``. All source-validation failures
    preserve previous outputs. Suppliers are parsed only with ``include_history=True``.
    Their raw identifiers and winner values are retained. Each output is
    published atomically; a filesystem cannot atomically replace two paths.
    """
    archive_path, database_path, audit_path = map(Path, (archive_path, database_path, audit_path))
    if len({path.resolve() for path in (archive_path, database_path, audit_path)}) != 3:
        raise ValueError("Archive, database and audit must use different paths")
    if database_path.exists() and not replace:
        raise FileExistsError(f"Database already exists: {database_path}; pass replace=True explicitly")
    if database_path.is_dir() or audit_path.is_dir():
        raise IsADirectoryError("Database and audit outputs must be files")
    signature = _source_signature(archive_path)
    archive_hash = _file_sha256(archive_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_database = temporary_audit = None
    connection = None
    lock_path = database_path.with_name(f".{database_path.name}.build.lock")
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        if database_path.exists() and not replace:
            raise FileExistsError(f"Database already exists: {database_path}")
        fd, name = tempfile.mkstemp(prefix=f".{database_path.name}.", suffix=".tmp", dir=database_path.parent)
        os.close(fd)
        temporary_database = Path(name)
        connection = sqlite3.connect(temporary_database)
        connection.execute("PRAGMA cache_size=-65536")
        connection.execute("PRAGMA temp_store=FILE")
        connection.executescript("""
            CREATE TABLE items (row_id INTEGER PRIMARY KEY, lot_id TEXT NOT NULL,
                                product_name TEXT NOT NULL, okpd2_code TEXT NOT NULL);
            CREATE TABLE notices (publish_date TEXT NOT NULL, procedure_id TEXT NOT NULL,
                lot_id TEXT PRIMARY KEY NOT NULL, start_price TEXT NOT NULL, reqnum TEXT NOT NULL,
                procedure_name TEXT NOT NULL, subject TEXT NOT NULL, is_smp TEXT NOT NULL,
                customer_inn TEXT NOT NULL, customer_kpp TEXT NOT NULL, is_eshop_or_aisgz TEXT NOT NULL);
        """)
        if include_history:
            connection.execute("""
                CREATE TABLE suppliers (row_id INTEGER PRIMARY KEY, lot_id TEXT NOT NULL,
                    supplier_inn TEXT NOT NULL, supplier_kpp TEXT NOT NULL, is_winner TEXT NOT NULL)
            """)
        manifest, tables = _read_members(connection, archive_path, include_history)
        connection.execute("CREATE INDEX items_lot_id ON items(lot_id)")
        connection.execute("CREATE INDEX notices_publish_date ON notices(publish_date)")
        if include_history:
            connection.execute("CREATE INDEX suppliers_lot_inn ON suppliers(lot_id,supplier_inn)")
            connection.execute("CREATE INDEX suppliers_inn ON suppliers(supplier_inn)")
            connection.execute("CREATE INDEX items_code_product ON items(okpd2_code,product_name)")
        result = {"schema_version": 2 if include_history else 1,
                  "history_included": include_history,
                  "created_at": datetime.now(timezone.utc).isoformat(),
                  "source": {"archive": str(archive_path.resolve()), "sha256": archive_hash,
                             "size": signature[1], "members": manifest},
                  **_summarize(connection, tables)}
        if _source_signature(archive_path) != signature:
            raise ValueError("Source archive changed while building; outputs were not published")
        connection.commit()
        connection.close()
        connection = None
        with temporary_database.open("rb") as stream:
            os.fsync(stream.fileno())
        fd, name = tempfile.mkstemp(prefix=f".{audit_path.name}.", suffix=".tmp", dir=audit_path.parent)
        temporary_audit = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary_database, database_path)
        else:
            # A hard link publishes the finished file atomically and fails if
            # another writer creates the target, unlike rename/replace on POSIX.
            os.link(temporary_database, database_path)
            temporary_database.unlink()
        temporary_database = None
        os.replace(temporary_audit, audit_path)
        temporary_audit = None
        return result
    finally:
        if connection is not None:
            connection.close()
        if temporary_database is not None:
            temporary_database.unlink(missing_ok=True)
            Path(f"{temporary_database}-journal").unlink(missing_ok=True)
        if temporary_audit is not None:
            temporary_audit.unlink(missing_ok=True)
        os.close(lock_fd)
        lock_path.unlink(missing_ok=True)
