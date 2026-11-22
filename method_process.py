"""Run a method with the same process and result handling in both GUI modes."""

import codecs
import json
import re
import sys
from pathlib import Path

from PyQt5.QtCore import QObject, QProcess, QProcessEnvironment, QTemporaryDir, QTimer, pyqtSignal

from method_support import CANCEL_PATH_ENV, METHOD_CANCELLED_EXIT_CODE, RESULT_PATH_ENV


PROGRAM_DIR = Path(__file__).resolve().parent
RETIRED_SORTER = "Sorter-0.0.2"
LEGACY_OUTPUT = re.compile(r"(?:文件保存至[：:]|文件名为)[ \t]*(.+)")


class MethodProcess(QObject):
    output_ready = pyqtSignal(str)
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.setWorkingDirectory(str(PROGRAM_DIR))
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.on_finished)
        self.process.errorOccurred.connect(self.on_error)
        self.stop_timer = QTimer(self)
        self.stop_timer.setSingleShot(True)
        self.stop_timer.timeout.connect(self.process.kill)
        self.result_dir = QTemporaryDir()
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.output_tail = ""
        self.stopping = False

    def start(self, method, parameters):
        if self.stopping:
            self.cancelled.emit()
            return
        if method.casefold() == RETIRED_SORTER.casefold():
            self.failed.emit(f"{RETIRED_SORTER} 已移除，请将此步骤替换为 Sorter-0.1.0。")
            return
        if not self.result_dir.isValid():
            self.failed.emit("无法创建任务结果的临时目录。")
            return
        path = PROGRAM_DIR / "Methods" / method / "__init__.py"
        self.result_path = Path(self.result_dir.filePath("result.json"))
        self.cancel_path = Path(self.result_dir.filePath("cancel"))
        self.graceful_stop = method == "Cb_Spider--AromaNexus"
        env = QProcessEnvironment.systemEnvironment()
        env.insert(RESULT_PATH_ENV, str(self.result_path))
        env.insert(CANCEL_PATH_ENV, str(self.cancel_path))
        env.insert("PYTHONIOENCODING", "utf-8")
        self.process.setProcessEnvironment(env)
        self.process.start(sys.executable, ["-B", "-u", "-X", "utf8", str(path), json.dumps(parameters)])

    def send_input(self, text):
        if self.process.state() != QProcess.Running or self.stopping:
            return False
        return self.process.write((text + "\n").encode("utf-8")) >= 0

    def stop(self):
        if self.stopping:
            return
        self.stopping = True
        if self.process.state() == QProcess.Running and self.graceful_stop:
            try:
                self.cancel_path.touch()
            except OSError:
                pass
            self.process.closeWriteChannel()
            self.stop_timer.start(5000)
            return
        self.process.kill()

    def read_output(self, final=False):
        data = bytes(self.process.readAllStandardOutput())
        text = self.decoder.decode(data, final=final)
        if text:
            self.output_tail = (self.output_tail + text)[-65536:]
            self.output_ready.emit(text)

    def on_error(self, error):
        if error == QProcess.FailedToStart:
            if self.stopping:
                self.cancelled.emit()
            else:
                self.failed.emit(self.process.errorString())

    def on_finished(self, exit_code, exit_status):
        self.stop_timer.stop()
        self.read_output(final=True)
        if self.stopping or (exit_code == METHOD_CANCELLED_EXIT_CODE and exit_status == QProcess.NormalExit):
            self.cancelled.emit()
            return
        if exit_code or exit_status != QProcess.NormalExit:
            self.failed.emit(f"方法执行失败（退出码 {exit_code}），请查看上方日志。")
            return
        try:
            output = self.read_result()
        except (OSError, TypeError, ValueError) as error:
            self.failed.emit(str(error))
        else:
            self.succeeded.emit(str(output))

    def read_result(self):
        if self.result_path.exists():
            result = json.loads(self.result_path.read_text(encoding="utf-8"))
            if not isinstance(result, dict) or not isinstance(result.get("output_file"), str):
                raise ValueError("方法结果缺少有效的输出路径。")
            filename = result["output_file"]
        else:
            # Older method scripts reported the output only in their log.
            matches = LEGACY_OUTPUT.findall(self.output_tail)
            filename = matches[-1].strip() if matches else ""
        if not filename:
            raise ValueError("方法未产出结果文件，请查看上方日志。")
        path = (PROGRAM_DIR / filename).resolve()
        if path.suffix.lower() != ".xlsx" or not path.is_file():
            raise ValueError(f"结果不是可用的 Excel 文件：{path}")
        return path
