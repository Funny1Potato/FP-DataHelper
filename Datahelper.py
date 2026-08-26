# -*- coding: utf-8 -*-
import sys
import os
import json
import base64

# ==================== 环境兼容 ====================
# 自动检测是否为完整包环境（内嵌Python）
_embedded_python_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "python-3.10.11-embed-amd64")
if os.path.isdir(_embedded_python_dir):
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(
        _embedded_python_dir, 'Lib', 'site-packages', 'PyQt5', 'Qt5', 'plugins'
    )

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox, QProgressDialog
from PyQt5.QtCore import QProcess, QProcessEnvironment

# 版本信息
__version__ = "0.2.1"
__repo__ = "Funny1Potato/FP-DataHelper"

# 导入更新模块
from updater import Updater, CheckThread, DownloadThread


# 图标 base64 数据 (64x64)
ICON_BASE64 = "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"


# ==================== UI 定义 ====================
class main_Ui_Form(object):
    def setupUi(self, widget):
        widget.setObjectName("Form")
        widget.resize(1280, 720)

        # 主布局：左右分栏
        main_layout = QtWidgets.QHBoxLayout(widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # ========== 左侧：输出区域 ==========
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setSpacing(5)

        self.output_label = QtWidgets.QLabel(widget)
        self.output_label.setText("输出信息：")
        left_layout.addWidget(self.output_label)

        self.output_area = QtWidgets.QPlainTextEdit(widget)
        self.output_area.setReadOnly(True)
        font = QtGui.QFont("Consolas", 9)
        self.output_area.setFont(font)
        left_layout.addWidget(self.output_area)

        # 输入区域（用于程序交互）
        input_layout = QtWidgets.QHBoxLayout()
        self.input_label = QtWidgets.QLabel(widget)
        self.input_label.setText("输入：")
        input_layout.addWidget(self.input_label)
        self.cmd_input = QtWidgets.QLineEdit(widget)
        self.cmd_input.setMinimumHeight(28)
        self.cmd_input.setPlaceholderText("程序需要输入时在此输入，按回车或点击发送")
        self.cmd_input.setEnabled(False)
        input_layout.addWidget(self.cmd_input, stretch=1)
        self.send_btn = QtWidgets.QPushButton(widget)
        self.send_btn.setText("发送")
        self.send_btn.setMinimumWidth(60)
        self.send_btn.setEnabled(False)
        input_layout.addWidget(self.send_btn)
        left_layout.addLayout(input_layout)

        # 清空按钮
        self.clear_btn = QtWidgets.QPushButton(widget)
        self.clear_btn.setText("清空输出")
        self.clear_btn.setObjectName("clear_btn")
        left_layout.addWidget(self.clear_btn, alignment=QtCore.Qt.AlignRight)

        main_layout.addLayout(left_layout, stretch=1)

        # ========== 右侧：参数和按钮 ==========
        self.right_layout = QtWidgets.QVBoxLayout()
        self.right_layout.setSpacing(30)

        # 方法选择
        method_layout = QtWidgets.QHBoxLayout()
        self.label = QtWidgets.QLabel(widget)
        self.label.setObjectName("label")
        self.label.setMinimumWidth(45)
        method_layout.addWidget(self.label)
        self.ChooseMethods = QtWidgets.QComboBox(widget)
        self.ChooseMethods.setFixedHeight(50)
        self.ChooseMethods.setObjectName("ChooseMethods")
        method_layout.addWidget(self.ChooseMethods, stretch=1)
        self.right_layout.addLayout(method_layout)

        # 文件选择
        file_layout = QtWidgets.QHBoxLayout()
        self.label_2 = QtWidgets.QLabel(widget)
        self.label_2.setObjectName("label_2")
        self.label_2.setMinimumWidth(45)
        file_layout.addWidget(self.label_2)
        self.file = QtWidgets.QLineEdit(widget)
        self.file.setFixedHeight(50)
        self.file.setObjectName("file")
        file_layout.addWidget(self.file)
        self.choosefile = QtWidgets.QToolButton(widget)
        self.choosefile.setFixedHeight(50)
        self.choosefile.setObjectName("choosefile")
        file_layout.addWidget(self.choosefile)
        self.right_layout.addLayout(file_layout)

        # 参数1
        para1_layout = QtWidgets.QHBoxLayout()
        self.label_3 = QtWidgets.QLabel(widget)
        self.label_3.setObjectName("label_3")
        self.label_3.setMinimumWidth(45)
        para1_layout.addWidget(self.label_3)
        self.input1 = QtWidgets.QLineEdit(widget)
        self.input1.setFixedHeight(50)
        self.input1.setObjectName("input1")
        para1_layout.addWidget(self.input1)
        self.choosefile_para1 = QtWidgets.QToolButton(widget)
        self.choosefile_para1.setFixedHeight(50)
        self.choosefile_para1.setText("...")
        self.choosefile_para1.setObjectName("choosefile_para1")
        para1_layout.addWidget(self.choosefile_para1)
        self.right_layout.addLayout(para1_layout)

        # 参数2
        para2_layout = QtWidgets.QHBoxLayout()
        self.label_4 = QtWidgets.QLabel(widget)
        self.label_4.setObjectName("label_4")
        self.label_4.setMinimumWidth(45)
        para2_layout.addWidget(self.label_4)
        self.input2 = QtWidgets.QLineEdit(widget)
        self.input2.setFixedHeight(50)
        self.input2.setObjectName("input2")
        para2_layout.addWidget(self.input2)
        self.right_layout.addLayout(para2_layout)

        # 参数3
        para3_layout = QtWidgets.QHBoxLayout()
        self.label_5 = QtWidgets.QLabel(widget)
        self.label_5.setObjectName("label_5")
        self.label_5.setMinimumWidth(45)
        para3_layout.addWidget(self.label_5)
        self.input3 = QtWidgets.QLineEdit(widget)
        self.input3.setFixedHeight(50)
        self.input3.setObjectName("input3")
        para3_layout.addWidget(self.input3)
        self.right_layout.addLayout(para3_layout)

        # 弹性空间（将按钮推到底部）
        self.right_layout.addStretch(1)

        # 按钮行
        btn_layout = QtWidgets.QHBoxLayout()
        self.option = QtWidgets.QPushButton(widget)
        self.option.setMinimumSize(QtCore.QSize(160, 50))
        self.option.setObjectName("option")
        btn_layout.addWidget(self.option)
        self.run = QtWidgets.QPushButton(widget)
        self.run.setMinimumSize(QtCore.QSize(160, 50))
        self.run.setObjectName("run")
        btn_layout.addWidget(self.run)
        self.right_layout.addLayout(btn_layout)

        main_layout.addLayout(self.right_layout, stretch=1)

        self.retranslateUi(widget)
        QtCore.QMetaObject.connectSlotsByName(widget)

    def retranslateUi(self, widget):
        _translate = QtCore.QCoreApplication.translate
        widget.setWindowTitle(_translate("Form", f"FP-DataHelper - {__version__}"))
        self.run.setText(_translate("Form", "运行"))
        self.label.setText(_translate("Form", "方法："))
        self.label_2.setText(_translate("Form", "文件："))
        self.label_3.setText(_translate("Form", "参数1："))
        self.label_4.setText(_translate("Form", "参数2："))
        self.label_5.setText(_translate("Form", "参数3："))
        self.choosefile.setText(_translate("Form", "选择文件"))
        self.option.setText(_translate("Form", "选项"))


# ==================== 工具函数 ====================
# 设置文件路径
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

def load_settings():
    """加载设置"""
    default = {"auto_check_update": True}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default

def save_settings(settings):
    """保存设置"""
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)

def get_folders(path):
    folders = []
    files = os.listdir(path)
    for file in files:
        if os.path.isdir(os.path.join(path, file)):
            folders.append(file)
    return folders


# ==================== 主窗口 ====================
class MainForm(QMainWindow, main_Ui_Form):
    def __init__(self, parent=None):
        super(MainForm, self).__init__(parent)
        self.setWindowTitle(f"FP-DataHelper - {__version__}")
        self.resize(1280, 720)  # 设置主窗口初始大小
        self.aspect_ratio = 16 / 9  # 宽高比 16:9
        self.base_width = 1280  # 基准宽度
        self.base_height = 720  # 基准高度
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        self.setupUi(central_widget)

        self.process = None

        # 保存需要缩放的控件引用
        self._scalable_widgets = []
        self._init_scalable_widgets()

        # 方法列表
        Methods = get_folders("./Methods")
        self.ChooseMethods.addItems(["请选择方法"])
        self.ChooseMethods.addItems(Methods)
        self.ChooseMethods.setCurrentIndex(0)
        self.ChooseMethods.currentIndexChanged.connect(self.Methods_changed)

        # 文件选择
        self.file.setPlaceholderText("请选择文件")
        self.choosefile.clicked.connect(self.openFile)

        # Para1 文件选择
        self.choosefile_para1.clicked.connect(self.openFileForPara1)

        # 按钮
        self.option.clicked.connect(self.option_clicked)
        self.run.clicked.connect(self.run_clicked)
        self.clear_btn.clicked.connect(self.clear_output)

        # 输入功能
        self.cmd_input.returnPressed.connect(self.send_input)
        self.send_btn.clicked.connect(self.send_input)

        # 初始化缩放控件
        self._init_scalable_widgets()
        # 初始缩放
        self._update_scale(1.0)

        # 初始化更新器
        self.updater = Updater(__repo__, __version__)
        self.check_thread = None
        self.download_thread = None
        self._is_manual_check = False
        # 启动时检查更新（根据设置）
        settings = load_settings()
        if settings.get("auto_check_update", True):
            self._check_update()

    def _init_scalable_widgets(self):
        """初始化需要缩放的控件列表"""
        self._scalable_widgets = [
            self.output_label, self.label, self.label_2, self.label_3, self.label_4, self.label_5,
            self.input_label
        ]

    def _update_scale(self, scale_factor):
        """更新所有可缩放元素的大小"""
        # 计算缩放后的字体大小
        base_font_size = 10
        new_font_size = max(8, int(base_font_size * scale_factor))

        # 更新输入框和按钮高度
        base_height = 50
        new_height = max(35, int(base_height * scale_factor))

        # 更新按钮大小
        btn_base_width = 160
        btn_base_height = 50
        new_btn_width = max(100, int(btn_base_width * scale_factor))
        new_btn_height = max(35, int(btn_base_height * scale_factor))

        # 更新行间距
        base_spacing = 30
        new_spacing = max(15, int(base_spacing * scale_factor))
        self.right_layout.setSpacing(new_spacing)

        # 应用到输入框
        for widget in [self.ChooseMethods, self.file, self.choosefile,
                       self.input1, self.choosefile_para1,
                       self.input2, self.input3,
                       self.cmd_input, self.send_btn]:
            widget.setFixedHeight(new_height)

        # 应用到按钮
        for widget in [self.option, self.run]:
            widget.setFixedSize(QtCore.QSize(new_btn_width, new_btn_height))

        # 更新字体
        font = QtGui.QFont()
        font.setPointSize(new_font_size)

        # 应用到标签
        for widget in self._scalable_widgets:
            widget.setFont(font)

        # 应用到输入框
        input_font = QtGui.QFont()
        input_font.setPointSize(new_font_size)
        for widget in [self.ChooseMethods, self.file, self.input1,
                       self.input2, self.input3, self.cmd_input]:
            widget.setFont(input_font)

        # 更新按钮字体
        for widget in [self.option, self.run, self.clear_btn, self.send_btn,
                       self.choosefile, self.choosefile_para1]:
            widget.setFont(font)

        # 更新输出区域字体
        output_font = QtGui.QFont("Consolas", max(7, int(9 * scale_factor)))
        self.output_area.setFont(output_font)

    def openFile(self):
        fileName, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "xlsx Files (*.xlsx);;xls Files (*.xls);;All Files (*)")
        if fileName:
            self.file.setText(fileName)

    def openFileForPara1(self):
        fileName, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "xlsx Files (*.xlsx);;xls Files (*.xls);;All Files (*)")
        if fileName:
            self.input1.setText(fileName)

    def Methods_changed(self, index):
        text = self.ChooseMethods.currentText()
        try:
            with open(f"./Methods/{text}/Config.json", "r", encoding='utf-8') as file:
                config_dict = json.loads(file.read())
            self.input1.setPlaceholderText(config_dict.get("Para1", ""))
            self.input2.setPlaceholderText(config_dict.get("Para2", ""))
            self.input3.setPlaceholderText(config_dict.get("Para3", ""))
        except:
            self.input1.setPlaceholderText("")
            self.input2.setPlaceholderText("")
            self.input3.setPlaceholderText("")

    def option_clicked(self):
        """打开设置对话框"""
        settings = load_settings()
        
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("设置")
        dialog.setMinimumWidth(350)
        
        layout = QtWidgets.QVBoxLayout(dialog)
        
        # 自动更新开关
        auto_update_check = QtWidgets.QCheckBox("启动时自动检查更新")
        auto_update_check.setChecked(settings.get("auto_check_update", True))
        layout.addWidget(auto_update_check)
        
        # 手动检查更新按钮
        check_update_btn = QtWidgets.QPushButton("立即检查更新")
        check_update_btn.clicked.connect(lambda: self._manual_check_update(dialog))
        layout.addWidget(check_update_btn)
        
        layout.addSpacing(20)
        
        # 确定/取消按钮
        btn_layout = QtWidgets.QHBoxLayout()
        ok_btn = QtWidgets.QPushButton("确定")
        cancel_btn = QtWidgets.QPushButton("取消")
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            settings["auto_check_update"] = auto_update_check.isChecked()
            save_settings(settings)
    
    def _manual_check_update(self, parent_dialog):
        """手动检查更新"""
        parent_dialog.accept()  # 关闭设置对话框
        self._check_update(force=True)

    def resizeEvent(self, event):
        """窗口自由缩放，内部内容按16:9排布"""
        new_size = event.size()
        width = new_size.width()
        height = new_size.height()

        # 最小边距
        min_margin = 20

        # 计算16:9区域
        height_from_width = int(width * 9 / 16)
        width_from_height = int(height * 16 / 9)

        if height_from_width <= height:
            # 宽度为主，垂直居中
            content_width = width
            content_height = height_from_width
            margin_top = max(min_margin, (height - content_height) // 2)
            margin_bottom = max(min_margin, height - content_height - margin_top)
            margin_left = min_margin
            margin_right = min_margin
        else:
            # 高度为主，水平居中
            content_width = width_from_height
            content_height = height
            margin_top = min_margin
            margin_bottom = min_margin
            margin_left = max(min_margin, (width - content_width) // 2)
            margin_right = max(min_margin, width - content_width - margin_left)

        # 设置布局边距
        self.centralWidget().layout().setContentsMargins(
            margin_left, margin_top, margin_right, margin_bottom
        )

        # 计算缩放因子
        scale_factor = content_width / self.base_width
        self._update_scale(scale_factor)

        super().resizeEvent(event)

    def clear_output(self):
        self.output_area.clear()

    def append_output(self, text):
        self.output_area.appendPlainText(text.rstrip('\n\r'))

    def send_input(self):
        """发送输入到子进程"""
        if self.process and self.process.state() == QProcess.Running:
            text = self.cmd_input.text()
            if text:
                # 显示用户输入
                self.append_output(f">>> {text}")
                # 发送到子进程
                self.process.write((text + '\n').encode('gbk'))
                self.cmd_input.clear()

    def set_input_enabled(self, enabled):
        """启用/禁用输入区域"""
        self.cmd_input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        if enabled:
            self.cmd_input.setFocus()

    def run_clicked(self):
        text = self.ChooseMethods.currentText()
        if text == "请选择方法":
            self.append_output("请先选择一个方法")
            return

        path = f"./Methods/{text}/__init__.py"
        if not os.path.exists(path):
            self.append_output(f"错误：找不到方法文件 {path}")
            return

        para1 = self.input1.text() or ""
        para2 = self.input2.text() or ""
        para3 = self.input3.text() or ""
        file = self.file.text() or ""

        if not file and "RI" not in text:
            self.append_output("请先选择文件")
            return

        param = json.dumps({"Para1": para1, "Para2": para2, "Para3": para3, "File": file})

        # 禁用运行按钮，启用输入
        self.run.setEnabled(False)
        self.run.setText("运行中...")
        self.set_input_enabled(True)
        self.append_output(f"开始执行: {text}")
        self.append_output("-" * 40)

        # 使用 QProcess
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.on_ready_read)
        self.process.finished.connect(self.on_finished)

        # 禁用 Python 输出缓冲，确保实时显示
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self.process.setProcessEnvironment(env)

        self.process.start(sys.executable, [path, param])

    def on_ready_read(self):
        if self.process:
            data = self.process.readAllStandardOutput().data()
            try:
                text = data.decode('gbk', errors='replace')
            except:
                text = data.decode('utf-8', errors='replace')
            if text:
                # 清理 tqdm 控制字符
                lines = text.split('\r')
                for line in lines:
                    clean = line.strip()
                    if clean:
                        self.output_area.appendPlainText(clean)
                # 滚动到底部
                scrollbar = self.output_area.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())

    def on_finished(self, exit_code, exit_status):
        self.run.setEnabled(True)
        self.run.setText("运行")
        self.set_input_enabled(False)
        self.append_output("-" * 40)
        self.append_output(f"执行完成 (退出码: {exit_code})")
        self.process = None

    # ==================== 更新相关方法 ====================
    def _check_update(self, force=False):
        """启动后台检查更新
        force: True表示强制检查（手动），False表示根据设置决定
        """
        if not force:
            settings = load_settings()
            if not settings.get("auto_check_update", True):
                return
        
        self._is_manual_check = force  # 记录是否手动检查
        
        self.check_thread = CheckThread(self.updater)
        self.check_thread.update_found.connect(self._on_update_found)
        self.check_thread.check_done.connect(self._on_check_done)
        self.check_thread.check_failed.connect(self._on_check_failed)
        self.check_thread.start()
    
    def _on_check_done(self):
        """检查完成，无更新"""
        if self._is_manual_check:
            QMessageBox.information(self, "检查更新", "当前已是最新版本！")
    
    def _on_check_failed(self, error: str):
        """检查失败"""
        if self._is_manual_check:
            QMessageBox.warning(self, "检查更新", f"检查更新失败：\n{error}")

    def _on_update_found(self, info: dict):
        """发现新版本时弹窗提示"""
        version = info["version"]
        changelog = info["changelog"]
        
        msg = QMessageBox(self)
        msg.setWindowTitle("发现新版本")
        msg.setIcon(QMessageBox.Information)
        msg.setText(f"发现新版本 v{version}")
        msg.setInformativeText(f"更新内容：\n{changelog}")
        
        update_btn = msg.addButton("立即更新", QMessageBox.AcceptRole)
        skip_btn = msg.addButton("跳过此版本", QMessageBox.RejectRole)
        later_btn = msg.addButton("稍后再说", QMessageBox.RejectRole)
        
        msg.exec_()
        
        clicked = msg.clickedButton()
        if clicked == update_btn:
            self._start_download(info["download_url"])
        elif clicked == skip_btn:
            # TODO: 保存跳过的版本号到本地配置
            pass

    def _start_download(self, url: str):
        """开始下载更新"""
        self.progress_dialog = QProgressDialog("正在下载更新...", "取消", 0, 100, self)
        self.progress_dialog.setWindowTitle("下载更新")
        self.progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(0)
        
        self.download_thread = DownloadThread(self.updater, url)
        self.download_thread.progress.connect(self._on_download_progress)
        self.download_thread.finished.connect(self._on_download_finished)
        self.download_thread.error.connect(self._on_download_error)
        
        self.progress_dialog.canceled.connect(self._cancel_download)
        self.download_thread.start()

    def _on_download_progress(self, downloaded: int, total: int):
        """更新下载进度"""
        if total > 0:
            percent = int(downloaded * 100 / total)
            self.progress_dialog.setValue(percent)
            self.progress_dialog.setLabelText(f"正在下载更新... {percent}%\n已下载: {downloaded // 1024}KB / {total // 1024}KB")

    def _on_download_finished(self, zip_path: str):
        """下载完成，应用更新"""
        self.progress_dialog.close()
        
        try:
            self.updater.apply_update(zip_path)
            
            msg = QMessageBox(self)
            msg.setWindowTitle("更新完成")
            msg.setIcon(QMessageBox.Information)
            msg.setText("更新完成！需要重启程序生效。")
            msg.setInformativeText('点击"立即重启"将关闭并重新启动程序。')
            
            restart_btn = msg.addButton("立即重启", QMessageBox.AcceptRole)
            later_btn = msg.addButton("稍后重启", QMessageBox.RejectRole)
            
            msg.exec_()
            
            if msg.clickedButton() == restart_btn:
                self._restart_app()
        except Exception as e:
            QMessageBox.critical(self, "更新失败", f"应用更新时出错：\n{str(e)}")

    def _on_download_error(self, error: str):
        """下载失败"""
        self.progress_dialog.close()
        QMessageBox.warning(self, "下载失败", f"下载更新失败：\n{error}\n\n请稍后重试。")

    def _cancel_download(self):
        """取消下载"""
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.terminate()
            self.download_thread.wait()

    def _restart_app(self):
        """重启应用程序"""
        import subprocess
        # 启动新进程
        subprocess.Popen([sys.executable] + sys.argv)
        # 关闭当前进程
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # 设置应用程序图标（从 base64 加载）
    icon_data = base64.b64decode(ICON_BASE64)
    icon_pixmap = QtGui.QPixmap()
    icon_pixmap.loadFromData(icon_data)
    app.setWindowIcon(QtGui.QIcon(icon_pixmap))
    myWin = MainForm()
    myWin.show()
    sys.exit(app.exec_())
