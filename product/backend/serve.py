#!/usr/bin/env python3
"""Loopback-only local server; intentionally never binds a public interface."""
import argparse
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
from config.wsgi import application
from django.core.management import call_command
from waitress import serve
parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=8902)
args = parser.parse_args()
call_command('migrate', verbosity=0)
serve(application, host='127.0.0.1', port=args.port, threads=4,
      max_request_body_size=24 * 1024 * 1024, connection_limit=50,
      channel_timeout=30, clear_untrusted_proxy_headers=True)
