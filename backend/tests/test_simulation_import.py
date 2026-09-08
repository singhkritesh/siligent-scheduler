from __future__ import annotations

import io
import unittest
import zipfile
from datetime import date

from backend.simulation_import import SimulationImportError, parse_simulation_upload


HEADERS = (
    "request_id",
    "patient_ref",
    "procedure_code",
    "difficulty",
    "priority",
    "availability_start_date",
    "availability_end_date",
    "daily_start_time",
    "daily_end_time",
)


def minimal_xlsx(values: list[str], *, formula_column: int | None = None) -> bytes:
    def inline_cell(reference: str, value: str, formula: bool = False) -> str:
        formula_xml = "<f>1+1</f>" if formula else ""
        return f'<c r="{reference}" t="inlineStr">{formula_xml}<is><t>{value}</t></is></c>'

    header_cells = "".join(
        inline_cell(f"{chr(65 + index)}1", value) for index, value in enumerate(HEADERS)
    )
    data_cells = "".join(
        inline_cell(
            f"{chr(65 + index)}2",
            value,
            formula=formula_column == index,
        )
        for index, value in enumerate(values)
    )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData><row r="1">{header_cells}</row><row r="2">{data_cells}</row></sheetData>'
        '</worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Requests" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return output.getvalue()


class SimulationImportTests(unittest.TestCase):
    def test_valid_csv_is_normalized_and_sorted_by_arrival(self) -> None:
        header = ",".join(HEADERS + ("request_received_at", "condition_tag"))
        content = (
            header
            + "\nREQ-2,PAT-2,exam,standard,routine,2026-10-06,2026-10-09,08:00,17:00,2026-09-20T09:00:00-04:00,routine_preventive"
            + "\nREQ-1,PAT-1,cleaning,complex,priority,2026-10-05,2026-10-09,09:00,15:00,2026-09-19T09:00:00-04:00,periodontal_maintenance\n"
        ).encode()
        file_format, rows = parse_simulation_upload(
            content, "requests.csv", today=date(2026, 9, 7), horizon_days=365
        )
        self.assertEqual(file_format, "csv")
        self.assertEqual([row["request_id"] for row in rows], ["REQ-1", "REQ-2"])
        self.assertEqual(rows[0]["availability_start_date"], date(2026, 10, 5))

    def test_direct_identifier_column_is_rejected(self) -> None:
        content = (
            ",".join(HEADERS + ("patient_name",))
            + "\nREQ-1,PAT-1,exam,standard,routine,2026-10-05,2026-10-09,08:00,17:00,Example\n"
        ).encode()
        with self.assertRaisesRegex(SimulationImportError, "Direct identifiers"):
            parse_simulation_upload(
                content, "requests.csv", today=date(2026, 9, 7), horizon_days=365
            )

    def test_data_without_an_approved_header_is_rejected(self) -> None:
        content = (
            ",".join(HEADERS)
            + "\nREQ-1,PAT-1,exam,standard,routine,2026-10-05,2026-10-09,08:00,17:00,unexpected\n"
        ).encode()
        with self.assertRaisesRegex(SimulationImportError, "without an approved header"):
            parse_simulation_upload(
                content, "requests.csv", today=date(2026, 9, 7), horizon_days=365
            )

    def test_availability_cannot_precede_request_arrival(self) -> None:
        content = (
            ",".join(HEADERS + ("request_received_at",))
            + "\nREQ-1,PAT-1,exam,standard,routine,2026-10-05,2026-10-09,08:00,17:00,2026-10-06T09:00:00-04:00\n"
        ).encode()
        with self.assertRaisesRegex(SimulationImportError, "cannot precede"):
            parse_simulation_upload(
                content, "requests.csv", today=date(2026, 9, 7), horizon_days=365
            )

    def test_request_after_last_daily_window_is_rejected(self) -> None:
        content = (
            ",".join(HEADERS + ("request_received_at",))
            + "\nREQ-1,PAT-1,exam,standard,routine,2026-10-05,2026-10-05,08:00,17:00,2026-10-05T17:30:00-04:00\n"
        ).encode()
        with self.assertRaisesRegex(SimulationImportError, "availability ends"):
            parse_simulation_upload(
                content, "requests.csv", today=date(2026, 9, 7), horizon_days=365
            )

    def test_minimal_xlsx_is_accepted(self) -> None:
        values = [
            "REQ-1",
            "PAT-1",
            "exam",
            "standard",
            "routine",
            "2026-10-05",
            "2026-10-09",
            "08:00",
            "17:00",
        ]
        file_format, rows = parse_simulation_upload(
            minimal_xlsx(values),
            "requests.xlsx",
            today=date(2026, 9, 7),
            horizon_days=365,
        )
        self.assertEqual(file_format, "xlsx")
        self.assertEqual(rows[0]["patient_ref"], "PAT-1")

    def test_excel_formula_cells_are_rejected(self) -> None:
        values = [
            "REQ-1",
            "PAT-1",
            "exam",
            "standard",
            "routine",
            "2026-10-05",
            "2026-10-09",
            "08:00",
            "17:00",
        ]
        with self.assertRaisesRegex(SimulationImportError, "Formula cells"):
            parse_simulation_upload(
                minimal_xlsx(values, formula_column=0),
                "requests.xlsx",
                today=date(2026, 9, 7),
                horizon_days=365,
            )


if __name__ == "__main__":
    unittest.main()
