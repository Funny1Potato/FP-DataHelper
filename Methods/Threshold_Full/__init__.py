# -*- coding: utf-8 -*-
"""
Threshold_Full 模块
基于 Threshold_full.json 完整数据库的高级阈值查询模块。
支持三种模式：default（默认最新值）、custom（自定义筛选）、manual（手动选择）

参数说明：
  Para1 - （可选）CAS号列位置（列字母，如 D）
  Para2 - 模式：d(默认) / c(自定义) / m(手动)
  Para3 - 无
"""

import os
import sys
import json
import re
from pathlib import Path
import openpyxl
from tqdm import tqdm
from PyQt5.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout,
                              QLabel, QComboBox, QCheckBox, QPushButton,
                              QTableWidget, QTableWidgetItem, QHeaderView,
                              QAbstractItemView, QMessageBox)
from PyQt5.QtCore import Qt

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from method_support import (
    MethodCancelled, find_header_row, is_cas_header, process_workbook, report_output,
    run_script, save_workbook, should_append_columns, worksheet_column, write_columns,
)


NAME_KEYWORDS = ('名称', 'name', 'compound', 'compounds')


def is_name_header(value):
    return isinstance(value, str) and any(word in value.strip().lower() for word in NAME_KEYWORDS)


# ================= 数据库加载 =================
def load_full_thresholds(json_path="./Database/Threshold_full.json"):
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"未找到阈值数据库文件: {json_path}")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    cas_index = {}
    name_index = {}
    for compound in data:
        cas = (compound.get('cas_number') or '').strip()
        if cas:
            cas_index[cas] = compound
        en = (compound.get('english_name') or '').strip().lower()
        cn = (compound.get('chinese_name') or '').strip()
        if en:
            name_index[en] = compound
        if cn:
            name_index[cn] = compound
    return data, cas_index, name_index

# ================= 范围值解析 =================
def parse_threshold_value(val_str):
    """解析阈值字符串，返回数值列表。支持范围值如 '0.001～0.002'"""
    if not val_str:
        return []
    s = str(val_str).strip()
    s = re.sub(r'^[<>≤≥]', '', s)
    range_match = re.match(r'([\d.]+)\s*[～~\-]\s*([\d.]+)', s)
    if range_match:
        try:
            return [float(range_match.group(1)), float(range_match.group(2))]
        except ValueError:
            return []
    try:
        return [float(s)]
    except ValueError:
        return []

def get_max_value(thresholds):
    """获取阈值列表中的最大值"""
    max_val = None
    for t in thresholds:
        vals = parse_threshold_value(t.get('value', ''))
        if vals:
            v = max(vals)
            if max_val is None or v > max_val:
                max_val = v
    return max_val

def get_min_value(thresholds):
    """获取阈值列表中的最小值"""
    min_val = None
    for t in thresholds:
        vals = parse_threshold_value(t.get('value', ''))
        if vals:
            v = min(vals)
            if min_val is None or v < min_val:
                min_val = v
    return min_val

def get_latest_threshold(thresholds):
    """获取最新年份的阈值"""
    if not thresholds:
        return None
    valid = [t for t in thresholds if t.get('year')]
    if not valid:
        return thresholds[0]
    max_year = max(t.get('year', 0) for t in valid)
    latest = [t for t in valid if t.get('year') == max_year]
    return latest[0] if latest else thresholds[0]

def filter_by_type(thresholds, type_filter):
    """Only include records of the selected type."""
    if not type_filter or type_filter == "全部":
        return thresholds
    selected = type_filter.strip().casefold()
    return [
        record for record in thresholds
        if (record.get("type") or "").strip().casefold() == selected
    ]


# ================= PyQt5 窗口 =================
class CustomModeWindow(QDialog):
    """自定义模式设置窗口"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自定义模式 - 筛选条件")
        self.setFixedSize(350, 250)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("匹配方式:"))
        self.match_combo = QComboBox()
        self.match_combo.addItems(["CAS 号", "名称"])
        row1.addWidget(self.match_combo)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("阈值选择:"))
        self.value_combo = QComboBox()
        self.value_combo.addItems(["最新值", "最大值", "最小值"])
        row2.addWidget(self.value_combo)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("类型:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["全部", "detection", "recognition"])
        row3.addWidget(self.type_combo)
        layout.addLayout(row3)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("确认")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def get_settings(self):
        return {
            'match_mode': 'cas' if self.match_combo.currentIndex() == 0 else 'name',
            'value_mode': ['latest', 'max', 'min'][self.value_combo.currentIndex()],
            'type_filter': self.type_combo.currentText()
        }

class ManualModeSettingsWindow(QDialog):
    """手动模式设置窗口"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("手动模式 - 匹配方式")
        self.setFixedSize(300, 180)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel("请选择匹配方式（可多选）:"))

        self.cas_check = QCheckBox("CAS 号")
        self.cas_check.setChecked(True)
        layout.addWidget(self.cas_check)

        self.name_check = QCheckBox("名称")
        self.name_check.setChecked(True)
        layout.addWidget(self.name_check)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("确认")
        ok_btn.clicked.connect(self.validate_and_accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def validate_and_accept(self):
        if not self.cas_check.isChecked() and not self.name_check.isChecked():
            QMessageBox.warning(self, "提示", "请至少选择一种匹配方式")
            return
        self.accept()

    def get_settings(self):
        return {
            'use_cas': self.cas_check.isChecked(),
            'use_name': self.name_check.isChecked()
        }

class ManualModeDialog(QDialog):
    """手动模式逐行选择对话框"""
    def __init__(self, compound_name, cas_number, thresholds, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"选择阈值 - {compound_name}")
        self.setMinimumSize(600, 400)
        self.thresholds = thresholds
        self.selected_indices = []
        self.setup_ui(compound_name, cas_number)

    def setup_ui(self, compound_name, cas_number):
        layout = QVBoxLayout()

        info = f"化合物: {compound_name}"
        if cas_number:
            info += f"  |  CAS: {cas_number}"
        layout.addWidget(QLabel(info))

        self.table = QTableWidget(len(self.thresholds), 5)
        self.table.setHorizontalHeaderLabels(["值", "单位", "研究者", "年份", "类型"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.MultiSelection)

        for i, t in enumerate(self.thresholds):
            self.table.setItem(i, 0, QTableWidgetItem(str(t.get('value', ''))))
            self.table.setItem(i, 1, QTableWidgetItem(str(t.get('unit', ''))))
            self.table.setItem(i, 2, QTableWidgetItem(str(t.get('researcher', ''))))
            self.table.setItem(i, 3, QTableWidgetItem(str(t.get('year', ''))))
            self.table.setItem(i, 4, QTableWidgetItem(str(t.get('type', ''))))

        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("确认选择")
        ok_btn.clicked.connect(self.accept_selection)
        skip_btn = QPushButton("跳过")
        skip_btn.clicked.connect(self.skip)
        cancel_btn = QPushButton("取消处理")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(skip_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def accept_selection(self):
        selected = self.table.selectionModel().selectedRows()
        self.selected_indices = [idx.row() for idx in selected]
        self.done(QDialog.Accepted)

    def skip(self):
        self.selected_indices = []
        self.done(QDialog.Accepted)

    def get_selected_values(self):
        if not self.selected_indices:
            return "Skipped"
        values = []
        for idx in self.selected_indices:
            val = self.thresholds[idx].get('value', '')
            if val:
                values.append(str(val))
        return '; '.join(values) if values else "Skipped"

# ================= 核心处理逻辑 =================
def find_columns(header_row_vals):
    """自动识别 CAS 列和名称列"""
    cas_col = None
    name_col = None
    for i, val in enumerate(header_row_vals):
        if cas_col is None and is_cas_header(val):
            cas_col = i
        if name_col is None and is_name_header(val):
            name_col = i
    return cas_col, name_col

def threshold_columns(sheet, cas_col_param, *, use_cas=True, use_name=True):
    explicit_cas = worksheet_column(sheet, cas_col_param) if use_cas else None
    header = None
    if use_cas:
        header = find_header_row(sheet, is_cas_header, column=explicit_cas, fallback=None)
    if header is None:
        header = find_header_row(sheet, is_name_header) if use_name else 0

    rows = sheet.iter_rows(min_row=header + 1, values_only=True)
    cas_col, name_col = find_columns(next(rows, ()))
    if explicit_cas is not None:
        cas_col = explicit_cas
    return header, rows, cas_col if use_cas else None, name_col if use_name else None


def lookup_by_cas(cas_val, cas_index):
    if not cas_val:
        return None
    cas_key = str(cas_val).strip()
    return cas_index.get(cas_key)

def lookup_by_name(name_val, name_index):
    if not name_val:
        return None
    name_key = str(name_val).strip().lower()
    return name_index.get(name_key)

def process_default_mode(ws, cas_col_param, cas_index, name_index):
    """默认模式：自动匹配最新阈值"""
    header_idx, data_rows, cas_col, name_col = threshold_columns(ws, cas_col_param)
    if cas_col is None and name_col is None:
        raise ValueError("未找到 CAS 或名称列，请检查表头或通过参数1指定 CAS 列。")
    insert_col = (cas_col if cas_col is not None else name_col) + 2

    values = []
    stats = {'matched': 0, 'not_found': 0}

    for row in tqdm(data_rows, desc="处理数据", unit="行"):
        cas_val = row[cas_col] if cas_col is not None else None
        name_val = row[name_col] if name_col is not None and name_col < len(row) else None

        if cas_val is None and name_val is None:
            values.append(("",))
            continue

        compound = lookup_by_cas(cas_val, cas_index)
        if compound is None and name_val:
            compound = lookup_by_name(name_val, name_index)

        if compound is None:
            values.append(("Not Found",))
            stats['not_found'] += 1
            continue

        thresholds = compound.get('thresholds', [])
        if not thresholds:
            values.append(("No Data",))
            continue

        latest = get_latest_threshold(thresholds)
        values.append((str(latest.get('value', '')) if latest else "No Data",))
        stats['matched'] += 1

    return (header_idx + 1, insert_col, ("嗅觉阈值(mg/L)",), values), stats

def process_custom_mode(ws, cas_col_param, cas_index, name_index, settings):
    """自定义模式：根据用户设置筛选"""
    use_cas = bool(cas_col_param) or settings['match_mode'] == 'cas'
    header_idx, data_rows, cas_col, name_col = threshold_columns(
        ws, cas_col_param, use_cas=use_cas, use_name=not use_cas,
    )
    lookup_col = cas_col if use_cas else name_col
    if lookup_col is None:
        raise ValueError(f"未找到{'CAS' if use_cas else '名称'}列，请检查表头。")

    values = []
    stats = {'matched': 0, 'not_found': 0}

    for row in tqdm(data_rows, desc="处理数据", unit="行"):
        lookup_val = row[lookup_col] if lookup_col < len(row) else None

        if lookup_val is None:
            values.append(("",))
            continue

        if use_cas:
            compound = lookup_by_cas(lookup_val, cas_index)
        else:
            compound = lookup_by_name(lookup_val, name_index)

        if compound is None:
            values.append(("Not Found",))
            stats['not_found'] += 1
            continue

        thresholds = compound.get('thresholds', [])
        if not thresholds:
            values.append(("No Data",))
            continue

        filtered = filter_by_type(thresholds, settings.get('type_filter'))
        value_mode = settings.get('value_mode', 'latest')
        if value_mode == 'latest':
            latest = get_latest_threshold(filtered)
            value = latest.get('value') if latest else None
        elif value_mode == 'max':
            value = get_max_value(filtered)
        else:
            value = get_min_value(filtered)
        if value is None:
            values.append(("No Match",))
            stats['not_found'] += 1
        else:
            values.append((str(value),))
            stats['matched'] += 1

    return (header_idx + 1, lookup_col + 2, ("嗅觉阈值(mg/L)",), values), stats


def process_manual_mode(ws, cas_col_param, cas_index, name_index, settings):
    """手动模式：用户逐行选择"""
    use_cas = settings.get('use_cas', True)
    use_name = settings.get('use_name', True)
    header_idx, data_rows, cas_col, name_col = threshold_columns(
        ws, cas_col_param, use_cas=use_cas, use_name=use_name,
    )
    if cas_col is None and name_col is None:
        raise ValueError("未找到可用于匹配的 CAS 或名称列。")
    insert_col = (cas_col if cas_col is not None else name_col) + 2

    values = []
    stats = {'matched': 0, 'not_found': 0, 'skipped': 0}
    for row in tqdm(data_rows, desc="处理数据", unit="行"):
        cas_val = row[cas_col] if cas_col is not None and cas_col < len(row) else None
        name_val = row[name_col] if name_col is not None and name_col < len(row) else None

        if cas_val is None and name_val is None:
            values.append(("",))
            continue

        compound = None

        if use_cas and cas_val:
            compound = lookup_by_cas(cas_val, cas_index)
        if compound is None and use_name and name_val:
            compound = lookup_by_name(name_val, name_index)

        if compound is None:
            values.append(("Not Found",))
            stats['not_found'] += 1
            continue

        thresholds = compound.get('thresholds', [])
        if not thresholds:
            values.append(("No Data",))
            continue

        compound_name = compound.get('chinese_name') or compound.get('english_name', '')
        cas_number = compound.get('cas_number', '')
        dialog = ManualModeDialog(compound_name, cas_number, thresholds)
        result = dialog.exec_()

        if result != QDialog.Accepted:
            raise MethodCancelled()

        selected_value = dialog.get_selected_values()
        values.append((selected_value,))

        if selected_value == "Skipped":
            stats['skipped'] += 1
        else:
            stats['matched'] += 1

    return (header_idx + 1, insert_col, ("嗅觉阈值(mg/L)",), values), stats

# ================= 主程序 =================
def main():
    option = json.loads(sys.argv[1])
    para1 = option.get("Para1", "").strip()
    para2 = option.get("Para2", "").strip().lower()
    settings = option.get("ThresholdSettings")
    all_compounds, cas_index, name_index = load_full_thresholds()
    print(f"已加载阈值数据库: {len(all_compounds)} 个化合物")

    if settings is not None:
        if (not isinstance(settings, dict)
                or settings.get("match_mode") not in ("cas", "name")
                or settings.get("value_mode") not in ("latest", "min", "max")
                or settings.get("type_filter") not in ("全部", "detection", "recognition")):
            raise ValueError("ThresholdSettings 含无效的匹配方式、取值方式或阈值类型。")
        mode, dialog_type, calculate = "custom", None, process_custom_mode
    elif para2 in ("c", "custom"):
        mode, dialog_type, calculate = "custom", CustomModeWindow, process_custom_mode
    elif para2 in ("m", "manual"):
        mode, dialog_type, calculate = "manual", ManualModeSettingsWindow, process_manual_mode
    else:
        mode, dialog_type, calculate = "default", None, process_default_mode
    print(f"运行模式: {mode}")

    extra_args = (settings,) if settings is not None else ()
    if dialog_type is not None:
        app = QApplication.instance() or QApplication(sys.argv)
        dialog = dialog_type()
        if dialog.exec_() != QDialog.Accepted:
            raise MethodCancelled()
        extra_args = (dialog.get_settings(),)

    total_stats = {"matched": 0, "not_found": 0, "skipped": 0}
    wb = openpyxl.load_workbook(option["File"])
    try:
        append = should_append_columns(wb)

        def process(ws):
            columns, stats = calculate(ws, para1, cas_index, name_index, *extra_args)
            write_columns(ws, *columns, append=append)
            for key in total_stats:
                total_stats[key] += stats.get(key, 0)
            print(f"  工作表 '{ws.title}': 匹配 {stats['matched']}, 未找到 {stats['not_found']}")

        process_workbook(wb, process)
        out_path = save_workbook(wb, "_threshold_full")
        print(f"匹配 {total_stats['matched']}，未找到 {total_stats['not_found']}，跳过 {total_stats['skipped']}")
        print(f"处理完成，文件保存至：{out_path}")
        report_output(out_path)
    finally:
        wb.close()


if __name__ == "__main__":
    sys.exit(run_script(main))
