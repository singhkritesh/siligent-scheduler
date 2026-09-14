"""Parse and validate de-identified CSV/XLSX scheduling simulation inputs."""

from __future__ import annotations

import csv
import io
import posixpath
import re
import zipfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from xml.etree import ElementTree


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_XLSX_BYTES = 25 * 1024 * 1024
MAX_ROWS = 1000
MAX_COLUMNS = 40

REQUIRED_COLUMNS = (
    "request_id",
    "patient_ref",
    "procedure_code",
)
OPTIONAL_COLUMNS = (
    "difficulty",
    "priority",
    "availability_start_date",
    "availability_end_date",
    "daily_start_time",
    "daily_end_time",
    "request_received_at",
    "condition_tag",
    "preferred_doctor_code",
    "established_doctor_code",
    "request_source",
    "scheduled_minutes",
    "expected_production_cents",
    "status",
    "locked",
    "allow_reserved_block_override",
)
ALLOWED_COLUMNS = frozenset(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)
PROHIBITED_COLUMNS = frozenset(
    {
        "patient_name",
        "name",
        "medical_record_number",
        "mrn",
        "date_of_birth",
        "dob",
        "phone",
        "email",
        "address",
        "condition",
        "notes",
        "clinical_notes",
    }
)
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


class SimulationImportError(ValueError):
    """Safe validation error suitable for returning to an authenticated user."""


def _normalize_header(value: object) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower())).strip("_")


def _column_number(reference: str) -> int:
    letters = "".join(character for character in reference if character.isalpha()).upper()
    number = 0
    for character in letters:
        number = number * 26 + ord(character) - 64
    return number


def _excel_serial(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise SimulationImportError("Excel date/time cells must contain valid values") from error


def _excel_date(value: str, *, date_1904: bool) -> datetime:
    origin = datetime(1904, 1, 1) if date_1904 else datetime(1899, 12, 30)
    return origin + timedelta(days=_excel_serial(value))


def _xlsx_rows(content: bytes) -> tuple[list[list[str]], bool]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as error:
        raise SimulationImportError("The .xlsx file is damaged or is not an Excel workbook") from error
    with archive:
        entries = archive.infolist()
        if len(entries) > 250 or sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_XLSX_BYTES:
            raise SimulationImportError("The Excel workbook is too large or complex")
        for entry in entries:
            normalized = posixpath.normpath(entry.filename)
            if normalized.startswith("../") or normalized.startswith("/"):
                raise SimulationImportError("The Excel workbook contains an unsafe path")
        try:
            workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            relationships_root = ElementTree.fromstring(
                archive.read("xl/_rels/workbook.xml.rels")
            )
        except (KeyError, ElementTree.ParseError) as error:
            raise SimulationImportError("The Excel workbook structure is incomplete") from error

        main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        package_rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        workbook_properties = workbook_root.find(f"{{{main_ns}}}workbookPr")
        date_1904 = bool(
            workbook_properties is not None
            and workbook_properties.attrib.get("date1904", "false").lower() in {"1", "true"}
        )
        sheet = workbook_root.find(f".//{{{main_ns}}}sheet")
        if sheet is None:
            raise SimulationImportError("The Excel workbook contains no worksheet")
        relationship_id = sheet.attrib.get(f"{{{rel_ns}}}id")
        relationship_targets = {
            item.attrib.get("Id"): item.attrib.get("Target")
            for item in relationships_root.findall(f"{{{package_rel_ns}}}Relationship")
            if item.attrib.get("TargetMode", "Internal") != "External"
        }
        target = relationship_targets.get(relationship_id)
        if not target:
            raise SimulationImportError("The first Excel worksheet cannot be read")
        clean_target = target.lstrip("/")
        worksheet_path = posixpath.normpath(
            clean_target if clean_target.startswith("xl/") else posixpath.join("xl", clean_target)
        )
        if not worksheet_path.startswith("xl/"):
            raise SimulationImportError("The Excel worksheet path is unsafe")

        shared_strings: list[str] = []
        try:
            shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall(f"{{{main_ns}}}si"):
                shared_strings.append(
                    "".join(node.text or "" for node in item.iter(f"{{{main_ns}}}t"))
                )
        except KeyError:
            pass
        except ElementTree.ParseError as error:
            raise SimulationImportError("The Excel shared-text table is invalid") from error

        try:
            worksheet_root = ElementTree.fromstring(archive.read(worksheet_path))
        except (KeyError, ElementTree.ParseError) as error:
            raise SimulationImportError("The first Excel worksheet is invalid") from error
        rows: list[list[str]] = []
        for row_node in worksheet_root.findall(f".//{{{main_ns}}}sheetData/{{{main_ns}}}row"):
            cells: dict[int, str] = {}
            for cell in row_node.findall(f"{{{main_ns}}}c"):
                if cell.find(f"{{{main_ns}}}f") is not None:
                    raise SimulationImportError("Formula cells are not supported in simulation uploads")
                reference = cell.attrib.get("r", "")
                column = _column_number(reference)
                if column < 1 or column > MAX_COLUMNS:
                    raise SimulationImportError(f"Excel uploads may contain at most {MAX_COLUMNS} columns")
                cell_type = cell.attrib.get("t", "n")
                value_node = cell.find(f"{{{main_ns}}}v")
                raw = value_node.text if value_node is not None and value_node.text is not None else ""
                if cell_type == "s" and raw:
                    try:
                        raw = shared_strings[int(raw)]
                    except (IndexError, ValueError) as error:
                        raise SimulationImportError("The Excel shared-text table is inconsistent") from error
                elif cell_type == "inlineStr":
                    raw = "".join(
                        node.text or "" for node in cell.iter(f"{{{main_ns}}}t")
                    )
                elif cell_type == "b":
                    raw = "true" if raw == "1" else "false"
                cells[column] = raw.strip()
            if cells:
                last_column = max(cells)
                rows.append([cells.get(column, "") for column in range(1, last_column + 1)])
        return rows, date_1904


def _csv_rows(content: bytes) -> list[list[str]]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SimulationImportError("CSV files must use UTF-8 encoding") from error
    try:
        return [list(row) for row in csv.reader(io.StringIO(decoded)) if any(cell.strip() for cell in row)]
    except csv.Error as error:
        raise SimulationImportError("The CSV file could not be parsed") from error


def _date_value(value: str, *, date_1904: bool) -> date:
    value = value.strip()
    try:
        return date.fromisoformat(value)
    except ValueError:
        try:
            return _excel_date(value, date_1904=date_1904).date()
        except (SimulationImportError, OverflowError) as error:
            raise SimulationImportError("dates must use YYYY-MM-DD") from error


def _time_value(value: str, *, date_1904: bool) -> time:
    value = value.strip()
    try:
        return time.fromisoformat(value).replace(second=0, microsecond=0)
    except ValueError:
        try:
            converted = _excel_date(value, date_1904=date_1904)
            return converted.time().replace(second=0, microsecond=0)
        except (SimulationImportError, OverflowError) as error:
            raise SimulationImportError("times must use HH:MM") from error


def _integer_value(value: str, field_name: str, *, minimum: int = 0) -> int | None:
    if not value.strip():
        return None
    try:
        number = float(value)
    except ValueError as error:
        raise SimulationImportError(f"{field_name} must be a whole number") from error
    if not number.is_integer() or number < minimum:
        raise SimulationImportError(f"{field_name} must be a whole number of at least {minimum}")
    return int(number)


def parse_simulation_upload(
    content: bytes,
    filename: str,
    *,
    today: date,
    horizon_days: int,
) -> tuple[str, list[dict[str, object]]]:
    """Return file format and normalized rows, or raise a safe validation error."""

    if not content:
        raise SimulationImportError("Choose a non-empty CSV or XLSX file")
    if len(content) > MAX_UPLOAD_BYTES:
        raise SimulationImportError("Simulation uploads are limited to 5 MB")
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".csv":
        file_format = "csv"
        raw_rows = _csv_rows(content)
        date_1904 = False
    elif suffix == ".xlsx":
        file_format = "xlsx"
        raw_rows, date_1904 = _xlsx_rows(content)
    else:
        raise SimulationImportError("Upload a .csv or .xlsx file")
    if len(raw_rows) < 2:
        raise SimulationImportError("The upload needs a header and at least one data row")
    headers = [_normalize_header(value) for value in raw_rows[0]]
    if any(not header for header in headers):
        raise SimulationImportError("Every populated spreadsheet column needs a header")
    if len(headers) != len(set(headers)):
        raise SimulationImportError("Spreadsheet headers must be unique")
    prohibited = sorted(set(headers) & PROHIBITED_COLUMNS)
    if prohibited:
        raise SimulationImportError(
            "Direct identifiers and free text are prohibited: " + ", ".join(prohibited)
        )
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise SimulationImportError("Missing required columns: " + ", ".join(missing))
    unknown = sorted(set(headers) - ALLOWED_COLUMNS)
    if unknown:
        raise SimulationImportError("Unsupported columns: " + ", ".join(unknown))
    if len(raw_rows) - 1 > MAX_ROWS:
        raise SimulationImportError(f"Simulation uploads are limited to {MAX_ROWS} rows")

    normalized: list[dict[str, object]] = []
    seen_request_ids: set[str] = set()
    horizon_end = today + timedelta(days=horizon_days)
    for row_number, values in enumerate(raw_rows[1:], 2):
        if len(values) > len(headers) and any(value.strip() for value in values[len(headers) :]):
            raise SimulationImportError(
                f"Row {row_number}: data appears in a column without an approved header"
            )
        item = {
            header: (values[index].strip() if index < len(values) else "")
            for index, header in enumerate(headers)
        }
        prefix = f"Row {row_number}"
        request_id = str(item["request_id"])
        patient_ref = str(item["patient_ref"])
        if not IDENTIFIER_PATTERN.fullmatch(request_id):
            raise SimulationImportError(f"{prefix}: request_id must be an opaque identifier")
        if request_id in seen_request_ids:
            raise SimulationImportError(f"{prefix}: request_id is duplicated")
        seen_request_ids.add(request_id)
        if not IDENTIFIER_PATTERN.fullmatch(patient_ref):
            raise SimulationImportError(f"{prefix}: patient_ref must be an opaque identifier")
        procedure_code = str(item["procedure_code"]).lower()
        if not CODE_PATTERN.fullmatch(procedure_code):
            raise SimulationImportError(f"{prefix}: procedure_code is invalid")
        received_value = str(item.get("request_received_at", "")).strip()
        received_at: datetime | None = None
        if received_value:
            try:
                received_at = datetime.fromisoformat(received_value)
            except ValueError:
                try:
                    received_at = _excel_date(received_value, date_1904=date_1904)
                except (SimulationImportError, OverflowError) as error:
                    raise SimulationImportError(f"{prefix}: request_received_at is invalid") from error
            if received_at.tzinfo is not None and received_at.utcoffset() is not None:
                received_at = received_at.astimezone(UTC)
            else:
                received_at = received_at.replace(tzinfo=UTC)

        difficulty = str(item.get("difficulty", "") or "standard").lower()
        if difficulty not in {"standard", "complex"}:
            raise SimulationImportError(f"{prefix}: difficulty must be standard or complex")
        priority = str(item.get("priority", "") or "routine").lower()
        if priority not in {"routine", "priority", "urgent"}:
            raise SimulationImportError(f"{prefix}: priority must be routine, priority, or urgent")
        start_date_value = str(item.get("availability_start_date", "")).strip()
        end_date_value = str(item.get("availability_end_date", "")).strip()
        start_time_value = str(item.get("daily_start_time", "")).strip()
        end_time_value = str(item.get("daily_end_time", "")).strip()
        availability_values = (
            start_date_value, end_date_value, start_time_value, end_time_value
        )
        if any(availability_values) and not all(availability_values):
            raise SimulationImportError(
                f"{prefix}: custom availability requires both dates and both daily times"
            )
        availability_assumption = "custom_window" if all(availability_values) else "any_opening"
        start_date = (
            _date_value(start_date_value, date_1904=date_1904)
            if start_date_value
            else max(today, received_at.date() if received_at else today)
        )
        end_date = (
            _date_value(end_date_value, date_1904=date_1904)
            if end_date_value
            else horizon_end
        )
        start_time = (
            _time_value(start_time_value, date_1904=date_1904)
            if start_time_value
            else time.min
        )
        end_time = (
            _time_value(end_time_value, date_1904=date_1904)
            if end_time_value
            else time(23, 59)
        )
        if start_date < today or start_date > horizon_end or end_date > horizon_end:
            raise SimulationImportError(
                f"{prefix}: availability must fall within the rolling {horizon_days}-day horizon"
            )
        if end_date < start_date:
            raise SimulationImportError(f"{prefix}: availability_end_date precedes the start")
        if end_time <= start_time:
            raise SimulationImportError(f"{prefix}: daily_end_time must be after daily_start_time")
        condition_tag = str(item.get("condition_tag", "")).lower()
        if condition_tag and not CODE_PATTERN.fullmatch(condition_tag):
            raise SimulationImportError(f"{prefix}: condition_tag must be a controlled code, not free text")
        for doctor_field in ("preferred_doctor_code", "established_doctor_code"):
            doctor_code = str(item.get(doctor_field, ""))
            if doctor_code and not CODE_PATTERN.fullmatch(doctor_code):
                raise SimulationImportError(f"{prefix}: {doctor_field} is invalid")
        if str(item.get("status", "requested")).lower() not in {"", "requested"}:
            raise SimulationImportError(f"{prefix}: simulation inputs must have requested status")
        if str(item.get("locked", "false")).lower() not in {"", "false", "0", "no"}:
            raise SimulationImportError(f"{prefix}: input requests cannot already be locked")
        if str(item.get("allow_reserved_block_override", "false")).lower() not in {
            "", "false", "0", "no"
        }:
            raise SimulationImportError(f"{prefix}: simulations cannot override reserved capacity")
        scheduled_minutes = _integer_value(
            str(item.get("scheduled_minutes", "")), "scheduled_minutes", minimum=1
        )
        expected_production_cents = _integer_value(
            str(item.get("expected_production_cents", "")),
            "expected_production_cents",
            minimum=0,
        )
        if received_at is None:
            received_at = datetime.combine(start_date, time.min, tzinfo=UTC) - timedelta(days=1)
        received_date = received_at.date()
        received_local_time = received_at.timetz().replace(tzinfo=None)
        if received_date > start_date:
            raise SimulationImportError(
                f"{prefix}: availability_start_date cannot precede request_received_at"
            )
        if received_date == end_date and received_local_time >= end_time:
            raise SimulationImportError(
                f"{prefix}: availability ends before the request can be scheduled"
            )
        request_source = str(item.get("request_source", "")).lower()
        if request_source not in {"", "phone", "front_desk", "patient_portal", "walk_in"}:
            raise SimulationImportError(
                f"{prefix}: request_source must be phone, front_desk, patient_portal, or walk_in"
            )
        normalized.append(
            {
                "row_number": row_number,
                "request_id": request_id,
                "patient_ref": patient_ref,
                "request_received_at": received_at,
                "procedure_code": procedure_code,
                "condition_tag": condition_tag,
                "difficulty": difficulty,
                "priority": priority,
                "availability_start_date": start_date,
                "availability_end_date": end_date,
                "daily_start_time": start_time,
                "daily_end_time": end_time,
                "availability_assumption": availability_assumption,
                "preferred_doctor_code": str(item.get("preferred_doctor_code", "")).upper(),
                "established_doctor_code": str(item.get("established_doctor_code", "")).upper(),
                "request_source": request_source,
                "scheduled_minutes": scheduled_minutes,
                "uploaded_production_cents": expected_production_cents,
            }
        )
    normalized.sort(key=lambda row: (row["request_received_at"], row["request_id"]))
    return file_format, normalized


def serialize_preview_row(row: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": row["request_id"],
        "patient_ref": row["patient_ref"],
        "procedure_code": row["procedure_code"],
        "condition_tag": row["condition_tag"],
        "difficulty": row["difficulty"],
        "priority": row["priority"],
        "availability_start_date": row["availability_start_date"].isoformat(),
        "availability_end_date": row["availability_end_date"].isoformat(),
        "daily_start_time": row["daily_start_time"].strftime("%H:%M"),
        "daily_end_time": row["daily_end_time"].strftime("%H:%M"),
        "availability_assumption": row["availability_assumption"],
        "preferred_doctor_code": row["preferred_doctor_code"],
    }
