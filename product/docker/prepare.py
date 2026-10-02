"""Prepare private local credentials; never print secret values."""
from pathlib import Path
import os,secrets,socket
ROOT=Path(__file__).resolve().parents[2]
required=['local/history.sqlite','local/retrieval-router/engine.py','local/pu-ranker/score_frozen.py','local/neighbor-ml-v3/cuda-results/selection.lock.json','local/next-cycle-v3/reserve.results.json','local/okpd-structure-v2/history_aux.sqlite','local/release-s9-audit/release/runtime_release/artifacts/runtime_index.sqlite','local/enrichment-36m/companies.json','local/enrichment-36m-dated-v2/reviewed_activity_patch.json','local/registry-enrichment-expansion/companies.json','local/colleague-enrichment-2026-10-02/registry_companies.json']
missing=[v for v in required if not (ROOT/v).is_file()]
if missing:raise SystemExit('Missing required runtime artifacts: '+', '.join(missing))
state=ROOT/'local/product-docker';private=state/'secrets';private.mkdir(parents=True,mode=0o700,exist_ok=True)
os.chmod(state,0o700);os.chmod(private,0o700)
for name in ['postgres_password','app_db_password']:
 path=private/name
 try:fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 except FileExistsError:continue
 with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(48)+'\n')
config=state/'compose.env'
if not config.exists():
 for port in (8903,8904,8905,8914,8920):
  with socket.socket() as s:
   if s.connect_ex(('127.0.0.1',port))!=0:break
 else:raise SystemExit('No free local Docker port in 8903/8904/8905/8914/8920')
 config.write_text(f'APP_UID={os.getuid()}\nAPP_GID={os.getgid()}\nSUPPLY_DOCKER_PORT={port}\n')
 os.chmod(config,0o600)
print('Private configuration and required artifact paths are ready; secrets were not printed.')
