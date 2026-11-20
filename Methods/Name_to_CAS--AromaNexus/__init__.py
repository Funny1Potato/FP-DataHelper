import openpyxl
import time
import sys
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# ================= 复用之前的识别函数 =================
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from method_support import (
    process_workbook, report_output, run_script, save_workbook, should_append_columns, write_columns,
    find_header_row, worksheet_column,
)


NAME_KEYWORDS = ('名称', 'name', 'compound', 'compounds')


def is_name_header(value):
    return isinstance(value, str) and any(word in value.strip().lower() for word in NAME_KEYWORDS)


# ================= 参考程序中的 CAS 查询函数（完全照抄） =================
def get_cas_by_name(name):
    """
    根据物质名称去 NIST 搜索 CAS 号。
    """
    if name is None or str(name).strip() == "":
        return "\\"
    
    clean_name = str(name).strip()
    url = "https://webbook.nist.gov/cgi/cbook.cgi"
    params = {
        "Name": clean_name,
        "Units": "SI"
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return "Connection Error"
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        if "Search Results" in soup.title.text:
            return "Ambiguous/List Found"
            
        if "Name Not Found" in response.text:
            return "Not Found"

        cas_label = soup.find('strong', string="CAS Registry Number:")
        if cas_label:
            cas_text = cas_label.next_sibling
            if cas_text:
                return cas_text.strip()
        
        all_text = soup.get_text()
        if "CAS Registry Number:" in all_text:
            match = re.search(r'CAS Registry Number:\s*([\d\-]+)', all_text)
            if match:
                return match.group(1)

        return "Not Found in Page"

    except Exception as e:
        print(f"Error processing {name}: {e}")
        return "Error"

# ================= 处理单个工作表，添加 CAS 列 =================
def process_sheet_add_cas(ws, name_col_param, show_progress=True):
    """为工作表计算CAS号列。"""
    name_col = worksheet_column(ws, name_col_param)
    header_idx = find_header_row(ws, is_name_header, column=name_col)
    rows = ws.iter_rows(min_row=header_idx + 1, values_only=True)
    headers = next(rows, ())
    if name_col is None:
        name_col = next((index for index, value in enumerate(headers) if is_name_header(value)), None)
        if name_col is None:
            raise ValueError("未找到名称列，请通过参数1指定列字母。")
    data_rows = list(rows)

    # 收集所有需要查询的名称（去重）
    name_set = set()
    for row in data_rows:
        if name_col < len(row):
            val = row[name_col]
            if val is not None and str(val).strip():
                name_set.add(str(val).strip())

    # 查询 CAS，建立缓存
    cas_cache = {}
    desc = "查询 CAS 号"
    for name in tqdm(name_set, desc=desc, disable=not show_progress, unit="个"):
        cas = get_cas_by_name(name)
        cas_cache[name] = cas
        time.sleep(1)   # 礼貌爬虫

    values = []
    for row in data_rows:
        # 获取名称
        name_val = row[name_col] if name_col < len(row) else None
        if name_val is None or str(name_val).strip() == "":
            cas_val = ""
        else:
            cas_val = cas_cache.get(str(name_val).strip(), "Not Found")
        values.append((cas_val,))

    return header_idx + 1, name_col + 1, ("CAS号",), values


# ================= 主程序 =================
def main():
    option = json.loads(sys.argv[1])
    name_col_param = option.get("Para1", "").strip()
    wb = openpyxl.load_workbook(option["File"])

    try:
        append = should_append_columns(wb)

        def process(ws):
            result = process_sheet_add_cas(ws, name_col_param)
            write_columns(ws, *result, append=append)

        process_workbook(wb, process)
        out_path = save_workbook(wb, "_with_cas")
        print(f"处理完成，文件保存至：{out_path}")
        report_output(out_path)
    finally:
        wb.close()


if __name__ == "__main__":
    sys.exit(run_script(main))
