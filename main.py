# main.py
import sys
import os
import textwrap
from datetime import datetime
from PyQt5 import QtCore
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QLineEdit, QPushButton,
    QProgressBar, QFileDialog, QMessageBox, QTabWidget, QVBoxLayout,
    QGridLayout, QHBoxLayout, QComboBox, QCheckBox, QTreeWidget,
    QTreeWidgetItem, QAction, QMenu
)
from PyQt5.QtCore import Qt
from exchange_worker import ExchangeWorker  # assumes it accepts send_file flag


class ConsoleWidget(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderLabels(["Time", "Message"])
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(False)
        self.setAllColumnsShowFocus(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.filter_text = ""
        # режим автoраскрытия/сворачивания новых сообщений: 'expand' | 'collapse' | None
        self._expand_mode = None

    def log(self, msg: str):
        # проверяем: если сейчас скролл внизу — будем "прилипать"
        sb = self.verticalScrollBar()
        at_bottom = (sb.value() == sb.maximum())

        now = datetime.now().strftime("%H:%M:%S")
        lines = msg.splitlines()
        first = lines[0] if lines else ""
        item = QTreeWidgetItem([now, first])
        # wrap and children
        for ln in lines[1:]:
            wrapped = textwrap.wrap(ln, width=120) or [""]
            for part in wrapped:
                child = QTreeWidgetItem(["", part])
                item.addChild(child)
        self.addTopLevelItem(item)
        # filter
        full = "\n".join([item.text(1)] + [item.child(i).text(1) for i in range(item.childCount())])
        hide = bool(self.filter_text and self.filter_text.lower() not in full.lower())
        item.setHidden(hide)
        for i in range(item.childCount()):
            item.child(i).setHidden(hide)

        # применяем sticky-режим раскрутки
        if self._expand_mode == 'expand':
            self.expandAll()
        elif self._expand_mode == 'collapse':
            self.collapseAll()

        # если были внизу — скроллим вниз
        if at_bottom:
            self.scrollToBottom()

        return item

    def set_filter(self, text: str):
        self.filter_text = text
        lower = text.lower()
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            full = "\n".join([it.text(1)] + [it.child(j).text(1) for j in range(it.childCount())])
            hide = bool(lower and lower not in full.lower())
            it.setHidden(hide)
            for j in range(it.childCount()):
                it.child(j).setHidden(hide)

    def _show_context_menu(self, pos):
        item = self.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        copy = QAction("Copy Message", self)
        expand = QAction("Expand All", self)
        collapse = QAction("Collapse All", self)
        menu.addAction(copy)
        menu.addSeparator()
        menu.addAction(expand)
        menu.addAction(collapse)
        act = menu.exec_(self.viewport().mapToGlobal(pos))
        if act == copy:
            root = item
            while root.parent():
                root = root.parent()
            parts = [root.text(1)] + [root.child(i).text(1) for i in range(root.childCount())]
            QApplication.clipboard().setText("\n".join(parts))
        elif act == expand:
            self.expandAll()
            self._expand_mode = 'expand'
        elif act == collapse:
            self.collapseAll()
            self._expand_mode = 'collapse'


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.log_file = None
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("1С-Битрикс: Обмен с сайтом")
        self.resize(900, 700)

        central = QWidget(self)
        self.setCentralWidget(central)
        main_l = QVBoxLayout(central)

        self.tabs = QTabWidget()
        main_l.addWidget(self.tabs)

        # --- Tab 1: Стандартный обмен (имя файла только) ---
        t1 = QWidget()
        g1 = QGridLayout(t1)
        g1.addWidget(QLabel("URL:"), 0, 0)
        self.url1 = QLineEdit()
        g1.addWidget(self.url1, 0, 1, 1, 3)

        g1.addWidget(QLabel("Login:"), 1, 0)
        self.login1 = QLineEdit()
        g1.addWidget(self.login1, 1, 1, 1, 3)

        g1.addWidget(QLabel("Password:"), 2, 0)
        self.password1 = QLineEdit()
        self.password1.setEchoMode(QLineEdit.Password)
        g1.addWidget(self.password1, 2, 1, 1, 3)

        g1.addWidget(QLabel("Exchange Type:"), 3, 0)
        self.type1 = QComboBox()
        self.type1.addItems(["catalog"]) # self.type1.addItems(["catalog", "sale"]) было, пока скрыл
        self.type1.setEditable(True)
        g1.addWidget(self.type1, 3, 1, 1, 3)

        g1.addWidget(QLabel("Remote File Name:"), 4, 0)
        self.filename1 = QLineEdit()
        g1.addWidget(self.filename1, 4, 1, 1, 3)

        g1.addWidget(QLabel("Progress:"), 5, 0)
        self.progress1 = QProgressBar()
        g1.addWidget(self.progress1, 5, 1, 1, 3)

        g1.addWidget(QLabel("Filter:"), 6, 0)
        self.filter1 = QLineEdit()
        g1.addWidget(self.filter1, 6, 1, 1, 3)

        self.console1 = ConsoleWidget()
        g1.addWidget(self.console1, 7, 0, 4, 4)

        btn1 = QHBoxLayout()
        self.start1 = QPushButton("Start")
        self.stop1 = QPushButton("Stop")
        self.stop1.setEnabled(False)
        btn1.addWidget(self.start1)
        btn1.addWidget(self.stop1)
        g1.addLayout(btn1, 11, 0, 1, 4)

        self.log_chk1 = QCheckBox("Log to file")
        g1.addWidget(self.log_chk1, 12, 0)
        self.log_path1 = QLineEdit()
        self.log_path1.setEnabled(False)
        g1.addWidget(self.log_path1, 12, 1, 1, 2)
        self.log_b1 = QPushButton("Browse")
        self.log_b1.setEnabled(False)
        g1.addWidget(self.log_b1, 12, 3)

        self.tabs.addTab(t1, "Стандартный обмен")

        # --- Tab 2: Загрузка файла ---
        t2 = QWidget()
        g2 = QGridLayout(t2)
        g2.addWidget(QLabel("URL:"), 0, 0)
        self.url2 = QLineEdit()
        g2.addWidget(self.url2, 0, 1, 1, 3)

        g2.addWidget(QLabel("Login:"), 1, 0)
        self.login2 = QLineEdit()
        g2.addWidget(self.login2, 1, 1, 1, 3)

        g2.addWidget(QLabel("Password:"), 2, 0)
        self.password2 = QLineEdit()
        self.password2.setEchoMode(QLineEdit.Password)
        g2.addWidget(self.password2, 2, 1, 1, 3)

        g2.addWidget(QLabel("Exchange Type:"), 3, 0)
        self.type2 = QComboBox()
        self.type2.addItems(["catalog", "sale"])
        self.type2.setEditable(True)
        g2.addWidget(self.type2, 3, 1, 1, 3)

        g2.addWidget(QLabel("File XML/ZIP:"), 4, 0)
        self.file2 = QLineEdit()
        g2.addWidget(self.file2, 4, 1, 1, 2)
        self.browse2 = QPushButton("Browse...")
        g2.addWidget(self.browse2, 4, 3)

        g2.addWidget(QLabel("Progress:"), 5, 0)
        self.progress2 = QProgressBar()
        g2.addWidget(self.progress2, 5, 1, 1, 3)

        g2.addWidget(QLabel("Filter:"), 6, 0)
        self.filter2 = QLineEdit()
        g2.addWidget(self.filter2, 6, 1, 1, 3)

        self.console2 = ConsoleWidget()
        g2.addWidget(self.console2, 7, 0, 4, 4)

        btn2 = QHBoxLayout()
        self.start2 = QPushButton("Start")
        self.stop2 = QPushButton("Stop")
        self.stop2.setEnabled(False)
        btn2.addWidget(self.start2)
        btn2.addWidget(self.stop2)
        g2.addLayout(btn2, 11, 0, 1, 4)

        self.log_chk2 = QCheckBox("Log to file")
        g2.addWidget(self.log_chk2, 12, 0)
        self.log_path2 = QLineEdit()
        self.log_path2.setEnabled(False)
        g2.addWidget(self.log_path2, 12, 1, 1, 2)
        self.log_b2 = QPushButton("Browse")
        self.log_b2.setEnabled(False)
        g2.addWidget(self.log_b2, 12, 3)

        self.tabs.addTab(t2, "Загрузка файла")

        # --- Tab 3: Дополнительно ---
        t3 = QWidget()
        l3 = QVBoxLayout(t3)
        l3.addWidget(QLabel("Дополнительный функционал здесь."))
        self.tabs.addTab(t3, "Дополнительно")

        # --- Connections Tab1 ---
        self.start1.clicked.connect(lambda: self._start(tab=1))
        self.stop1.clicked.connect(lambda: self._stop(tab=1))
        self.log_b1.clicked.connect(self._browse_log1)
        self.filter1.textChanged.connect(self.console1.set_filter)
        self.log_chk1.toggled.connect(lambda v: (self.log_path1.setEnabled(v), self.log_b1.setEnabled(v)))

        # --- Connections Tab2 ---
        self.start2.clicked.connect(lambda: self._start(tab=2))
        self.stop2.clicked.connect(lambda: self._stop(tab=2))
        self.browse2.clicked.connect(self._browse2)
        self.log_b2.clicked.connect(self._browse_log2)
        self.filter2.textChanged.connect(self.console2.set_filter)
        self.log_chk2.toggled.connect(lambda v: (self.log_path2.setEnabled(v), self.log_b2.setEnabled(v)))

    def _browse2(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select file", "", "XML or ZIP (*.xml *.zip)")
        if f:
            self.file2.setText(f)

    def _browse_log1(self):
        f, _ = QFileDialog.getSaveFileName(self, "Select log file", "", "TXT (*.txt);;All Files (*)")
        if f:
            self.log_path1.setText(f)

    def _browse_log2(self):
        f, _ = QFileDialog.getSaveFileName(self, "Select log file", "", "TXT (*.txt);;All Files (*)")
        if f:
            self.log_path2.setText(f)

    def _start(self, tab: int):
        if tab == 1:
            url, login, pwd = self.url1.text().strip(), self.login1.text().strip(), self.password1.text().strip()
            exch, fp = self.type1.currentText().strip(), self.filename1.text().strip()
            # запретим непредвиденный sale
            if exch.lower() == "sale":
                QMessageBox.warning(self, "Ошибка", "‘sale’ пока недоступен в Стандартном обмене")
                return

            send_file = False
            console, progress = self.console1, self.progress1
            log_chk, log_path, log_btn = self.log_chk1, self.log_path1, self.log_b1
            ui_disable = (
                self.url1, self.login1, self.password1,
                self.type1, self.filename1,
                self.start1, log_chk, log_path, log_btn
            )
            stop_btn = self.stop1
        else:
            url, login, pwd = self.url2.text().strip(), self.login2.text().strip(), self.password2.text().strip()
            exch, fp = self.type2.currentText().strip(), self.file2.text().strip()
            send_file = True
            console, progress = self.console2, self.progress2
            log_chk, log_path, log_btn = self.log_chk2, self.log_path2, self.log_b2
            ui_disable = (
                self.url2, self.login2, self.password2,
                self.type2, self.file2, self.browse2,
                self.start2, log_chk, log_path, log_btn
            )
            stop_btn = self.stop2

        if not all([url, login, pwd, exch, fp]) or (send_file and not os.path.isfile(fp)):
            QMessageBox.warning(self, "Error", "Fill all fields and (if uploading) select existing file/name.")
            return

        # open log file
        if log_chk.isChecked():
            lp = log_path.text().strip() or "exchange.log"
            try:
                self.log_file = open(lp, "a", encoding="utf-8")
                self.log_file.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
            except:
                self.log_file = None
        else:
            self.log_file = None

        # disable UI
        for w in ui_disable:
            w.setEnabled(False)
        stop_btn.setEnabled(True)

        progress.setValue(0)
        console.clear()

        # start worker
        self.worker = ExchangeWorker(url, login, pwd, exch, fp, send_file=send_file)
        # текстовый лог
        self.worker.progress.connect(lambda m: self._log(m, console))
        # процент заполнения прогрессбара
        self.worker.progressPercent.connect(progress.setValue)
        # переключение диапазона (для лоадера на import)
        self.worker.progressRange.connect(progress.setRange)
        # по завершении
        self.worker.finished.connect(lambda ok: self._finish(ok, tab))
        # инициализируем прогрессбар в дефолтный диапазон
        progress.setRange(0, 100)
        progress.setValue(0)
        self.worker.start()

    def _stop(self, tab: int):
        if self.worker:
            self.worker.requestInterruption()

    def _log(self, msg: str, console):
        console.log(msg)
        if self.log_file:
            try:
                self.log_file.write(msg + "\n")
                self.log_file.flush()
            except:
                pass

    def _finish(self, ok: bool, tab: int):
        if tab == 1:
            ui_enable = (
                self.url1, self.login1, self.password1,
                self.type1, self.filename1,
                self.start1, self.log_chk1,
                self.log_path1, self.log_b1
            )
            stop_btn = self.stop1
        else:
            ui_enable = (
                self.url2, self.login2, self.password2,
                self.type2, self.file2, self.browse2,
                self.start2, self.log_chk2,
                self.log_path2, self.log_b2
            )
            stop_btn = self.stop2

        for w in ui_enable:
            w.setEnabled(True)
        stop_btn.setEnabled(False)

        if self.log_file:
            try:
                self.log_file.close()
            except:
                pass
            self.log_file = None

        if ok:
            QMessageBox.information(self, "Success", "Exchange completed successfully.")
        else:
            # сброс прогрессбара при ошибке
            if tab == 1:
                self.progress1.setRange(0, 100)
                self.progress1.setValue(0)
            else:
                self.progress2.setRange(0, 100)
                self.progress2.setValue(0)
            QMessageBox.critical(self, "Error", "Exchange finished с ошибками.")

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            r = QMessageBox.question(self, "Abort?", "Exchange is running. Exit?", QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                e.ignore()
                return
            self.worker.requestInterruption()
            self.worker.wait(2000)
        if self.log_file:
            try:
                self.log_file.close()
            except:
                pass
        e.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
