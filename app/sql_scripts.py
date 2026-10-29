"""Running the .sql files under sql/ against the configured database.

This project is database first: the schema is written as SQL, applied by
`flask db-apply`, and read back into app/models/models.py by
`flask generate-models`. That makes a small SQL script runner part of the
application rather than a one-off shell script, so that the test suite can
build its schema from exactly the same files the deployment does.

Deliberately not a migration tool: there is no ledger of what has been applied,
so every statement has to be safe to re-run. See sql/README.md.
"""
from __future__ import annotations

import re
from pathlib import Path

import config

#: sql/ is resolved against the project root, not the working directory — the
#: CLI gets run from anywhere, and a worker's cwd is whatever Docker says it is.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: A line holding nothing but GO: the batch separator sqlcmd and SSMS use.
_GO_LINE = re.compile(r"(?im)^[ \t]*GO[ \t]*(?:--[^\n]*)?$")


class SchemaScriptsNotFound(FileNotFoundError):
    """No directory of .sql files for the dialect that was asked for."""


def script_dir(dialect: str, directory: str | Path | None = None) -> Path:
    base = Path(directory or config.SQL_SCHEMA_DIR)
    if not base.is_absolute():
        base = PROJECT_ROOT / base
    return base / dialect


def script_paths(dialect: str, directory: str | Path | None = None) -> list[Path]:
    """The dialect's scripts, in the order they should run.

    Filename order is the contract — 001_, 002_, … — because it is the one
    ordering that is obvious from `ls` and survives being copied between
    machines.
    """
    folder = script_dir(dialect, directory)
    if not folder.is_dir():
        raise SchemaScriptsNotFound(
            f"No schema scripts for {dialect!r}: {folder} does not exist.")
    return sorted(folder.glob("*.sql"))


def split_statements(sql: str) -> list[str]:
    """Split a script into statements the driver will accept one at a time.

    Most drivers refuse a multi-statement string, so the splitting has to happen
    here. A file containing GO batch separators is split on those alone: T-SQL's
    `IF … BEGIN … END` is a single statement that contains semicolons, so the
    semicolon rule would cut it in half.
    """
    parts = _GO_LINE.split(sql) if _GO_LINE.search(sql) else _split_on_semicolons(sql)
    return [part.strip() for part in parts if _has_code(part)]


def apply_scripts(engine, paths) -> list[tuple[Path, int]]:
    """Run each script in its own transaction; return (path, statement count).

    One transaction per file rather than one for the whole run, so a failure
    half way through leaves the files before it applied and names the one that
    broke — and on a database with transactional DDL, the failing file applies
    none of its statements.
    """
    applied: list[tuple[Path, int]] = []
    for path in paths:
        statements = split_statements(path.read_text(encoding="utf-8"))
        with engine.begin() as connection:
            for statement in statements:
                # exec_driver_sql, not text(): SQLAlchemy would read `:name` and
                # `::type` in DDL as bind parameters and refuse the statement.
                connection.exec_driver_sql(statement)
        applied.append((path, len(statements)))
    return applied


def _split_on_semicolons(sql: str) -> list[str]:
    """Split on `;`, ignoring the ones inside comments and quoted text.

    Quoting follows the SQL standard: a quote character is escaped by doubling
    it. Backslash escapes (MySQL's default) are not recognised, so a string
    literal ending in a backslash would confuse this — put statements like that
    in their own GO batch.
    """
    parts: list[str] = []
    start = index = 0
    length = len(sql)

    while index < length:
        char = sql[index]
        if sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = length if newline == -1 else newline + 1
        elif sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = length if end == -1 else end + 2
        elif char in "'\"`":
            index = _skip_quoted(sql, index, char)
        elif char == "[":
            index = _skip_quoted(sql, index, "]")
        elif char == ";":
            parts.append(sql[start:index])
            index += 1
            start = index
        else:
            index += 1

    parts.append(sql[start:])
    return parts


def _skip_quoted(text: str, start: int, closer: str) -> int:
    """Index just past the closing quote that opens at `start`."""
    index = start + 1
    length = len(text)
    while index < length:
        if text[index] == closer:
            if index + 1 < length and text[index + 1] == closer:
                index += 2                                      # an escaped quote
                continue
            return index + 1
        index += 1
    return length


def _has_code(text: str) -> bool:
    """Whether a fragment is anything more than whitespace and comments."""
    without_comments = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    without_comments = re.sub(r"--[^\n]*", " ", without_comments)
    return bool(without_comments.strip())
