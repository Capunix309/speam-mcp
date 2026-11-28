"""Build and apply one complete sprint update to the existing workbook."""

from __future__ import annotations

from datetime import date
from typing import Any

from ..core.normalize import sheets_serial
from ..core.settings import AutomationSettings
from ..core.sheets.client import Formula, SheetsClient, update_cells_request
from . import analysis, burndown, issue_tables, worklog_table


REQUIRED_SHEETS = {"Worklogs", "Analysis", "Task Analysis", "Person Task Effort", "Hours by Person", "Burndown Data", "Sprint Setup"}


def update_workbook(
    settings: AutomationSettings, sprint_name: str, start_date: date, end_date: date,
    issues: list[dict[str, Any]], worklogs: list[dict[str, Any]], client: SheetsClient | None = None,
) -> dict[str, Any]:
    """Preflight all sheet content, then send a single workbook batch update."""
    client = client or SheetsClient(settings.spreadsheet_id)
    metadata = client.metadata()
    sheets = {
        sheet["properties"]["title"]: sheet["properties"]
        for sheet in metadata.get("sheets", [])
    }
    missing = REQUIRED_SHEETS - sheets.keys()
    if missing:
        raise ValueError(f"The configured workbook is missing sheets: {', '.join(sorted(missing))}.")
    worklog_columns = sheets["Worklogs"]["gridProperties"]["columnCount"]
    worklogs_table = _table_for_sheet(metadata, sheets["Worklogs"]["sheetId"])
    worklog_range = "A1:AI2000" if worklog_columns >= 35 else "A1:AG2000"
    existing_worklogs = client.values("Worklogs", worklog_range)
    worklog_formulas = client.values("Worklogs", worklog_range, "FORMULA")
    task_rows = client.values("Task Analysis", "A1:M1000")
    task_formulas = client.values("Task Analysis", "A1:M1000", "FORMULA")
    person_rows = client.values("Person Task Effort", "A1:J2000")
    person_formulas = client.values("Person Task Effort", "A1:J2000", "FORMULA")
    hours_by_person_rows = client.values("Hours by Person", "A1:L8")
    hours_by_person_formulas = client.values("Hours by Person", "A1:L8", "FORMULA")
    setup_rows = client.values("Sprint Setup", "A1:G100")
    setup_formulas = client.values("Sprint Setup", "A1:G100", "FORMULA")
    analysis_rows = client.values("Analysis", "A1:N28")
    analysis_formulas = client.values("Analysis", "A1:N28", "FORMULA")
    burndown_formulas = client.values("Burndown Data", "A1:L1000", "FORMULA")
    if not existing_worklogs or not task_rows or not person_rows or not setup_rows:
        raise ValueError("One or more workbook tables are missing their header row.")

    worklog_values = worklog_table.refresh_worklogs(existing_worklogs, worklogs, sprint_name)
    task_updates, person_updates = issue_tables.plan_issue_updates(
        task_rows, person_rows, issues, sprint_name, settings,
    )
    setup_values = _sprint_setup(setup_rows, sprint_name, start_date, end_date)
    requests: list[dict[str, Any]] = []
    requests.extend(_changed_literal_requests(
        sheets["Hours by Person"]["sheetId"], 0, 11, [["Std"]],
        hours_by_person_rows, hours_by_person_formulas,
    ))
    requests.extend(_missing_formula_requests(
        sheets["Hours by Person"]["sheetId"], 1, 11,
        [[formula] for formula in analysis.standard_deviation_formulas()],
        [[_cell(hours_by_person_formulas, row, 11)] for row in range(1, 7)],
    ))
    # The original budget occupied rows 1–7 with an empty row 8 before the
    # analysis content. The two-level headers and grand-total row need one
    # additional row; detect the legacy layout so reruns remain idempotent.
    has_budget_subheaders = len(analysis_rows) > 2 and any(
        value == "Value" for value in analysis_rows[2][2:]
    )
    if not has_budget_subheaders:
        requests.append({"insertDimension": {
            "range": {"sheetId": sheets["Analysis"]["sheetId"], "dimension": "ROWS",
                      "startIndex": 8, "endIndex": 9},
            "inheritFromBefore": False,
        }})
        analysis_rows.insert(8, [])
        analysis_formulas.insert(8, [])
    if worklog_columns < 35:
        requests.append({"appendDimension": {
            "sheetId": sheets["Worklogs"]["sheetId"], "dimension": "COLUMNS", "length": 35 - worklog_columns,
        }})
    _extend_rows(requests, sheets["Worklogs"], len(worklog_values))
    old_count = max(0, len(existing_worklogs) - 1)
    body_rows = worklog_values[1:]
    clear_to = max(old_count, len(body_rows))
    body_rows += [[""] * 35 for _ in range(clear_to - len(body_rows))]
    if body_rows:
        requests.extend(_changed_literal_requests(
            sheets["Worklogs"]["sheetId"], 1, 0, body_rows,
            existing_worklogs, worklog_formulas,
        ))
    if worklogs_table is not None:
        requests.append(_resize_table(worklogs_table, len(worklog_values)))
    if worklog_columns < 35:
        requests.extend(_changed_literal_requests(
            sheets["Worklogs"]["sheetId"], 0, 33, [worklog_values[0][33:35]],
            existing_worklogs, worklog_formulas,
        ))

    for row_index, row in task_updates:
        _extend_rows(requests, sheets["Task Analysis"], row_index + 1)
        requests.extend(_missing_formula_requests(
            sheets["Task Analysis"]["sheetId"], row_index, 0, [row],
            [_row_or_empty(task_formulas, row_index, 13)],
        ))
        requests.extend(_changed_literal_requests(
            sheets["Task Analysis"]["sheetId"], row_index, 0, [row], task_rows, task_formulas,
        ))

    for row_index, row in person_updates:
        _extend_rows(requests, sheets["Person Task Effort"], row_index + 1)
        requests.extend(_missing_formula_requests(
            sheets["Person Task Effort"]["sheetId"], row_index, 0, [row],
            [_row_or_empty(person_formulas, row_index, 10)],
        ))
        requests.extend(_changed_literal_requests(
            sheets["Person Task Effort"]["sheetId"], row_index, 0, [row], person_rows, person_formulas,
        ))

    requests.extend(_changed_literal_requests(
        sheets["Sprint Setup"]["sheetId"], 0, 0, setup_values, setup_rows, setup_formulas,
    ))
    analysis_id = sheets["Analysis"]["sheetId"]
    requests.extend(_changed_literal_requests(
        analysis_id, 11, 1, [[sprint_name]], analysis_rows, analysis_formulas,
    ))
    requests.extend(_changed_literal_requests(
        analysis_id, 12, 0, [analysis.SUMMARY_HEADERS], analysis_rows, analysis_formulas,
    ))
    summary_formulas = [[analysis.hours_logged_formula(), *analysis.summary_formulas()]]
    requests.extend(_missing_formula_requests(
        analysis_id, 13, 0, summary_formulas, analysis_formulas[13:14],
    ))
    # Keep the full-precision formula for calculations, but display whole hours.
    requests.append({"repeatCell": {
        "range": {"sheetId": analysis_id, "startRowIndex": 13, "endRowIndex": 14,
                  "startColumnIndex": 0, "endColumnIndex": 1},
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0"}}},
        "fields": "userEnteredFormat.numberFormat",
    }})
    requests.extend(_changed_literal_requests(
        analysis_id, 15, 0, [[analysis.HOW_TO_READ_HEADER]], analysis_rows, analysis_formulas,
    ))
    requests.extend(_changed_literal_requests(
        analysis_id, 16, 0, [[text] for text in analysis.HOW_TO_READ], analysis_rows, analysis_formulas,
    ))
    requests.extend(_changed_literal_requests(
        analysis_id, 20, 0, [[f"Hours per story point — {sprint_name} — finished tasks only"]],
        analysis_rows, analysis_formulas,
    ))
    for column, header in analysis.EFFORT_HEADERS.items():
        requests.extend(_changed_literal_requests(
            analysis_id, 21, column, [[header]], analysis_rows, analysis_formulas,
        ))
    for column, formulas in analysis.effort_column_formulas().items():
        requests.extend(_missing_formula_requests(
            analysis_id, 22, column, [[formula] for formula in formulas],
            [[_cell(analysis_formulas, row, column)] for row in range(22, 28)],
        ))
    budget = analysis.budget_table(settings.team_members)
    budget_values = [["Sprint time budget", *([""] * 13)], *budget]
    requests.extend(_changed_literal_requests(
        analysis_id, 0, 0, budget_values, analysis_rows, analysis_formulas,
    ))
    requests.extend(_missing_formula_requests(
        analysis_id, 0, 0, budget_values, analysis_formulas[:9],
    ))
    burndown_id = sheets["Burndown Data"]["sheetId"]
    daily_headers = [["Date", *settings.team_members, "Team total"]]
    requests.extend(_changed_literal_requests(
        burndown_id, 0, 5, daily_headers, burndown_formulas, burndown_formulas,
    ))
    requests.extend(_budget_number_formats(analysis_id, len(settings.team_members)))
    burn_formulas = burndown.burndown_formulas(last_row=1000)
    date_formulas = analysis.daily_date_formulas(last_row=1000)
    member_formulas = analysis.daily_member_formulas(settings.team_members, last_row=1000)
    daily_formulas = [
        [*burn_formulas[row], *date_formulas[row], *member_formulas[row]]
        for row in range(len(burn_formulas))
    ]
    requests.extend(_missing_formula_requests(
        burndown_id, 1, 0, daily_formulas, burndown_formulas[1:],
    ))
    requests.extend(_date_formats(sheets, max(2, clear_to + 1)))
    client.apply(requests)
    return {
        "sprint": sprint_name,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "issues_updated": len(issues),
        "worklogs_in_window": len(worklogs),
        "worklog_hours": round(sum(float(item["hours"]) for item in worklogs), 2),
        "analysis_selection": sprint_name,
    }


def _row_or_empty(rows: list[list[Any]], row_index: int, width: int) -> list[Any]:
    """Return a padded row from a values.get result."""
    if row_index >= len(rows):
        return [""] * width
    row = list(rows[row_index][:width])
    row.extend([""] * (width - len(row)))
    return row


def _cell(rows: list[list[Any]], row_index: int, column_index: int) -> Any:
    """Read one possibly absent cell from a ragged values.get result."""
    if row_index >= len(rows) or column_index >= len(rows[row_index]):
        return ""
    return rows[row_index][column_index]


def _is_formula(value: Any) -> bool:
    """Identify formula strings returned by Sheets with valueRenderOption=FORMULA."""
    return isinstance(value, str) and value.startswith("=")


def _missing_formula_requests(
    sheet_id: int,
    start_row: int,
    start_column: int,
    desired_rows: list[list[Any]],
    existing_formula_rows: list[list[Any]],
) -> list[dict[str, Any]]:
    """Write only formula cells that are currently blank, coalescing rectangular runs."""
    row_spans: dict[tuple[int, int], list[tuple[int, list[Any]]]] = {}
    for row_offset, desired in enumerate(desired_rows):
        existing = existing_formula_rows[row_offset] if row_offset < len(existing_formula_rows) else []
        column = 0
        while column < len(desired):
            current = existing[column] if column < len(existing) else ""
            # Existing formulas belong to the workbook. Only seed a genuinely
            # blank cell; a different formula may be an intentional user edit.
            missing = isinstance(desired[column], Formula) and current in (None, "")
            if not missing:
                column += 1
                continue
            first = column
            cells = []
            while column < len(desired):
                current = existing[column] if column < len(existing) else ""
                if not isinstance(desired[column], Formula) or current not in (None, ""):
                    break
                cells.append(desired[column])
                column += 1
            row_spans.setdefault((first, column), []).append((row_offset, cells))

    requests: list[dict[str, Any]] = []
    for (first_column, _), rows in row_spans.items():
        rows.sort(key=lambda item: item[0])
        run: list[list[Any]] = []
        run_start = previous = -1
        for row_offset, cells in rows:
            if run and row_offset != previous + 1:
                requests.append(update_cells_request(
                    sheet_id, start_row + run_start, start_column + first_column, run,
                ))
                run = []
            if not run:
                run_start = row_offset
            run.append(cells)
            previous = row_offset
        if run:
            requests.append(update_cells_request(
                sheet_id, start_row + run_start, start_column + first_column, run,
            ))
    return requests


def _changed_literal_requests(
    sheet_id: int,
    start_row: int,
    start_column: int,
    desired_rows: list[list[Any]],
    existing_values: list[list[Any]],
    existing_formulas: list[list[Any]],
) -> list[dict[str, Any]]:
    """Write changed literal cells only; never replace an existing formula with its result."""
    requests: list[dict[str, Any]] = []
    for row_offset, desired in enumerate(desired_rows):
        changed: list[tuple[int, Any]] = []
        for column_offset, value in enumerate(desired):
            if isinstance(value, Formula) or _is_formula(
                _cell(existing_formulas, start_row + row_offset, start_column + column_offset)
            ):
                continue
            current = _cell(existing_values, start_row + row_offset, start_column + column_offset)
            if current != value and not (current in (None, "") and value in (None, "")):
                changed.append((column_offset, value))
        index = 0
        while index < len(changed):
            first_offset, first_value = changed[index]
            cells = [first_value]
            previous = first_offset
            index += 1
            while index < len(changed) and changed[index][0] == previous + 1:
                previous, value = changed[index]
                cells.append(value)
                index += 1
            requests.append(update_cells_request(
                sheet_id, start_row + row_offset, start_column + first_offset, [cells],
            ))
    return requests


def _sprint_setup(existing: list[list[Any]], sprint_name: str, start_date: date, end_date: date) -> list[list[Any]]:
    """Update the selector list and store the resolved reporting window."""
    rows = [list(row[:7]) + [""] * max(0, 7 - len(row)) for row in existing]
    rows += [[""] * 7 for _ in range(100 - len(rows))]
    rows[0][0:4] = [rows[0][0] or "Sprint options", "Start date", "End date", "Duration (weeks)"]
    rows[0][5:7] = [rows[0][5] or "Expected hours per week", rows[0][6] or 13]
    found = None
    first_empty = None
    for index in range(1, len(rows)):
        if rows[index][0] == sprint_name:
            found = index
            break
        if not rows[index][0] and first_empty is None:
            first_empty = index
    target = found if found is not None else first_empty
    if target is None:
        raise ValueError("Sprint Setup has no free rows for another sprint.")
    rows[target][0] = sprint_name
    rows[target][1] = sheets_serial(start_date)
    rows[target][2] = sheets_serial(end_date)
    return rows


def _budget_number_formats(analysis_id: int, member_count: int = 5) -> list[dict[str, Any]]:
    """Set numeric display formats without changing colors or other styling."""
    first_person_column = 2
    total_value_column = first_person_column + member_count * 2
    last_column = total_value_column + 2
    requests = [{"repeatCell": {
        "range": {"sheetId": analysis_id, "startRowIndex": 3, "endRowIndex": 9,
                  "startColumnIndex": 1, "endColumnIndex": last_column},
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0.0"}}},
        "fields": "userEnteredFormat.numberFormat",
    }}]
    delta_columns = [first_person_column + i * 2 + 1 for i in range(member_count)] + [total_value_column + 1]
    for delta_column in delta_columns:
        requests.append({"repeatCell": {
            "range": {"sheetId": analysis_id, "startRowIndex": 3, "endRowIndex": 9,
                      "startColumnIndex": delta_column, "endColumnIndex": delta_column + 1},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "+0.0;-0.0;0.0"}}},
            "fields": "userEnteredFormat.numberFormat",
        }})
    return requests


def _extend_rows(requests: list[dict[str, Any]], sheet: dict[str, Any], required_rows: int) -> None:
    """Grow a sheet only when a table exceeds its current grid."""
    current = sheet["gridProperties"]["rowCount"]
    if required_rows > current:
        requests.append({"appendDimension": {
            "sheetId": sheet["sheetId"], "dimension": "ROWS", "length": required_rows - current,
        }})
        sheet["gridProperties"]["rowCount"] = required_rows


def _table_for_sheet(metadata: dict[str, Any], sheet_id: int) -> dict[str, Any] | None:
    """Return the unique Google Sheets table attached to a sheet, if present."""
    matches = [table for table in metadata.get("tables", [])
               if table.get("range", {}).get("sheetId") == sheet_id]
    if len(matches) > 1:
        raise ValueError("The Worklogs sheet has multiple Google Sheets tables; refusing to resize them.")
    if matches and matches[0].get("range", {}).get("startRowIndex", 0) != 0:
        raise ValueError("The Worklogs table must start in the first row to sync safely.")
    return matches[0] if matches else None


def _resize_table(table: dict[str, Any], row_count: int) -> dict[str, Any]:
    """Resize the Worklogs table vertically without absorbing sync metadata columns."""
    table_range = dict(table["range"])
    table_range["endRowIndex"] = max(1, row_count)
    return {
        "updateTable": {
            "table": {"tableId": table["tableId"], "range": table_range},
            "fields": "range",
        }
    }


def _date_formats(sheets: dict[str, dict[str, Any]], last_worklog_row: int) -> list[dict[str, Any]]:
    """Set date number formats for values written as Sheets serial numbers."""
    return [
        {"repeatCell": {
            "range": {"sheetId": sheets["Worklogs"]["sheetId"], "startRowIndex": 1,
                      "endRowIndex": max(2, last_worklog_row), "startColumnIndex": 3, "endColumnIndex": 4},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE_TIME", "pattern": "yyyy-mm-dd hh:mm"}}},
            "fields": "userEnteredFormat.numberFormat",
        }},
        {"repeatCell": {
            "range": {"sheetId": sheets["Task Analysis"]["sheetId"], "startRowIndex": 1,
                      "endRowIndex": sheets["Task Analysis"]["gridProperties"]["rowCount"],
                      "startColumnIndex": 8, "endColumnIndex": 9},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}},
            "fields": "userEnteredFormat.numberFormat",
        }},
        {"repeatCell": {
            "range": {"sheetId": sheets["Sprint Setup"]["sheetId"], "startRowIndex": 1,
                      "endRowIndex": 100, "startColumnIndex": 1, "endColumnIndex": 3},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}},
            "fields": "userEnteredFormat.numberFormat",
        }},
    ]
