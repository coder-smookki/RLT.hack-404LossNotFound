"""Container-only adapter. Public exposure is restricted by Compose host binding."""
import json
import os
from pathlib import Path
import sys

state=Path(os.environ['SUPPLY_DATA_DIR']);state.mkdir(mode=0o700,exist_ok=True)
os.chmod(state,0o700)
config={'NAME':'rlt_product','USER':'rlt_app','PASSWORD':Path('/run/secrets/app_db_password').read_text().strip(),'HOST':'db','PORT':'5432'}
path=state/'database.json'
temporary=state/('database.'+str(os.getpid())+'.tmp')
fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as stream:json.dump(config,stream)
os.replace(temporary,path)
sys.path.insert(0,'/app/product/backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
from config import settings as container_settings
# Cookies are scoped by host, not port: keep the existing native app signed in.
container_settings.SESSION_COOKIE_NAME = 'supply_docker_session'
container_settings.CSRF_COOKIE_NAME = 'supply_docker_csrf'
import django
django.setup()
from django.core.management import call_command
if sys.argv[1]=='web':
    call_command('migrate',verbosity=0)
    from config.wsgi import application
    from waitress import serve
    serve(application,host='0.0.0.0',port=8902,threads=4,max_request_body_size=24*1024*1024,connection_limit=50,channel_timeout=30,clear_untrusted_proxy_headers=True)
elif sys.argv[1]=='worker':
    call_command('inference_worker')
elif sys.argv[1]=='source-worker':
    call_command('source_worker')
else:raise SystemExit('Expected web, worker or source-worker')
