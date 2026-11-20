import openpyxl
import sys
import json
from copy import copy
from math import isfinite
from pathlib import Path

from openpyxl.utils import get_column_letter
from tqdm import tqdm

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from method_support import (
    prepare_sort_values, process_workbook, report_output, require_saved_sort_values,
    run_script, save_workbook,
)

# 列字母生成器（最多支持 3 个字母）
# 关键词（不区分大小写）
TIME_KEYWORDS = ('保留时间', '时间', 'time')
NAME_KEYWORDS = ('名称', 'name', 'compound', 'compounds')

def is_time_header(val):
    if val is None:
        return False
    s = str(val).strip()
    if not s:
        return False
    return any(kw in s.lower() for kw in TIME_KEYWORDS)

def is_name_header(val):
    if val is None:
        return False
    s = str(val).strip()
    if not s:
        return False
    return any(kw in s.lower() for kw in NAME_KEYWORDS)

def detect_header_row(ws, max_rows=20):
    """
    扫描前 max_rows 行，返回同时包含时间列和名称列的行索引（0-based）。
    若未找到，返回 0。
    """
    for r in range(min(max_rows, ws.max_row)):
        row_vals = [cell.value for cell in ws[r+1]]   # openpyxl 行号从 1 开始
        has_time = any(is_time_header(v) for v in row_vals)
        has_name = any(is_name_header(v) for v in row_vals)
        if has_time and has_name:
            return r
    return 0

def detect_groups(header_row_vals, count_param=None):
    """手动指定时按固定组宽切分，否则按表头推断分组。"""
    total_cols = len(header_row_vals)
    if count_param is not None:
        if count_param < 2 or total_cols == 0 or total_cols % count_param:
            raise ValueError("每组至少要有两列，数据列数必须是指定组宽的整数倍。")
        groups = []
        for start in range(0, total_cols, count_param):
            cols = list(range(start, start + count_param))
            times = [col for col in cols if is_time_header(header_row_vals[col])]
            names = [col for col in cols if is_name_header(header_row_vals[col])]
            if len(times) == len(names) == 1 and times[0] != names[0]:
                time_col, name_col = times[0], names[0]
            else:
                time_col, name_col = cols[:2]
            groups.append({
                'time_col': time_col,
                'name_col': name_col,
                'other_cols': [col for col in cols if col not in (time_col, name_col)],
            })
        return groups, count_param

    time_idxs = [i for i, v in enumerate(header_row_vals) if is_time_header(v)]
    name_idxs = [i for i, v in enumerate(header_row_vals) if is_name_header(v)]
    if len(time_idxs) < 2:
        raise ValueError("自动分组需要至少两组时间列，请检查表头或手动指定每组列数。")
    gaps = [right - left for left, right in zip(time_idxs, time_idxs[1:])]
    count = gaps[0]
    if any(gap != count for gap in gaps):
        raise ValueError("时间列间距不一致，请检查表头或手动指定每组列数。")

    # 尝试确定时间列在组内的偏移 offset（0-based），使得每组恰好包含一个名称列且偏移一致
    possible_offsets = []
    for offset in range(count):
        start0 = time_idxs[0] - offset
        if start0 < 0 or start0 + count > total_cols:
            continue
        # 检查每个时间列所在组
        valid = True
        name_rel_offset = None  # 名称列在组内的相对偏移（若存在）
        for t_idx in time_idxs:
            start = t_idx - offset
            if start < 0 or start + count > total_cols:
                valid = False
                break
            # 本组内的所有列索引
            group_cols = list(range(start, start + count))
            # 找本组内的名称列
            group_name_idxs = [c for c in group_cols if c in name_idxs]
            if len(group_name_idxs) != 1:
                valid = False
                break
            # 计算名称列相对偏移
            rel = group_name_idxs[0] - start
            if name_rel_offset is None:
                name_rel_offset = rel
            elif name_rel_offset != rel:
                valid = False
                break
        if valid:
            possible_offsets.append((offset, name_rel_offset))

    if not possible_offsets:
        raise ValueError("无法根据时间列和名称列确定有效的分组，请检查表头列排列或手动指定每组列数。")

    # 取第一个可行的 offset（通常唯一）
    offset, name_rel_offset = possible_offsets[0]

    # 构建 groups
    groups = []
    for t_idx in time_idxs:
        start = t_idx - offset
        group_cols = list(range(start, start + count))
        time_col = t_idx
        name_col = start + name_rel_offset
        other_cols = [c for c in group_cols if c != time_col and c != name_col]
        groups.append({
            'time_col': time_col,
            'name_col': name_col,
            'other_cols': other_cols,
        })
    return groups, count

def process_sheet(ws, dev, count_param, show_progress=True):
    """计算新表头、对齐数据，以及原始单元格位置。"""
    rows = list(ws.values)
    header_row_idx = detect_header_row(ws)
    relevant_rows = rows[header_row_idx:]
    header_row_vals = rows[header_row_idx]
    if count_param is not None and count_param >= 2:
        width = max(
            (index + 1 for row in relevant_rows for index, value in enumerate(row) if value is not None),
            default=0,
        )
        padded_width = ((width + count_param - 1) // count_param) * count_param
        if padded_width <= len(header_row_vals):
            width = padded_width
        header_row_vals = header_row_vals[:width]
    groups, _ = detect_groups(header_row_vals, count_param)
    columns = {
        col for group in groups
        for col in (group['time_col'], group['name_col'], *group['other_cols'])
    }
    if any(value is not None and col not in columns
           for row in relevant_rows for col, value in enumerate(row)):
        raise ValueError("检测到未归入任何组的数据，请检查分组。")

    # 4. 提取数据（从表头行下一行开始）
    data_rows = rows[header_row_idx+1:]
    records = []  # 每个元素：{group, time, name, others}
    for r_idx, row_vals in enumerate(data_rows):
        if not any(row_vals):  # 跳过全空行
            continue
        for g_idx, g in enumerate(groups):
            time_val = row_vals[g['time_col']] if g['time_col'] < len(row_vals) else None
            name_val = row_vals[g['name_col']] if g['name_col'] < len(row_vals) else None
            if time_val is None or name_val is None:
                # 缺少关键信息，跳过
                continue
            # 时间转为浮点
            try:
                t = float(time_val)
            except (ValueError, TypeError):
                continue
            if not isfinite(t):
                continue
            name = str(name_val).strip()
            # 其他列值
            others = [row_vals[c] if c < len(row_vals) else None for c in g['other_cols']]
            records.append({
                'group': g_idx,
                'time': t,
                'name': name,
                'others': others,
                'row': header_row_idx + r_idx + 2,
            })

    if not records:
        raise ValueError("未找到具有有效保留时间和名称的数据。")

    # 5. 对齐（按时间排序，按名称和时间差匹配）
    records.sort(key=lambda x: x['time'])
    used = [False] * len(records)
    merged_rows = []  # 每个元素：{'name': name, 'group_data': {g_idx: (time, others)} }

    # 使用 tqdm 显示合并进度
    iter_records = tqdm(records, desc="合并对齐记录", disable=not show_progress, unit="条")
    for i, rec in enumerate(iter_records):
        if used[i]:
            continue
        # 创建新行
        name = rec['name']
        group_data = {rec['group']: rec}
        used[i] = True
        # 向后查找可以合并的记录
        for j in range(i+1, len(records)):
            rj = records[j]
            if rj['time'] - rec['time'] > dev:
                break
            if not used[j] and rj['name'] == name and rj['group'] not in group_data:
                group_data[rj['group']] = rj
                used[j] = True
        merged_rows.append({
            'name': name,
            'group_data': group_data,
            'name_source': (rec['row'], groups[rec['group']]['name_col'] + 1),
        })

    name_col = groups[0]['name_col']
    name_header = header_row_vals[name_col]
    new_headers = [str(name_header).strip() if is_name_header(name_header) else "名称"]
    header_columns = [name_col + 1]
    for group_number, group in enumerate(groups, 1):
        for col in (group['time_col'], *group['other_cols']):
            title = header_row_vals[col]
            if col == group['time_col'] and not is_time_header(title):
                title = "保留时间"
            title = str(title).strip() if title else f"Col_{col + 1}"
            new_headers.append(f"{title}_{group_number}")
            header_columns.append(col + 1)

    data_lines = []
    for merged in merged_rows:
        line = [(merged['name'], merged['name_source'])]
        for group_index, group in enumerate(groups):
            record = merged['group_data'].get(group_index)
            if record is None:
                line.extend([(None, None)] * (1 + len(group['other_cols'])))
                continue
            cols = (group['time_col'], *group['other_cols'])
            for value, col in zip((record['time'], *record['others']), cols):
                line.append((value, (record['row'], col + 1)))
        data_lines.append(line)

    return header_row_idx + 1, header_columns, new_headers, data_lines


def sort_sheet(ws, dev, count):
    header_row = detect_header_row(ws) + 1
    if (any(merge.max_row >= header_row for merge in ws.merged_cells.ranges)
            or ws.tables or ws.auto_filter.ref
            or ws._charts or ws._images or ws._pivots
            or ws.data_validations.dataValidation or ws.conditional_formatting
            or any(dimension.min != dimension.max for dimension in ws.column_dimensions.values())
            or any(cell.row >= header_row and cell.data_type == "f"
                   for cell in ws._cells.values())):
        raise ValueError("排序区域含合并单元格、公式或其他依赖原位置的对象。")

    header_row, header_columns, headers, data = process_sheet(ws, dev, count)
    if header_row + len(data) > 1048576:
        raise ValueError("对齐结果超出 Excel 的最大行数。")
    columns = {key: copy(value) for key, value in ws.column_dimensions.items()}
    source = {position: cell for position, cell in ws._cells.items() if position[0] >= header_row}
    for position in source:
        del ws._cells[position]
    ws.column_dimensions.clear()

    def write_cell(row, col, value, position):
        original = source.get(position)
        if value is None and original is None:
            return
        cell = ws.cell(row, col, value)
        if cell.data_type == 'f':
            cell.data_type = 's'
        if original is not None:
            cell._style = original._style
            if original.comment:
                cell.comment = copy(original.comment)
            if original.hyperlink:
                cell.hyperlink = copy(original.hyperlink)

    for col, (title, original_col) in enumerate(zip(headers, header_columns), 1):
        write_cell(header_row, col, title, (header_row, original_col))
        dimension = columns.get(get_column_letter(original_col))
        if dimension is not None:
            dimension.index = get_column_letter(col)
            dimension.min = dimension.max = col
            ws.column_dimensions[dimension.index] = dimension
    for row, line in enumerate(data, header_row + 1):
        for col, (value, position) in enumerate(line, 1):
            write_cell(row, col, value, position)


def out():
    option = json.loads(sys.argv[1])
    dev = float(option.get("Para1", ""))
    if not isfinite(dev) or dev < 0:
        raise ValueError("保留时间偏差必须是非负数。")
    count_value = option.get("Para2", "").strip()
    count = int(count_value) if count_value else None

    wb = openpyxl.load_workbook(option["File"])
    try:
        missing = prepare_sort_values(wb, option["File"])

        def process(ws):
            require_saved_sort_values(ws, missing)
            sort_sheet(ws, dev, count)

        process_workbook(wb, process)
        out_path = save_workbook(wb)
        print(f"处理完成，文件保存至：{out_path}")
        report_output(out_path)
    finally:
        wb.close()


if __name__ == "__main__":
    sys.exit(run_script(out))
