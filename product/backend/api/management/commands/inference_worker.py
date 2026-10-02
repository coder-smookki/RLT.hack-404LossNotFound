"""Separate worker: never executes inference in an HTTP request thread."""
import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from api.jobs import run_one

class Command(BaseCommand):
    help = 'Run durable inference jobs against the pinned loopback runtime on port 8901.'
    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process at most one eligible job, then exit.')
    def handle(self, *args, **options):
        self.stdout.write('Inference worker ready; results stay in the owner database.')
        try:
            while True:
                worked = run_one()
                if options['once']:
                    return
                if not worked:
                    close_old_connections()
                    time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write('Worker stopped.')
