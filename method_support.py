"""Shared result and worksheet operations for the method scripts."""

import json
import os
import re
from copy import copy
from datetime import datetime
from itertools import chain
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

RESULT_PATH_ENV = "FP_DATAHELPER_RESULT_PATH"
CANCEL_PATH_ENV = "FP_DATAHELPER_CANCEL_PATH"
METHOD_CANCELLED_EXIT_CODE = 130
SORT_SOURCE_NAME = "_FPDataHelper_SortSources"


class MethodCancelled(InterruptedError):
    """The user cancelled the method before saving its result."""


def find_header_row(sheet, predicate, *, column=None, max_rows=20, fallback=0):
    """Return the first matching header row as a zero-based index."""
    bounds = {} if column is None else {"min_col": column + 1, "max_col": column + 1}
    rows = sheet.iter_rows(max_row=min(sheet.max_row, max_rows), values_only=True, **bounds)
    for index, row in enumerate(rows):
        if any(predicate(value) for value in row):
            return index
    return fallback


def is_cas_header(value):
    if not isinstance(value, str):
        return False
    label = re.sub(r"[\s._/\-:：#]+", "", value.casefold())
    return label in {
        "cas", "cas号", "cas编号", "cas登记号", "casno", "casnumber", "casrn",
        "casregistry", "casregistryno", "casregistrynumber", "casregistrationnumber",
    }


def worksheet_column(sheet, letters):
    """Resolve an optional Excel column name to a zero-based index."""
    from openpyxl.utils import column_index_from_string

    if not letters:
        return None
    try:
        column = column_index_from_string(letters.strip())
    except ValueError as error:
        raise ValueError(f"无效的列字母：{letters}") from error
    if column > sheet.max_column:
        raise ValueError(f"列 {letters} 超出工作表范围。")
    return column - 1


def report_output(path):
    if result_path := os.environ.get(RESULT_PATH_ENV):
        Path(result_path).write_text(
            json.dumps({"output_file": str(Path(path).resolve())}), encoding="utf-8"
        )


def check_cancelled():
    if (path := os.environ.get(CANCEL_PATH_ENV)) and Path(path).exists():
        raise MethodCancelled()


def save_workbook(workbook, suffix=""):
    directory = Path("output")
    directory.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    path = directory / f"{timestamp}_{uuid4().hex[:12]}{suffix}.xlsx"
    with NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        workbook.save(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def process_workbook(workbook, process_sheet):
    sources = sort_source_sheets(workbook)
    sheets = [sheet for sheet in workbook.worksheets if sheet.title not in sources]
    skipped = []
    for sheet in sheets:
        try:
            process_sheet(sheet)
        except ValueError as error:
            skipped.append((sheet.title, str(error)))
    if skipped:
        print("跳过的工作表（保留原表）:")
        for title, reason in skipped:
            print(f"  {title}: {reason}")
    if len(skipped) == len(sheets):
        raise ValueError("没有成功处理任何工作表。")


def run_script(main):
    try:
        return main()
    except MethodCancelled:
        print("用户取消处理，未保存结果。")
        return METHOD_CANCELLED_EXIT_CODE
    except (OSError, ValueError) as error:
        print(f"错误：{error}")
        return 1


def _defined_names(workbook):
    names = workbook.defined_names
    return names.definedName if hasattr(names, "definedName") else names.values()


def sort_source_sheets(workbook):
    """Return source tabs retained for formulas after sorting a copy."""
    marker = next((name for name in _defined_names(workbook) if name.name == SORT_SOURCE_NAME), None)
    return {title.replace("''", "'") for title, _ in marker.destinations} if marker else set()


def prepare_sort_values(workbook, filename):
    """Prepare a standalone sort report with fixed values from the input file."""
    from openpyxl import load_workbook

    active = workbook.active
    sources = sort_source_sheets(workbook)
    for title in sources.intersection(workbook.sheetnames):
        workbook.remove(workbook[title])
    names = workbook.defined_names
    if hasattr(names, "definedName"):
        names.delete(SORT_SOURCE_NAME)
    else:
        names.pop(SORT_SOURCE_NAME, None)
    if active is not None and active.title in workbook.sheetnames:
        workbook.active = active

    formulas = [cell for sheet in workbook.worksheets for cell in sheet._cells.values()
                if cell.data_type == "f"]
    if not formulas:
        return {}

    missing = {}
    cached = load_workbook(filename, data_only=True)
    try:
        for cell in formulas:
            title = cell.parent.title
            value = cached[title][cell.coordinate]
            if value.value is None:
                missing.setdefault(title, []).append(cell.coordinate)
                cell.value = "#N/A"
            else:
                cell.value = value.value
                cell.data_type = value.data_type
    finally:
        cached.close()
    print("排序输出使用源文件中已保存的公式计算值。缺少计算值的单元格在结果中标为 #N/A。")
    return missing


def require_saved_sort_values(sheet, missing):
    if coordinates := missing.get(sheet.title):
        raise ValueError(
            f"公式单元格 {coordinates[0]} 没有已保存的计算结果。请先在 Excel 中重算并保存。"
        )


def should_append_columns(workbook):
    """Keep original cell coordinates when the workbook depends on them."""
    if workbook.defined_names:
        return True
    return any(
        getattr(sheet, "defined_names", None)
        or sheet.tables
        or sheet._charts
        or sheet._images
        or sheet._pivots
        or sheet.auto_filter.ref
        or sheet.data_validations.dataValidation
        or sheet.conditional_formatting
        or sheet.freeze_panes
        or sheet.print_area
        or sheet.print_title_cols
        or any(
            dimension.hidden or dimension.min != dimension.max
            for dimension in sheet.column_dimensions.values()
        )
        or any(
            cell.data_type == "f" or cell.hyperlink
            for cell in sheet._cells.values()
        )
        for sheet in workbook.worksheets
    )


def write_columns(sheet, header_row, column, headers, values, *, append=False):
    """Add columns without rebuilding the sheet. Positions use Excel's 1-based indices."""
    from openpyxl.utils import column_index_from_string, get_column_letter

    width = len(headers)
    merges = list(sheet.merged_cells.ranges)
    dimensions = list(sheet.column_dimensions.items())
    right_edge = max(
        [sheet.max_column] + [
            dimension.max or column_index_from_string(key) for key, dimension in dimensions
        ]
    )
    if append or any(
        merge.max_row >= header_row
        and merge.max_col >= column
        and (merge.min_row < header_row or merge.min_col < column)
        for merge in merges
    ):
        column = right_edge + 1
    if max(column - 1, right_edge) + width > 16384:
        raise ValueError("结果超出 Excel 的最大列数。")
    if column <= sheet.max_column:
        last_col = get_column_letter(sheet.max_column)
        last_row = sheet.max_row
        moving_merges = [
            merge for merge in merges
            if merge.min_row >= header_row and merge.max_col >= column
        ]
        for merge in moving_merges:
            sheet.unmerge_cells(str(merge))
        first_col = get_column_letter(column)
        sheet.move_range(f"{first_col}{header_row}:{last_col}{last_row}", cols=width)
        for merge in moving_merges:
            merge.shift(col_shift=width)
            sheet.merge_cells(str(merge))
    ordered_dimensions = sorted(dimensions, key=lambda item: column_index_from_string(item[0]), reverse=True)
    for key, dimension in ordered_dimensions:
        index = column_index_from_string(key)
        if index >= column:
            del sheet.column_dimensions[key]
            shifted = copy(dimension)
            shifted.index = get_column_letter(index + width)
            shifted.min = shifted.max = index + width
            sheet.column_dimensions[shifted.index] = shifted
    for row, items in enumerate(chain((headers,), values), header_row):
        for offset, value in enumerate(items):
            if value is not None:
                sheet.cell(row, column + offset, value)
    return column
