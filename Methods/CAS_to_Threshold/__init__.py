import os
import openpyxl
import sys
import json
from tqdm import tqdm

# ================= 识别函数 =================
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from method_support import (
    process_workbook, report_output, run_script, save_workbook, should_append_columns, write_columns,
    find_header_row, worksheet_column, is_cas_header,
)


# ================= 阈值加载 =================
def load_thresholds(json_path="./Database/Threshold.json"):
    """从 JSON 文件读取阈值数据，返回字典 {cas: threshold}"""
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"未找到阈值文件: {json_path} ")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data

# ================= 处理单个工作表，添加“嗅觉阈值”列 =================
def process_sheet_add_threshold(ws, cas_col_param, threshold_dict, show_progress=True):
    """为工作表计算嗅觉阈值列。"""
    cas_col = worksheet_column(ws, cas_col_param)
    header_idx = find_header_row(ws, is_cas_header, column=cas_col)
    rows = ws.iter_rows(min_row=header_idx + 1, values_only=True)
    headers = next(rows, ())
    if cas_col is None:
        cas_col = next((index for index, value in enumerate(headers) if is_cas_header(value)), None)
        if cas_col is None:
            raise ValueError("未找到CAS列，请通过参数1指定列字母。")
    data_rows = rows

    values = []
    for row in tqdm(data_rows, desc=f"处理 {ws.title} 数据行", disable=not show_progress, unit="行"):
        cas_val = row[cas_col] if cas_col < len(row) else None
        if cas_val is None or str(cas_val).strip() == "":
            threshold = ""
        else:
            cas_key = str(cas_val).strip()
            threshold = threshold_dict.get(cas_key, "Not Found")
        values.append((threshold,))

    return header_idx + 1, cas_col + 2, ("嗅觉阈值",), values


# ================= 主程序 =================
def main():
    option = json.loads(sys.argv[1])
    cas_col_param = option.get("Para1", "").strip()
    threshold_dict = load_thresholds()
    print("已加载阈值数据文件")
    wb = openpyxl.load_workbook(option["File"])

    try:
        append = should_append_columns(wb)

        def process(ws):
            result = process_sheet_add_threshold(ws, cas_col_param, threshold_dict)
            write_columns(ws, *result, append=append)

        process_workbook(wb, process)
        out_path = save_workbook(wb, "_with_threshold")
        print(f"处理完成，文件保存至：{out_path}")
        report_output(out_path)
    finally:
        wb.close()


if __name__ == "__main__":
    sys.exit(run_script(main))
