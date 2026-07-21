# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'connect_me.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!
import sys
import os
from tqdm import tqdm
import json
import subprocess
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog
from main import main_Ui_Form

#获取文件目录
def get_folders(path):
    folders = []
    files = os.listdir(path)
    for file in files:
        if os.path.isdir(os.path.join(path, file)):
            folders.append(file)
    return folders

#主窗口
class MainForm(QMainWindow, main_Ui_Form):
    def __init__(self, parent=None):
        super(MainForm, self).__init__(parent)
        self.setupUi(self)
        #方法程序选择
        Methods = get_folders("./Methods")
        self.ChooseMethods.addItems(["请选择方法"])
        self.ChooseMethods.addItems(Methods)#读取方法程序目录
        self.ChooseMethods.setCurrentIndex(0)#设置默认方法（"请选择方法"）
        self.ChooseMethods.show()#显示方法列表
        self.ChooseMethods.currentIndexChanged.connect(self.Methods_changed)#加载方法文件
        
        #文件选择
        self.file.setPlaceholderText("请选择文件")#默认提示文本
        self.choosefile.clicked.connect(self.openFile)
        
        #设置
        self.option.clicked.connect(self.option_clicked)
        
        #运行
        self.run.clicked.connect(self.run_clicked)
    
    #打开文件选择对话框
    def openFile(self):
        fileName, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "xlsx Files (*.xlsx);;xls Files (*.xls);;All Files (*)")
        self.file.setText(fileName)#显示选择的文件路径
    
    #加载方法文件配置
    def Methods_changed(self, index):
        text = self.ChooseMethods.currentText()
        try:
            # 从文件中加载JSON字符串并转换为对象
            with open(f"./Methods/{text}/Config.json", "r", encoding='utf-8') as file:
                loaded_config = file.read()
                config_dict = json.loads(loaded_config)
            self.input1.setPlaceholderText(config_dict["Para1"])
            self.input2.setPlaceholderText(config_dict["Para2"])
            self.input3.setPlaceholderText(config_dict["Para3"])
        except:
            self.input1.setPlaceholderText("")
            self.input2.setPlaceholderText("")
            self.input3.setPlaceholderText("")
            
    #打开设置界面
    def option_clicked(self):
        return
    
    #运行方法文件
    def run_clicked(self):
        text = self.ChooseMethods.currentText()
        path = f"./Methods/{text}/__init__.py"
        para1 = self.input1.text()
        para2 = self.input2.text()
        para3 = self.input3.text()
        file = self.file.text()
        param = {"Para1": para1, "Para2": para2, "Para3": para3, "File": file}
        subprocess.run(['python', path, json.dumps(param)])


#可能会用到的进度条代码
def a114514():        
    for i in tqdm(range(1, 60)):
        """
        代码
        """
        # 假设这代码部分需要0.05s，循环执行60次
        time.sleep(0.05)


        

if __name__ == "__main__":
    #固定的，PyQt5程序都需要QApplication对象。sys.argv是命令行参数列表，确保程序可以双击运行
    app = QApplication(sys.argv)
    #初始化
    myWin = MainForm()
    #将窗口控件显示在屏幕上
    myWin.show()
    #程序运行，sys.exit方法确保程序完整退出。
    sys.exit(app.exec_())