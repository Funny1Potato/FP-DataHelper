import os
import openpyxl
import time
import sys
import json
import math
import re
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from PyQt5.QtWidgets import QApplication, QMessageBox
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from method_support import (
    process_workbook, report_output, run_script, save_workbook, should_append_columns, write_columns,
)


# ================= 公共识别函数 =================
def col_letters():
    for c in range(1, 1000):
        n = c
        s = ''
        while n:
            n -= 1
            s = chr(ord('A') + n % 26) + s
            n //= 26
        yield s

HEAD = list(col_letters())[:256]

TIME_KEYWORDS = ('保留时间', '时间', 'time')
NAME_KEYWORDS = ('名称', 'name', 'compound', 'compounds')
CAS_KEYWORDS = ('cas', 'cas号', 'cas number')

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

def is_cas_header(val):
    if val is None:
        return False
    s = str(val).strip()
    if not s:
        return False
    return any(kw in s.lower() for kw in CAS_KEYWORDS)

def detect_header_row(ws, max_rows=20):
    """返回同时包含时间列和名称列的行索引（0-based）。"""
    for r in range(min(max_rows, ws.max_row)):
        row_vals = [cell.value for cell in ws[r+1]]
        has_time = any(is_time_header(v) for v in row_vals)
        has_name = any(is_name_header(v) for v in row_vals)
        if has_time and has_name:
            return r
    return 0

# ================= 正构烷烃参考文件加载 =================
def load_alkanes(file_path):
    """读取正构烷烃参考文件，返回 [(carbon_num, rt), ...] 按碳数升序排列。"""
    wb = openpyxl.load_workbook(file_path, data_only=True)
    alkanes = []
    try:
        rows = wb.active.iter_rows(min_col=1, max_col=2, values_only=True)
        for row_no, (carbon_value, time_value) in enumerate(rows, 1):
            if all(value is None or str(value).strip() == "" for value in (carbon_value, time_value)):
                continue
            try:
                carbon = float(carbon_value)
            except (TypeError, ValueError):
                if not alkanes and isinstance(carbon_value, str):
                    continue  # Optional text headings above the reference rows.
                raise ValueError(f"参考表第 {row_no} 行的碳数无效。") from None
            if not math.isfinite(carbon) or carbon < 1 or not carbon.is_integer():
                raise ValueError(f"参考表第 {row_no} 行的碳数必须是正整数。")
            try:
                rt = float(time_value)
            except (TypeError, ValueError):
                raise ValueError(f"参考表第 {row_no} 行缺少有效的保留时间。") from None
            if not math.isfinite(rt) or rt <= 0:
                raise ValueError(f"参考表第 {row_no} 行的保留时间必须是有限正数。")
            alkanes.append((int(carbon), rt))
    finally:
        wb.close()
    if len(alkanes) < 2:
        raise ValueError(f"正构烷烃参考文件中有效数据不足（至少需要2个），当前读取到 {len(alkanes)} 个。")
    alkanes.sort(key=lambda x: x[0])
    for (lower, lower_rt), (upper, upper_rt) in zip(alkanes, alkanes[1:]):
        if lower == upper:
            raise ValueError(f"正构烷烃参考表重复填写了 C{lower}。")
        if upper_rt <= lower_rt:
            raise ValueError(f"正构烷烃保留时间必须随碳数递增，请检查 C{lower} 与 C{upper}。")
    return alkanes

# ================= 保留指数计算 =================
def calc_ri_kovats(t_x, alkanes):
    """Kovats对数插值公式计算保留指数。"""
    if t_x <= 0:
        return None
    # 等于某个烷烃
    for carbon_num, rt in alkanes:
        if abs(t_x - rt) < 1e-10:
            return carbon_num * 100
    # 低于范围
    if t_x < alkanes[0][1]:
        return "低于范围"
    # 超出范围
    if t_x > alkanes[-1][1]:
        return "超出范围"
    # 查找包围的两个烷烃
    for i in range(len(alkanes) - 1):
        z, t_z = alkanes[i]
        z1, t_z1 = alkanes[i + 1]
        if t_z <= t_x < t_z1:
            if t_z <= 0 or t_z1 <= 0:
                return None
            fraction = (math.log10(t_x) - math.log10(t_z)) / (math.log10(t_z1) - math.log10(t_z))
            ri = 100 * (z + (z1 - z) * fraction)
            return round(ri, 1)
    return None

def calc_ri_linear(t_x, alkanes):
    """线性插值公式计算保留指数。"""
    if t_x <= 0:
        return None
    for carbon_num, rt in alkanes:
        if abs(t_x - rt) < 1e-10:
            return carbon_num * 100
    if t_x < alkanes[0][1]:
        return "低于范围"
    if t_x > alkanes[-1][1]:
        return "超出范围"
    for i in range(len(alkanes) - 1):
        z, t_z = alkanes[i]
        z1, t_z1 = alkanes[i + 1]
        if t_z <= t_x < t_z1:
            if t_z1 == t_z:
                return None
            fraction = (t_x - t_z) / (t_z1 - t_z)
            ri = 100 * (z + (z1 - z) * fraction)
            return round(ri, 1)
    return None

# ================= NIST RI 查询 =================
def get_nist_ri(cas, calc_ri):
    """根据CAS号查询NIST数据库中最接近calc_ri的保留指数。"""
    if cas is None or str(cas).strip() == "":
        return "\\"
    clean_cas = str(cas).strip().replace('-', '')
    url = f"https://webbook.nist.gov/cgi/cbook.cgi?ID=C{clean_cas}&Units=SI&Mask=2000"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return "\\"
        soup = BeautifulSoup(response.text, 'html.parser')
        target_title = "Normal alkane RI, non-polar column, custom temperature program"
        target_table = soup.find('table', attrs={'aria-label': target_title})
        if not target_table:
            text_matches = soup.find_all(string=re.compile(re.escape(target_title)))
            for match in text_matches:
                parent = match.parent
                next_table = parent.find_next('table')
                if next_table:
                    target_table = next_table
                    break
        if not target_table:
            return "\\"
        header_row = target_table.find('tr')
        headers_text = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
        try:
            ri_col_index = headers_text.index('I')
        except ValueError:
            return "\\"
        ri_values = []
        rows = target_table.find_all('tr')[1:]
        for row in rows:
            cols = row.find_all(['td', 'th'])
            if len(cols) > ri_col_index:
                val_text = cols[ri_col_index].get_text(strip=True)
                val_clean = re.sub(r'[^\d\.]', '', val_text)
                try:
                    if val_clean:
                        ri_values.append(float(val_clean))
                except ValueError:
                    continue
        if not ri_values:
            return "\\"
        closest_ri = min(ri_values, key=lambda x: abs(x - float(calc_ri)))
        if closest_ri.is_integer():
            return int(closest_ri)
        else:
            return closest_ri
    except Exception as e:
        print(f"  查询CAS {cas} 时出错: {e}")
        return "\\"

# ================= 工作表处理 =================
def process_sheet(ws, alkanes, formula, agg, cas_col_param, name_col_param, show_progress=True):
    """为一个工作表计算所选公式的保留指数。"""
    max_row = ws.max_row
    max_col = ws.max_column
    rows = []
    for r in range(1, max_row + 1):
        row_vals = [ws.cell(row=r, column=c).value for c in range(1, max_col + 1)]
        rows.append(row_vals)

    # 检测表头行
    header_idx = detect_header_row(ws)
    header_row_vals = rows[header_idx] if header_idx < len(rows) else []
    data_rows = rows[header_idx + 1:]

    # 确定名称列索引
    if name_col_param:
        name_col = HEAD.index(name_col_param.upper())
    else:
        name_col = None
        for i, val in enumerate(header_row_vals):
            if is_name_header(val):
                name_col = i
                break
        if name_col is None:
            raise ValueError(f"工作表 '{ws.title}' 中未找到名称列，请通过参数指定。")

    # 确定CAS列索引（可选，用于NIST查询）
    cas_col = None
    if cas_col_param:
        cas_col = HEAD.index(cas_col_param.upper())
    else:
        for i, val in enumerate(header_row_vals):
            if is_cas_header(val):
                cas_col = i
                break

    # 找到所有保留时间列
    time_cols = [i for i, val in enumerate(header_row_vals) if is_time_header(val)]
    if not time_cols:
        raise ValueError(f"工作表 '{ws.title}' 中未找到保留时间列（表头需包含'保留时间'/'时间'/'time'）。")

    # 确定插入RI列的位置（名称列右侧）
    ri_insert_pos = name_col + 1

    if formula == "B":
        headers = ("保留指数(Kovats)", "保留指数(线性)")
    elif formula == "K":
        headers = ("保留指数(Kovats)",)
    else:
        headers = ("保留指数(线性)",)

    values = []
    for row in tqdm(data_rows, desc=f"处理 {ws.title}", disable=not show_progress, unit="行"):
        # 收集该行所有有效保留时间
        rts = []
        for tc in time_cols:
            if tc < len(row) and row[tc] is not None:
                try:
                    rts.append(float(row[tc]))
                except (ValueError, TypeError):
                    pass

        # 聚合保留时间
        if not rts:
            agg_rt = None
        elif agg == "A":
            agg_rt = sum(rts) / len(rts)
        elif agg == "MIN":
            agg_rt = min(rts)
        elif agg == "MAX":
            agg_rt = max(rts)
        else:
            agg_rt = sum(rts) / len(rts)

        # 计算RI
        if agg_rt is None:
            ri_kovats = ""
            ri_linear = ""
        else:
            if formula in ("K", "B"):
                ri_kovats = calc_ri_kovats(agg_rt, alkanes)
            else:
                ri_kovats = None
            if formula in ("L", "B"):
                ri_linear = calc_ri_linear(agg_rt, alkanes)
            else:
                ri_linear = None

        if formula == "L":
            values.append((ri_linear,))
        elif formula == "K":
            values.append((ri_kovats,))
        else:
            values.append((ri_kovats, ri_linear))

    return (header_idx + 1, ri_insert_pos + 1, headers, values), cas_col


def add_nist_ri(workbook, sheet_positions, append):
    """在已经计算 RI 的工作表中加入 NIST 对照列。"""
    for sheet_name, (header_row, ri_col, ri_count, cas_col) in sheet_positions.items():
        if cas_col is None:
            continue
        sheet = workbook[sheet_name]
        values = []
        rows = range(header_row + 1, sheet.max_row + 1)
        for row in tqdm(rows, desc=f"NIST查询 {sheet_name}", unit="行"):
            cas = sheet.cell(row, cas_col).value
            result = ""
            try:
                ri = float(sheet.cell(row, ri_col).value)
            except (ValueError, TypeError):
                ri = 0
            if cas and ri > 0:
                result = get_nist_ri(cas, ri)
                print(f"  [{row - header_row}] CAS: {cas} | 计算RI: {ri} | NIST RI: {result}")
                time.sleep(1)
            values.append((result,))
        write_columns(sheet, header_row, ri_col + ri_count, ("NIST RI",), values, append=append)


def main():
    option = json.loads(sys.argv[1])
    file = option["File"]
    para1 = option.get("Para1", "").strip()  # 参考文件路径
    para2 = option.get("Para2", "").strip()  # 公式,聚合
    para3 = option.get("Para3", "").strip()  # CAS列,名称列

    # 解析Para1：参考文件路径
    if not para1:
        raise ValueError("请提供正构烷烃参考文件路径（Para1）。")
    if not os.path.exists(para1):
        raise ValueError(f"参考文件不存在: {para1}")

    # 解析Para2：公式和聚合方式
    if para2:
        parts = [p.strip().upper() for p in para2.split(",")]
        formula = parts[0] if len(parts) > 0 and parts[0] in ("L", "K", "B") else "L"
        agg = parts[1] if len(parts) > 1 and parts[1] in ("A", "MIN", "MAX") else "A"
    else:
        formula, agg = "L", "A"

    # 解析Para3：CAS列和名称列
    cas_col_param = None
    name_col_param = None
    if para3:
        parts = [p.strip() for p in para3.split(",")]
        if len(parts) >= 1 and parts[0]:
            cas_col_param = parts[0].upper()
        if len(parts) >= 2 and parts[1]:
            name_col_param = parts[1].upper()

    alkanes = load_alkanes(para1)
    print(f"已加载 {len(alkanes)} 个正构烷烃数据（碳数 {alkanes[0][0]}-{alkanes[-1][0]}）")

    wb = openpyxl.load_workbook(file)
    try:
        append = should_append_columns(wb)
        positions = {}

        def process(ws):
            columns, cas_col = process_sheet(ws, alkanes, formula, agg, cas_col_param, name_col_param)
            header_row, _, headers, _ = columns
            ri_col = write_columns(ws, *columns, append=append)
            if cas_col is not None:
                cas_col += 1
                if cas_col >= ri_col:
                    cas_col += len(headers)
            positions[ws.title] = (header_row, ri_col, len(headers), cas_col)

        process_workbook(wb, process)
        out_path = save_workbook(wb, "_with_RI")
        print(f"RI计算完成！文件保存至：{out_path}")

        if any(position[-1] is not None for position in positions.values()):
            app = QApplication.instance() or QApplication(sys.argv)
            reply = QMessageBox.question(
                None, "NIST RI 查询",
                "RI计算完成！是否查询NIST数据库进行RI对比？\n\n（查询过程较慢，每条约1秒）",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                print("开始NIST查询（每条约1秒，请耐心等待）...")
                add_nist_ri(wb, positions, append)
                out_path = save_workbook(wb, "_with_RI_NIST")
                print(f"NIST查询完成！最终文件保存至：{out_path}")
        else:
            print("未检测到CAS号列，跳过NIST查询。")
        report_output(out_path)
    finally:
        wb.close()


if __name__ == "__main__":
    sys.exit(run_script(main))
