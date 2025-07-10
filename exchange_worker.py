# exchange_worker.py

from PyQt5 import QtCore
import requests
import zipfile
import os
import time
import re

class ExchangeWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(str)
    progressRange = QtCore.pyqtSignal(int, int)
    progressPercent = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(bool)

    def __init__(self, url, login, password, exchange_type, file_path=None, send_file=True):
        super().__init__()
        self.url = url.rstrip('/')
        self.login = login
        self.password = password
        self.exchange_type = exchange_type
        self.file_path = file_path
        self.send_file = send_file
        self.exchange_version = '3.1'

    def run(self):
        session = requests.Session()
        session.auth = (self.login, self.password)
        success = False
        try:
            # 1. checkauth
            self.progress.emit("📤 Шаг 1: Авторизация.")
            params = {'type': self.exchange_type, 'mode': 'checkauth'}
            resp = session.get(self.url, params=params)
            self.progress.emit(f"📤 Запрос: GET {resp.url}")
            self.progress.emit("📥 Ответ сервера:\n" + resp.text.strip())
            if resp.status_code != 200:
                self.progress.emit(f"❌ Ошибка: код {resp.status_code} при авторизации")
                return
            lines = resp.text.strip().splitlines()
            if not lines or not lines[0].lower().startswith("success"):
                self.progress.emit(f"❌ Авторизация не удалась: {resp.text.strip() or '<empty>'}")
                return
            sessid = None
            for ln in lines:
                if ln.startswith("sessid="):
                    sessid = ln.split("=", 1)[1]
                    break
            if not sessid:
                self.progress.emit("❌ Ошибка: sessid не найден")
                return

            # 2–3. для стандартного обмена (send_file=False) пропускаем init и file
            fname = os.path.basename(self.file_path) if self.file_path else ''
            if not self.send_file:
                self.progress.emit("📤 Шаги 2 и 3: пропуск init и file для стандартного обмена")
                xmls = [fname]
            else:
                # 2. init
                self.progress.emit("📤 Шаг 2: Инициализация.")
                params = {
                    'type': self.exchange_type,
                    'mode': 'init',
                    'sessid': sessid,
                    'version': self.exchange_version
                }
                resp = session.get(self.url, params=params)
                self.progress.emit(f"📤 Запрос: GET {resp.url}")
                self.progress.emit("📥 Ответ сервера:\n" + resp.text.strip())
                if resp.status_code != 200:
                    self.progress.emit(f"❌ Ошибка init: код {resp.status_code}")
                    return
                init_txt = resp.text.strip().lower()
                if init_txt.startswith("failure"):
                    self.progress.emit(f"❌ Init failed: {init_txt}")
                    return
                m = re.search(r'file_limit=(\d+)', init_txt)
                limit = int(m.group(1)) if m else 0

                # 3. file — разбиваем на чанки и отсылаем, эмитим процент
                total = os.path.getsize(self.file_path)
                chunk = limit or total
                bytes_sent = 0
                with open(self.file_path, 'rb') as f:
                    while True:
                        if self.isInterruptionRequested():
                            self.progress.emit("🛑 Операция прервана пользователем.")
                            return

                        data = f.read(chunk)
                        if not data:
                            break
                        bytes_sent += len(data)
                        percent = int(bytes_sent / total * 100)
                        # обновляем прогресс-бар
                        self.progressPercent.emit(percent)
                        self.progress.emit(f"📤 Отправлено {bytes_sent}/{total} байт ({percent}%)")
                        r = session.post(
                            self.url,
                            params={
                                'type': self.exchange_type,
                                'mode': 'file',
                                'filename': fname,
                                'sessid': sessid,
                                'version': self.exchange_version
                            },
                            data=data
                        )
                        self.progress.emit("📥 Ответ сервера:\n" + r.text.strip())
                        if r.status_code != 200 or not r.text.lower().startswith("success"):
                            self.progress.emit(f"❌ Ошибка file: {r.text.strip()}")
                            return
                # доводим до 100%
                self.progressPercent.emit(100)

                # собираем список XML внутри ZIP или одиночного файла
                if fname.lower().endswith('.zip'):
                    with zipfile.ZipFile(self.file_path, 'r') as z:
                        xmls = [info.filename for info in z.infolist()
                                if info.filename.lower().endswith('.xml')]
                else:
                    xmls = [fname]

            # упорядочиваем xml: import, catalog, goods…
            xmls.sort(key=str.lower)
            ordered = []
            for k in ('import', 'catalog', 'goods'):
                for x in xmls:
                    if x.lower().startswith(k) and x not in ordered:
                        ordered.append(x)
            for x in xmls:
                if x not in ordered:
                    ordered.append(x)
            xmls = ordered

            # 4. import — переключаем progressBar в лоадер
            self.progress.emit("📤 Шаг 4: Импорт данных.")
            self.progressRange.emit(0, 0)  # лоадер (неопределённый)
            for xf in xmls:
                self.progress.emit(
                    f"📤 Запрос: GET {self.url}"
                    f"?type={self.exchange_type}&mode=import&filename={xf}&sessid={sessid}&version={self.exchange_version}"
                )
                while True:
                    if self.isInterruptionRequested():
                        self.progress.emit("🛑 Операция прервана пользователем.")
                        return

                    r = session.get(
                        self.url,
                        params={
                            'type': self.exchange_type,
                            'mode': 'import',
                            'filename': xf,
                            'sessid': sessid,
                            'version': self.exchange_version
                        }
                    )
                    self.progress.emit("📥 Ответ сервера:\n" + r.text.strip())
                    if r.status_code != 200:
                        self.progress.emit(f"❌ Ошибка import: код {r.status_code}")
                        return
                    txt = r.text.strip().lower()
                    if txt.startswith('progress'):
                        time.sleep(0.5)
                        continue
                    if txt.startswith('success'):
                        break
                    self.progress.emit("❌ Ошибка import, прерываем.")
                    return

            # после импорта возвращаем нормальный диапазон и ставим 100%
            self.progressRange.emit(0, 100)
            self.progressPercent.emit(100)

            self.progress.emit("✅ Обмен успешно завершен.")
            success = True

        except Exception as e:
            self.progress.emit(f"❌ Неожиданная ошибка: {e}")
        finally:
            session.close()
            self.finished.emit(success)
