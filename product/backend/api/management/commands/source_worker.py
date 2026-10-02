"""Запускать отдельный процесс обновления проверенных источников компаний."""
import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from api.source_jobs import run_one

class Command(BaseCommand):
    """Обрабатывать очередь публичных профилей без запуска ранжирования.

    Команда использует тот же SUPPLY_DATA_DIR и БД, что приложение. Supervisor
    отвечает за перезапуск процесса после необработанной ошибки."""
    help='Refresh previously verified official company websites; never executes ranking.'
    def add_arguments(self,parser):
        """Добавить к Django parser необязательный флаг --once.

        По умолчанию флаг False и worker работает циклически. Метод меняет
        конфигурацию парсера и возвращает None."""
        parser.add_argument('--once',action='store_true')
    def handle(self,*args,**options):
        """Запускать run_one до остановки либо одной попытки с --once.

        args и options передаёт Django; используется options[once]. При отсутствии
        работы закрывает соединения и ждёт 2 секунды. KeyboardInterrupt завершает
        цикл с сообщением; прочие ошибки передаются supervisor. Возвращает None.
        Сеть и записи БД выполняются внутри run_one, не в HTTP-процессе."""
        self.stdout.write('Company source worker ready.')
        try:
            while True:
                worked=run_one()
                if options['once']:return
                if not worked:
                    close_old_connections();time.sleep(2)
        except KeyboardInterrupt:self.stdout.write('Source worker stopped.')
