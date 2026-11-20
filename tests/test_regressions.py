import contextlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import openpyxl
from openpyxl.styles import Font, PatternFill
from PyQt5.QtCore import QElapsedTimer
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

import Datahelper
import method_process
from method_support import (
    METHOD_CANCELLED_EXIT_CODE, RESULT_PATH_ENV, SORT_SOURCE_NAME, run_script,
    should_append_columns, sort_source_sheets, write_columns,
)
from updater import Updater


ROOT = Path(__file__).resolve().parents[1]


def load_method(name):
    spec = importlib.util.spec_from_file_location("test_method", ROOT / "Methods" / name / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()
        patcher = patch.object(method_process, "PROGRAM_DIR", self.work)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.input = self.work / "原始文件.xlsx"
        self.input.touch()

    def method(self, name, body):
        directory = self.work / "Methods" / name
        directory.mkdir(parents=True)
        (directory / "__init__.py").write_text(
            "import json, os, sys\nfrom pathlib import Path\n"
            "params = json.loads(sys.argv[1])\n" + body,
            encoding="utf-8",
        )

    def batch(self, *methods):
        tasks = [{"method": method} for method in methods]
        tasks[0]["input_file"] = str(self.input)
        executor = Datahelper.BatchExecutor(tasks)
        self.addCleanup(self.stop_batch, executor)
        return executor

    def stop_batch(self, executor):
        executor.stop()
        self.wait(lambda: executor.job is None)

    def test_cancelled_method_stops_queue_without_reporting_failure(self):
        self.method("cancelled", f"raise SystemExit({METHOD_CANCELLED_EXIT_CODE})\n")
        executor = self.batch("cancelled", "unused")
        started, outcomes = [], []
        executor.task_started.connect(lambda index, name: started.append(name))
        executor.task_failed.connect(lambda *_: outcomes.append("failed"))
        executor.all_finished.connect(lambda: outcomes.append("finished"))
        executor.cancelled.connect(lambda: outcomes.append("cancelled"))
        executor.start()
        self.wait(lambda: outcomes)
        self.assertEqual(started, ["cancelled"])
        self.assertEqual(outcomes, ["cancelled"])

    def test_down_without_current_row_keeps_workflow_order(self):
        dialog = Datahelper.BatchDialog(["Sorter-0.1.0", "Si_Marker"])
        tasks = [{"method": "Sorter-0.1.0"}, {"method": "Si_Marker"}]
        dialog.task_queue = tasks.copy()
        dialog.update_table()
        dialog.table.setCurrentCell(-1, -1)
        dialog.move_down()
        self.assertEqual(dialog.task_queue, tasks)
        dialog.close()

    def wait(self, predicate):
        timer = QElapsedTimer()
        timer.start()
        while not predicate() and timer.elapsed() < 5000:
            QTest.qWait(10)
        self.assertTrue(predicate())

    def test_passes_structured_final_file_and_accepts_input(self):
        self.method("producer", f"""
print("请按回车", end="", flush=True)
assert input() == ""
for file in ("intermediate.xlsx", "最终.xlsx"):
    Path(file).touch()
    print("文件保存至：" + file)
Path(os.environ[{RESULT_PATH_ENV!r}]).write_text(
    json.dumps({{"output_file": "最终.xlsx"}}), encoding="utf-8"
)
print("文件保存至：intermediate.xlsx")
""")
        self.method("consumer", """
assert Path(params["File"]).name == "最终.xlsx", params
print("文件保存至：" + params["File"])
""")
        executor = self.batch("producer", "consumer")
        output, results, failures = [], [], []
        executor.output_ready.connect(output.append)
        executor.task_finished.connect(lambda index, path: results.append(Path(path)))
        executor.task_failed.connect(lambda index, error: failures.append(error))
        executor.start()
        self.wait(lambda: "请按回车" in "".join(output))
        self.assertTrue(executor.send_input(""))
        self.wait(lambda: len(results) == 2 or bool(failures))
        self.assertFalse(failures)
        self.assertEqual(results, [self.work / "最终.xlsx"] * 2)

    def test_missing_result_retries_or_skips_with_original_file(self):
        self.method("missing", 'print("no output")\n')
        self.method("consumer", """
assert Path(params["File"]).name == "原始文件.xlsx"
print("文件保存至：" + params["File"])
""")
        executor = self.batch("missing", "consumer")
        results, failures, done = [], [], []
        executor.task_finished.connect(lambda index, path: results.append((index, Path(path))))
        executor.task_failed.connect(lambda index, error: failures.append(index))
        executor.all_finished.connect(lambda: done.append(True))
        executor.start()
        self.wait(lambda: len(failures) == 1)
        self.assertEqual(results, [])
        executor.resolve_failure(skip=False)
        self.wait(lambda: len(failures) == 2)
        executor.resolve_failure(skip=True)
        self.wait(lambda: bool(done))
        self.assertEqual(failures, [0, 0])
        self.assertEqual(executor.skipped, 1)
        self.assertEqual(results, [(1, self.input)])

    def test_nonexistent_output_fails_without_advancing(self):
        self.method("missing", 'print("文件保存至：missing.xlsx")\n')
        executor = self.batch("missing", "unused")
        failures = []
        executor.task_failed.connect(lambda index, error: failures.append((index, error)))
        executor.start()
        self.wait(lambda: bool(failures))
        self.assertEqual(executor.current_index, 0)
        self.assertIn("missing.xlsx", failures[0][1])

    def test_stop_reports_cancel_and_does_not_start_next_task(self):
        self.method("waiting", 'print("ready", flush=True)\ninput()\n')
        executor = self.batch("waiting", "unused")
        output, started, ended = [], [], []
        executor.output_ready.connect(output.append)
        executor.task_started.connect(lambda index, name: started.append(name))
        executor.task_failed.connect(lambda index, error: ended.append("failed"))
        executor.all_finished.connect(lambda: ended.append("finished"))
        executor.cancelled.connect(lambda: ended.append("cancelled"))
        executor.start()
        self.wait(lambda: "ready" in "".join(output))
        executor.stop()
        self.wait(lambda: bool(ended))
        self.assertEqual(ended, ["cancelled"])
        self.assertEqual(started, ["waiting"])

    def test_stop_releases_stdin_wait_before_terminating_browser_method(self):
        self.method("Cb_Spider--AromaNexus", """
try:
    print("ready", flush=True)
    input()
finally:
    Path("browser-closed").touch()
""")
        executor = self.batch("Cb_Spider--AromaNexus")
        output, cancelled = [], []
        executor.output_ready.connect(output.append)
        executor.cancelled.connect(lambda: cancelled.append(True))
        executor.start()
        self.wait(lambda: "ready" in "".join(output))
        executor.stop()
        self.wait(lambda: bool(cancelled))
        self.assertTrue((self.work / "browser-closed").is_file())

    def test_main_window_single_execution_uses_same_runner(self):
        self.method("Sorter-0.1.0", 'print("文件保存至：" + params["File"])\n')
        with patch.object(Datahelper, "load_settings", return_value={"auto_check_update": False}):
            window = Datahelper.MainForm()
        try:
            window.ChooseMethods.setCurrentText("Sorter-0.1.0")
            window.file.setText(str(self.input))
            window.run_clicked()
            self.assertFalse(window.batch.isEnabled())
            self.wait(lambda: window.job is None)
            self.assertIn("执行完成，输出文件", window.output_area.toPlainText())
            self.assertTrue(window.batch.isEnabled())
        finally:
            if window.job:
                window.job.stop()
                self.wait(lambda: window.job is None)
            window.close()


class WorkbookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()

    def run_method(self, method, filename, **options):
        control = self.work / "result.json"
        control.unlink(missing_ok=True)
        params = json.dumps({"File": str(filename), **options})
        run = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(ROOT / "Methods" / method / "__init__.py"), params],
            cwd=self.work, env={**os.environ, RESULT_PATH_ENV: str(control)},
            capture_output=True, encoding="utf-8", timeout=15,
        )
        path = json.loads(control.read_text(encoding="utf-8"))["output_file"] if control.exists() else None
        return run, path

    def test_manual_group_width_overrides_recognized_headers(self):
        sorter = load_method("Sorter-0.1.0")
        headers = ["Time", "Name", "Area", "Time", "Name", "Area"]
        self.assertEqual(sorter.detect_groups(headers)[1], 3)
        self.assertEqual(sorter.detect_groups(headers, 2)[1], 2)
        with self.assertRaises(ValueError):
            sorter.detect_groups(headers, 4)

    def test_sort_cli_manual_preserves_styles_and_reports_skipped_sheet(self):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["RT", "Peak", "Area", "RT", "Peak", "Area"])
        sheet.append([1, "A", 10, 1.5, "A", 20])
        sheet.append([5, "B", 30, 6, "B", 40])
        sheet["F2"].fill = PatternFill("solid", fgColor="FFC000")
        sheet.column_dimensions["F"].width = 24
        notes = workbook.create_sheet("Notes")
        notes["A1"] = "original"
        notes.merge_cells("A1:B1")
        source = self.work / "peaks.xlsx"
        workbook.save(source)

        run, output = self.run_method("Sorter-0.1.0", source, Para1="0.5", Para2="3")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("Notes", run.stdout)
        self.assertIn("保留原表", run.stdout)
        result = openpyxl.load_workbook(output)
        try:
            self.assertEqual(list(result.active.values)[1:], [
                ("A", 1, 10, 1.5, 20),
                ("B", 5, 30, None, None),
                ("B", None, None, 6, 40),
            ])
            self.assertEqual(result.active["E2"].fill.fgColor.rgb[-6:], "FFC000")
            self.assertEqual(result.active.column_dimensions["E"].width, 24)
            self.assertIn("A1:B1", result["Notes"].merged_cells)
            self.assertEqual(result["Notes"]["A1"].value, "original")
        finally:
            result.close()

    def test_column_insertion_keeps_title_merge_styles_and_moved_merge(self):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.merge_cells("A1:D1")
        sheet["A1"] = "Title"
        sheet.append(["Name", "CAS", "Area", "Notes"])
        sheet.append(["compound", "83-32-9", 23, "a note"])
        sheet["C3"].font = Font(bold=True)
        sheet.merge_cells("D3:E3")
        sheet.column_dimensions["C"].width = 21

        self.assertFalse(should_append_columns(workbook))
        write_columns(sheet, 2, 3, ("Threshold",), [("0.08",)])
        self.assertEqual(sheet["C3"].value, "0.08")
        self.assertEqual(sheet["D3"].value, 23)
        self.assertTrue(sheet["D3"].font.bold)
        self.assertEqual(sheet.column_dimensions["D"].width, 21)
        self.assertIn("A1:D1", sheet.merged_cells)
        self.assertIn("E3:F3", sheet.merged_cells)

    def test_append_keeps_formula_references(self):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["Name", "CAS", "Area"])
        sheet.append(["compound", "83-32-9", 23])
        workbook.create_sheet("Summary")["A1"] = "=Sheet!C2"
        append = should_append_columns(workbook)
        self.assertTrue(append)
        write_columns(sheet, 1, 3, ("Threshold",), [("0.08",)], append=append)
        self.assertEqual(sheet["C2"].value, 23)
        self.assertEqual(sheet["D2"].value, "0.08")
        self.assertEqual(workbook["Summary"]["A1"].value, "=Sheet!C2")

    def test_no_successful_sheets_exits_without_output(self):
        workbook = openpyxl.Workbook()
        workbook.active["A1"] = "Notes"
        source = self.work / "notes.xlsx"
        workbook.save(source)
        run, output = self.run_method("Si_Marker", source)
        self.assertNotEqual(run.returncode, 0)
        self.assertIsNone(output)
        self.assertIn("没有成功处理任何工作表", run.stdout)

    def test_sort_writes_one_tab_and_freezes_cross_sheet_formula_values(self):
        workbook = openpyxl.Workbook()
        raw = workbook.active
        raw.title = "Raw's peaks"
        other = workbook.create_sheet("Independent")
        for sheet in (raw, other):
            sheet.append(["Time", "Name", "Area", "Time", "Name", "Area"])
            sheet.append([2, "B", 20, 2.1, "B", 21])
            sheet.append([1, "A", 10, 1.1, "A", 11])
        summary = workbook.create_sheet("Summary")
        summary["A1"] = "='Raw''s peaks'!C2"
        workbook.create_sheet("Missing")["A1"] = '=INDIRECT("Independent!C2")'
        uncached = self.work / "uncached.xlsx"
        workbook.save(uncached)
        source = self.cache_formula_value(uncached, "sheet3", 20)
        original = source.read_bytes()
        for method, options, name_cell in (
            ("Sorter-0.1.0", {}, "A2"),
            ("Sorter-0.0.2", {"Para2": "3"}, "B2"),
        ):
            with self.subTest(method=method):
                result, output = self.run_method(method, source, Para1="0.5", **options)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("已保存的公式计算值", result.stdout)
                with contextlib.closing(openpyxl.load_workbook(output)) as sorted_book:
                    self.assertEqual(sorted_book.sheetnames, workbook.sheetnames)
                    self.assertEqual(sorted_book[raw.title][name_cell].value, "A")
                    self.assertEqual(sorted_book[raw.title]["C2"].value, 10)
                    self.assertEqual(sorted_book["Summary"]["A1"].value, 20)
                    self.assertEqual(sorted_book["Missing"]["A1"].value, "#N/A")
                    self.assertEqual(sorted_book["Missing"]["A1"].data_type, "e")
                    self.assertEqual(sort_source_sheets(sorted_book), set())
                self.assertEqual(source.read_bytes(), original)

    def cache_formula_value(self, source, sheet_name, value):
        cached = self.work / f"{source.stem}-with-cache.xlsx"
        with zipfile.ZipFile(source) as previous, zipfile.ZipFile(cached, "w") as updated:
            for name in previous.namelist():
                content = previous.read(name)
                if name == f"xl/worksheets/{sheet_name}.xml":
                    self.assertIn(b"</f><v></v>", content)
                    content = content.replace(b"</f><v></v>", f"</f><v>{value}</v>".encode(), 1)
                updated.writestr(name, content)
        return cached

    def test_sort_copies_saved_formula_values_into_sorted_view(self):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["Time", "Name", "Area", "Time", "Name", "Area"])
        sheet.append([2, "B", "=10+10", 2.1, "B", 21])
        sheet.append([1, "A", 10, 1.1, "A", 11])
        source = self.work / "with-formula.xlsx"
        workbook.save(source)
        missing, output = self.run_method("Sorter-0.1.0", source, Para1="0.5")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("C2 没有已保存的计算结果", missing.stdout)
        self.assertIsNone(output)

        cached = self.cache_formula_value(source, "sheet1", 20)
        original = cached.read_bytes()
        result, output = self.run_method("Sorter-0.1.0", cached, Para1="0.5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with contextlib.closing(openpyxl.load_workbook(output)) as sorted_book:
            self.assertEqual(sorted_book.sheetnames, ["Sheet"])
            self.assertEqual(sorted_book.active["A3"].value, "B")
            self.assertEqual(sorted_book.active["C3"].value, 20)
            self.assertEqual(sorted_book.active["C3"].data_type, "n")
        self.assertEqual(cached.read_bytes(), original)

    def test_sort_drops_archived_tab_from_previous_candidate(self):
        from openpyxl.workbook.defined_name import DefinedName

        workbook = openpyxl.Workbook()
        workbook.active.title = "Raw"
        workbook.active["A1"] = "Archived source"
        sheet = workbook.create_sheet("Raw_排序")
        sheet.append(["Time", "Name", "Area", "Time", "Name", "Area"])
        sheet.append([2, "B", 20, 2.1, "B", 21])
        sheet.append([1, "A", 10, 1.1, "A", 11])
        workbook.active = sheet
        workbook.defined_names.add(DefinedName(SORT_SOURCE_NAME, attr_text="'Raw'!$A$1", hidden=True))
        source = self.work / "pre-release.xlsx"
        workbook.save(source)
        result, output = self.run_method("Sorter-0.1.0", source, Para1="0.5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with contextlib.closing(openpyxl.load_workbook(output)) as sorted_book:
            self.assertEqual(sorted_book.sheetnames, ["Raw_排序"])
            self.assertEqual(sorted_book.active["A2"].value, "A")
            self.assertEqual(sort_source_sheets(sorted_book), set())

    def test_ri_interpolates_reference_with_gap_for_both_formulas(self):
        reference = self.work / "alkanes.xlsx"
        source = self.work / "peaks.xlsx"
        workbook = openpyxl.Workbook()
        workbook.active.append(["C", "Time"])
        workbook.active.append([6, 2])
        workbook.active.append([8, 4])
        workbook.save(reference)
        peaks = openpyxl.Workbook()
        peaks.active.append(["Name", "Time"])
        peaks.active.append(["linear midpoint", 3])
        peaks.active.append(["log midpoint", math.sqrt(8)])
        peaks.active.append(["upper", 4])
        peaks.save(source)
        result, output = self.run_method(
            "RI_Calculator", source, Para1=str(reference), Para2="B,A"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with contextlib.closing(openpyxl.load_workbook(output)) as report:
            self.assertEqual([row[1:3] for row in list(report.active.values)[1:]],
                             [(717, 700), (700, 682.8), (800, 800)])

    def test_ri_rejects_duplicate_carbon_or_nonincreasing_time(self):
        method = load_method("RI_Calculator")
        for second, message in (([6, 4], "重复"), ([7, 2], "递增"), ([7, None], "有效的保留时间")):
            with self.subTest(second=second):
                workbook = openpyxl.Workbook()
                workbook.active.append([6, 2])
                workbook.active.append(second)
                path = self.work / "invalid-reference.xlsx"
                workbook.save(path)
                with self.assertRaisesRegex(ValueError, message):
                    method.load_alkanes(path)

    def test_cas_header_after_preamble_with_automatic_or_manual_column(self):
        shutil.copytree(ROOT / "Database", self.work / "Database")
        workbook = openpyxl.Workbook()
        workbook.active.append(["样品批次"])
        workbook.active.append(["CAS"])
        workbook.active.append(["83-32-9"])
        source = self.work / "preamble.xlsx"
        workbook.save(source)
        for param in ("", "A"):
            with self.subTest(param=param):
                result, output = self.run_method("CAS_to_Threshold", source, Para1=param)
                self.assertEqual(result.returncode, 0, result.stdout)
                with contextlib.closing(openpyxl.load_workbook(output)) as enriched:
                    self.assertEqual(list(enriched.active.values), [
                        ("样品批次", None), ("CAS", "嗅觉阈值"), ("83-32-9", "0.08"),
                    ])

    def test_cas_header_in_first_row_returns_original_simple_value(self):
        shutil.copytree(ROOT / "Database", self.work / "Database")
        workbook = openpyxl.Workbook()
        workbook.active.append(["CAS No."])
        workbook.active.append(["64-19-7"])
        source = self.work / "first-row.xlsx"
        workbook.save(source)
        result, output = self.run_method("CAS_to_Threshold", source)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with contextlib.closing(openpyxl.load_workbook(output)) as enriched:
            self.assertEqual(list(enriched.active.values), [("CAS No.", "嗅觉阈值"), ("64-19-7", "180")])

    def test_threshold_default_can_lookup_name_without_cas(self):
        shutil.copytree(ROOT / "Database", self.work / "Database")
        workbook = openpyxl.Workbook()
        workbook.active.append(["Sample information"])
        workbook.active.append(["Name"])
        workbook.active.append(["ACENAPHTHENE"])
        source = self.work / "names.xlsx"
        workbook.save(source)
        result, output = self.run_method("Threshold_Full", source)
        self.assertEqual(result.returncode, 0, result.stdout)
        with contextlib.closing(openpyxl.load_workbook(output)) as enriched:
            self.assertEqual(enriched.active["B3"].value, "0.08")

    def test_recognition_minimum_excludes_unclassified_records(self):
        method = load_method("Threshold_Full")
        _, cas, names = method.load_full_thresholds(ROOT / "Database/Threshold_full.json")
        workbook = openpyxl.Workbook()
        workbook.active.append(["Name"])
        workbook.active.append(["ACETIC ACID"])
        columns, stats = method.process_custom_mode(
            workbook.active, "", cas, names,
            {"match_mode": "name", "value_mode": "min", "type_filter": "recognition"},
        )
        self.assertEqual(columns[-1], [("60.0",)])
        self.assertEqual(stats["matched"], 1)

    def test_manual_cancel_aborts_workbook_and_leaves_no_output(self):
        from PyQt5.QtWidgets import QDialog

        app = QApplication.instance() or QApplication([])
        method = load_method("Threshold_Full")
        shutil.copytree(ROOT / "Database", self.work / "Database")
        workbook = openpyxl.Workbook()
        second = workbook.create_sheet("Other")
        for sheet in (workbook.active, second):
            sheet.append(["CAS"])
            sheet.append(["83-32-9"])
        source = self.work / "cancel.xlsx"
        workbook.save(source)
        parameters = json.dumps({"File": str(source), "Para2": "m"})
        cwd = Path.cwd()
        try:
            os.chdir(self.work)
            with (
                patch.object(sys, "argv", ["method", parameters]),
                patch.object(method, "ManualModeSettingsWindow") as settings,
                patch.object(method, "ManualModeDialog") as selection,
                patch.dict(os.environ, {RESULT_PATH_ENV: str(self.work / "result.json")}),
            ):
                settings.return_value.exec_.return_value = QDialog.Accepted
                settings.return_value.get_settings.return_value = {"use_cas": True, "use_name": False}
                selection.return_value.exec_.return_value = QDialog.Rejected
                self.assertEqual(run_script(method.main), METHOD_CANCELLED_EXIT_CODE)
                self.assertEqual(selection.call_count, 1)
        finally:
            os.chdir(cwd)
        self.assertFalse((self.work / "result.json").exists())
        self.assertFalse((self.work / "output").exists())

    def test_simple_and_full_thresholds_use_their_own_records(self):
        method = load_method("Threshold_Full")
        _, cas, _ = method.load_full_thresholds(ROOT / "Database/Threshold_full.json")
        simple = json.loads((ROOT / "Database/Threshold.json").read_text(encoding="utf-8"))
        self.assertEqual(simple["64-19-7"], "180")
        self.assertEqual(method.get_latest_threshold(cas["64-19-7"]["thresholds"])["value"], "99")

    def test_chemicalbook_names_unavailable_web_response(self):
        from unittest.mock import Mock

        method = load_method("Cb_Spider--AromaNexus")
        driver = Mock()
        driver.execute_script.return_value = 503
        with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
            method.check_page_status(driver)
        driver.execute_script.return_value = 200
        method.check_page_status(driver)

    def test_example_sort_and_ri(self):
        result, sorted_file = self.run_method("Sorter-0.1.0", ROOT / "example.xlsx", Para1="0.5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result, ri_file = self.run_method(
            "RI_Calculator", sorted_file, Para1=str(ROOT / "exampleRI.xlsx"), Para2="B,A"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        workbook = openpyxl.load_workbook(ri_file)
        try:
            self.assertEqual(workbook.sheetnames, ["BT-A", "BT-C", "BT-D", "BT-B"])
            for sheet in workbook:
                header = next(sheet.values)
                self.assertIn("保留指数(Kovats)", header)
                self.assertIn("保留指数(线性)", header)
        finally:
            workbook.close()

    def test_threshold_methods_and_silicon_preserve_sheets_and_styles(self):
        shutil.copytree(ROOT / "Database", self.work / "Database")
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["Name", "CAS", "Time"])
        sheet.append(["ACENAPHTHENE", "83-32-9", 2])
        sheet.append(["trimethylsilyl compound", None, 3])
        sheet["A3"].font = Font(bold=True, italic=True)
        workbook.create_sheet("Notes")["A1"] = "original"
        source = self.work / "compounds.xlsx"
        workbook.save(source)

        for method, header in (
            ("CAS_to_Threshold", "嗅觉阈值"),
            ("Threshold_Full", "嗅觉阈值(mg/L)"),
        ):
            with self.subTest(method=method):
                run, enriched = self.run_method(method, source)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn("Notes", run.stdout)
                run, marked = self.run_method("Si_Marker", enriched)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                result = openpyxl.load_workbook(marked)
                try:
                    self.assertEqual(result["Notes"]["A1"].value, "original")
                    self.assertEqual(result.active["C1"].value, header)
                    self.assertEqual(result.active["C2"].value, "0.08")
                    font = result.active["A3"].font
                    self.assertTrue(font.bold and font.italic)
                    self.assertEqual(font.color.rgb[-6:], "FF0000")
                finally:
                    result.close()

    def test_ri_reports_nist_output_after_intermediate_workbook(self):
        app = QApplication.instance() or QApplication([])
        module = load_method("RI_Calculator")
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["Name", "CAS", "Time"])
        sheet.append(["compound", "83-32-9", 3])
        source = self.work / "compounds.xlsx"
        workbook.save(source)
        reference = self.work / "reference.xlsx"
        workbook = openpyxl.Workbook()
        workbook.active.append([6, 2])
        workbook.active.append([7, 4])
        workbook.save(reference)
        control = self.work / "result.json"
        parameters = json.dumps({"File": str(source), "Para1": str(reference)})

        cwd = Path.cwd()
        try:
            os.chdir(self.work)
            with (patch.object(sys, "argv", ["method", parameters]),
                  patch.dict(os.environ, {RESULT_PATH_ENV: str(control)}),
                  patch.object(module.QMessageBox, "question", return_value=module.QMessageBox.Yes),
                  patch.object(module, "get_nist_ri", return_value=651) as lookup,
                  patch.object(module.time, "sleep")):
                module.main()
                lookup.assert_called_once_with("83-32-9", 650)
        finally:
            os.chdir(cwd)
        final = Path(json.loads(control.read_text(encoding="utf-8"))["output_file"])
        self.assertTrue(final.name.endswith("_with_RI_NIST.xlsx"))
        self.assertEqual(len(list(final.parent.glob("*_with_RI.xlsx"))), 1)
        result = openpyxl.load_workbook(final)
        try:
            self.assertEqual(list(result.active.values)[1], ("compound", 650, 651, "83-32-9", 3))
        finally:
            result.close()

    def test_chemicalbook_retries_then_writes_new_column(self):
        module = load_method("Cb_Spider--AromaNexus")
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["Name", "CAS", "Time"])
        sheet.append(["compound", "83-32-9", 3])
        found = {"CB_Odor_Desc": "floral", "CB_Odor_Threshold": "\\", "CB_Odor_Type": "\\"}
        with (patch("builtins.input", return_value="") as confirm,
              patch.object(module, "_get_data_logic", side_effect=[RuntimeError("try again"), found]),
              patch.object(module.time, "sleep")):
            columns = module.process_sheet_add_odor(sheet, "", object(), show_progress=False)
        confirm.assert_called_once()
        write_columns(sheet, *columns)
        self.assertEqual(sheet["C2"].value, "气味:floral")

    def test_cas_lookup_preserves_name_style_when_adding_a_column(self):
        module = load_method("Name_to_CAS--AromaNexus")
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(["Name", "Time"])
        sheet.append(["compound", 2])
        sheet["A2"].font = Font(bold=True)
        with (patch.object(module, "get_cas_by_name", return_value="83-32-9") as lookup,
              patch.object(module.time, "sleep")):
            columns = module.process_sheet_add_cas(sheet, "", show_progress=False)
        lookup.assert_called_once_with("compound")
        write_columns(sheet, *columns)
        self.assertEqual(list(sheet.values)[1], ("83-32-9", "compound", 2))
        self.assertTrue(sheet["B2"].font.bold)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()
        self.program = self.work / "installed"
        self.program.mkdir()
        self.updater = Updater("test/repo", "0.3.0")
        self.updater.program_dir = self.program
        (self.program / "Datahelper.py").write_text("old main", encoding="utf-8")
        (self.program / "updater.py").write_text("old updater", encoding="utf-8")

    def archive(self, members, *, prefix=""):
        path = self.work / "release.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, value in members.items():
                archive.writestr(prefix + name, value)
        return path

    def test_updates_code_without_replacing_user_files(self):
        preserved = (
            "user_data/settings.json", "config/settings.json", "config/user_workflows.json",
            "output/example.xlsx", "Methods/local_method/__init__.py",
        )
        for name in preserved:
            path = self.program / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("keep", encoding="utf-8")
        archive = self.archive({
            "Datahelper.py": "new main", "updater.py": "new updater", "method_process.py": "new worker",
            "builtin_workflows.json": '{"packaged": []}',
            "config/builtin_workflows.json": '{"new": []}', "启动.bat": "new launcher",
            **{name: "packaged version" for name in preserved if not name.startswith("Methods/")},
        }, prefix="FP-DataHelper/")
        self.updater.apply_update(archive)
        for name in preserved:
            self.assertEqual((self.program / name).read_text(encoding="utf-8"), "keep")
        self.assertEqual((self.program / "Datahelper.py").read_text(encoding="utf-8"), "new main")
        self.assertTrue((self.program / "method_process.py").is_file())
        self.assertTrue((self.program / "builtin_workflows.json").is_file())
        self.assertTrue((self.program / "启动.bat").is_file())

    def test_failed_replace_restores_previous_program_files(self):
        archive = self.archive({
            "Datahelper.py": "new main", "updater.py": "new updater",
            "Methods/New/__init__.py": "new method",
        })
        replace = os.replace

        def fail_last(src, dst):
            if Path(src).parent.name == "staged" and Path(dst).name == "Datahelper.py":
                raise PermissionError("simulated write failure")
            return replace(src, dst)

        with patch("updater.os.replace", side_effect=fail_last):
            with self.assertRaises(PermissionError):
                self.updater.apply_update(archive)
        self.assertEqual((self.program / "Datahelper.py").read_text(encoding="utf-8"), "old main")
        self.assertEqual((self.program / "updater.py").read_text(encoding="utf-8"), "old updater")
        self.assertFalse((self.program / "Methods").exists())

    def test_invalid_package_cannot_modify_program(self):
        archive = self.archive({"Datahelper.py": "new main"})
        with self.assertRaises(ValueError):
            self.updater.apply_update(archive)
        self.assertEqual((self.program / "Datahelper.py").read_text(encoding="utf-8"), "old main")


class UserConfigurationTests(unittest.TestCase):
    def test_built_in_presets_prefer_release_resource_and_support_legacy_layout(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            config = root / "config"
            config.mkdir()
            packaged = root / "builtin_workflows.json"
            (config / packaged.name).write_text('{"old": []}', encoding="utf-8")
            with patch.multiple(Datahelper, CONFIG_DIR=config, BUILTIN_WORKFLOWS_FILE=packaged):
                self.assertEqual(Datahelper.load_builtin_workflows(), {"old": []})
                packaged.write_text('{"new": []}', encoding="utf-8")
                self.assertEqual(Datahelper.load_builtin_workflows(), {"new": []})

    def test_legacy_files_are_read_and_changes_go_to_user_directory(self):
        with tempfile.TemporaryDirectory() as name:
            config = Path(name) / "config"
            config.mkdir()
            local = Path(name) / "user_data"
            old_settings = config / "settings.json"
            old_settings.write_text('{"auto_check_update": false}', encoding="utf-8")
            (config / "user_workflows.json").write_text('{"old": []}', encoding="utf-8")
            with patch.multiple(Datahelper, CONFIG_DIR=config, USER_DATA_DIR=local,
                                SETTINGS_FILE=local / "settings.json",
                                USER_WORKFLOWS_FILE=local / "user_workflows.json",
                                BUILTIN_WORKFLOWS_FILE=config / "builtin_workflows.json"):
                self.assertFalse(Datahelper.load_settings()["auto_check_update"])
                self.assertEqual(Datahelper.load_workflows(), {"old": []})
                Datahelper.save_settings({"auto_check_update": True})
                Datahelper.save_user_config(Datahelper.USER_WORKFLOWS_FILE, {})
                self.assertTrue(Datahelper.load_settings()["auto_check_update"])
                self.assertEqual(Datahelper.load_workflows(), {})
                self.assertEqual(old_settings.read_text(encoding="utf-8"), '{"auto_check_update": false}')
