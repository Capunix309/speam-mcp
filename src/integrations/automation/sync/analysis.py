"""Formulas and labels for the multi-sprint Analysis dashboard."""

from __future__ import annotations

from ..core.sheets.client import Formula


SUMMARY_HEADERS = [
    "Hours logged", "Worklog entries", "Jira tasks", "Done",
    "In progress", "Contributors", "Story points",
]
HOW_TO_READ_HEADER = "How to read this analysis"
HOW_TO_READ = [
    "Assigned effort is shown in story points because Jira has no per-person hour allocation; unassigned issue points are split evenly across the configured team.",
    "For partial work, each person's share of an issue's story points equals their logged hours ÷ total issue hours × issue story points.",
    "The burn-down compares the ideal line, the last-worklog completion proxy, and Jira's resolution-date line.",
]

EFFORT_HEADERS = {
    0: "Person",
    1: "Min",
    2: "Task at Min",
    7: "Mean",
    8: "Max",
    9: "Task at Max",
}

def budget_table(team_members: tuple[str, ...], first_row: int = 4) -> list[list[Formula | str]]:
    """Build a sprint budget with per-person value/delta columns and a grand total."""
    headers = ["Sprint", "Expected (team)"]
    subheaders = ["", ""]
    value_columns: list[int] = []
    delta_columns: list[int] = []
    for index, member in enumerate(team_members):
        value_columns.append(2 + index * 2)
        delta_columns.append(3 + index * 2)
        headers.extend([member, ""])
        subheaders.extend(["Value", "Delta"])
    total_value_column = 2 + len(team_members) * 2
    total_delta_column = total_value_column + 1
    last_person_column = _column_letter(total_value_column - 1)
    headers.extend(["Total", ""])
    subheaders.extend(["Value", "Delta"])
    rows: list[list[Formula | str]] = [headers, subheaders]
    for row in range(first_row, first_row + 5):
        sprint = row - first_row
        expected = (
            f'=IFERROR(IF(INDEX(\'Sprint Setup\'!$D$3:$D$100;MATCH($A{row};'
            f'\'Sprint Setup\'!$A$3:$A$100;0))="";"";'
            f'INDEX(\'Sprint Setup\'!$D$3:$D$100;MATCH($A{row};\'Sprint Setup\'!$A$3:$A$100;0))*'
            f'\'Sprint Setup\'!$G$1*COUNTA($C$2:${last_person_column}$2));"")'
        )
        values: list[Formula | str] = [f"Sprint {sprint}", Formula(expected)]
        for value_column in value_columns:
            letter = _column_letter(value_column)
            values.append(Formula(
                f'=SUMIFS(Worklogs!$AF$2:$AF;Worklogs!$F$2:$F;{letter}$2;'
                f'Worklogs!$AG$2:$AG;$A{row})'
            ))
            all_values = ";".join(f"{_column_letter(column)}{row}" for column in value_columns)
            values.append(Formula(
                f'=IF(SUM({all_values})=0;0;{letter}{row}-$B{row}/COUNTA($C$2:${last_person_column}$2))'
            ))
        values.extend([
            Formula("=" + "+".join(f"{_column_letter(column)}{row}" for column in value_columns)),
            Formula("=" + "+".join(f"{_column_letter(column)}{row}" for column in delta_columns)),
        ])
        rows.append(values)
    total_row = first_row + 5
    totals: list[Formula | str] = ["Total", Formula(f"=SUM(B{first_row}:B{total_row - 1})")]
    for value_column, delta_column in zip(value_columns, delta_columns):
        totals.extend([
            Formula(f"=SUM({_column_letter(value_column)}{first_row}:{_column_letter(value_column)}{total_row - 1})"),
            Formula(f"=SUM({_column_letter(delta_column)}{first_row}:{_column_letter(delta_column)}{total_row - 1})"),
        ])
    totals.extend([
        Formula(f"=SUM({_column_letter(total_value_column)}{first_row}:{_column_letter(total_value_column)}{total_row - 1})"),
        Formula(f"=SUM({_column_letter(total_delta_column)}{first_row}:{_column_letter(total_delta_column)}{total_row - 1})"),
    ])
    rows.append(totals)
    return rows


def _column_letter(index: int) -> str:
    """Convert a zero-based column index to its A1 column label."""
    result = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def daily_date_formulas(first_row: int = 2, last_row: int = 1000) -> list[list[Formula]]:
    """Reuse the selector-aware calendar axis already generated for the burn-down."""
    return [[Formula(f'=IF(A{row}="";"";A{row})')] for row in range(first_row, last_row + 1)]


def daily_member_formulas(team_members: tuple[str, ...], first_row: int = 2,
                          last_row: int = 1000) -> list[list[Formula]]:
    """Build selector-aware daily member-hours series in Burndown Data columns G:L."""
    rows = []
    for row in range(first_row, last_row + 1):
        line: list[Formula] = []
        for column in range(7, 12):
            letter = chr(ord("A") + column - 1)
            line.append(Formula(
                f'=IF($F{row}="";"";IF(Analysis!$B$12="All sprints";'
                f'SUMIFS(Worklogs!$AF$2:$AF;Worklogs!$F$2:$F;{letter}$1;Worklogs!$D$2:$D;"<"&$F{row}+1);'
                f'SUMIFS(Worklogs!$AF$2:$AF;Worklogs!$F$2:$F;{letter}$1;'
                f'Worklogs!$D$2:$D;"<"&$F{row}+1;'
                f'Worklogs!$AG$2:$AG;Analysis!$B$12)))'
            ))
        line.append(Formula(f'=IF($F{row}="";"";SUM(G{row}:K{row}))'))
        rows.append(line)
    return rows


def summary_formulas() -> list[Formula]:
    """Return formulas for the summary cards after the existing Hours Logged cell."""
    selected = 'Analysis!$B$12'
    all_sprints = f'{selected}="All sprints"'
    return [
        Formula(
            f'=IF({all_sprints};COUNTA(Worklogs!$A$2:$A);'
            f'COUNTIFS(Worklogs!$AG$2:$AG;{selected};Worklogs!$A$2:$A;"<>"))'
        ),
        Formula(
            f'=IF({all_sprints};COUNTIF(\'Task Analysis\'!$A$2:$A$1000;"<>");'
            f'COUNTIFS(\'Task Analysis\'!$A$2:$A$1000;"<>";\'Task Analysis\'!$J$2:$J$1000;{selected}))'
        ),
        _task_status_count("Done", all_sprints, selected),
        _task_status_count("In Progress", all_sprints, selected),
        Formula(
            '=COUNTIF(\'Hours by Person\'!$C$2:$C$6;">0")'
        ),
        Formula(
            f'=IF({all_sprints};SUM(\'Task Analysis\'!$E$2:$E$1000);'
            f'SUMIFS(\'Task Analysis\'!$E$2:$E$1000;\'Task Analysis\'!$J$2:$J$1000;{selected}))'
        ),
    ]


def hours_logged_formula() -> Formula:
    """Return the total-hours card formula for the selected sprint."""
    return Formula(
        '=IF($B$12="All sprints";SUM(Worklogs!$AF$2:$AF);'
        'SUMIFS(Worklogs!$AF$2:$AF;Worklogs!$AG$2:$AG;$B$12))'
    )


def effort_column_formulas() -> dict[int, list[Formula]]:
    """Map visible Analysis columns to Hours by Person outputs."""
    source_columns = {0: "A", 1: "G", 2: "H", 7: "K", 8: "I", 9: "J"}
    return {
        column: [Formula(f"='Hours by Person'!{source_column}{row}") for row in range(2, 8)]
        for column, source_column in source_columns.items()
    }


def _task_status_count(status: str, all_sprints: str, selected: str) -> Formula:
    return Formula(
        f'=IF({all_sprints};COUNTIF(\'Task Analysis\'!$C$2:$C$1000;"{status}");'
        f'COUNTIFS(\'Task Analysis\'!$C$2:$C$1000;"{status}";'
        f'\'Task Analysis\'!$J$2:$J$1000;{selected}))'
    )
