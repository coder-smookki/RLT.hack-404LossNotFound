"""Готовит компактный исходный релиз и проверяет отдельные доверенные ресурсы.

Аргументы задаются через CLI. Возвращает код завершения 0 при успехе.
Побочные эффекты: команды audit/stage/zip пишут только указанный staging/output;
install-assets копирует явно перечисленные файлы в отсутствующие локальные пути.
Исходные данные, Git и работающие сервисы скрипт не изменяет.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGE = ROOT / 'local/release-package-2026-10-02'
FROZEN_CODE = (
    'local/retrieval-router/engine.py',
    'local/pu-ranker/score_frozen.py', 'local/pu-ranker/runner.py', 'local/pu-ranker/nnpu.py',
    'local/neighbor-ml-v3/features.py', 'local/neighbor-ml-v3/scorer.py',
    'local/neighbor-ml-v3/locked-code/scorer.py', 'local/okpd-structure-v2/variants.py',
)
MODEL_WEIGHTS = (
    'local/neighbor-ml-v3/cuda-results/neighbor_nnpu_h16_pi0.02.npz',
    'local/neighbor-ml-v3/cuda-results/normalization.npz',
)
FIXED_SOURCES = (
    '.dockerignore', 'compose.yaml', 'README.md',
    'scripts/package_release.py', 'scripts/recommend_frozen_p1.py',
    'scripts/recommend_enriched.py', 'scripts/serve_local.py',
    'product/docker/Dockerfile', 'product/docker/entrypoint.py',
    'product/docker/db-entrypoint.sh', 'product/docker/init-db.sh',
    'product/docker/prepare.py', 'product/docker/runtime.requirements.lock',
    'product/backend/requirements.txt', 'product/backend/requirements.lock',
    'product/backend/fonts/LICENSE_LIBERATION',
    'product/backend/fonts/LiberationSans-Regular.ttf',
    'product/backend/fonts/LiberationSans-Bold.ttf',
    'product/frontend/package.json', 'product/frontend/package-lock.json',
    'product/frontend/tsconfig.json', 'product/frontend/vite.config.ts',
    'product/frontend/index.html', 'product/frontend/public/favicon.svg',
    'product/frontend/tests/domain-v2.test.mjs',
    'product/frontend/tests/purchaser-presentation.test.mjs',
    'src/rlt_lab/__init__.py', 'src/rlt_lab/data.py', 'src/rlt_lab/input.py',
    'src/rlt_lab/evidence_matching.py', 'src/rlt_lab/external_evidence.py',
    'src/rlt_lab/registry_evidence.py',
    'tests/test_input.py', 'tests/test_evidence_matching.py',
    'tests/test_external_evidence.py', 'tests/test_registry_evidence.py',
    'tests/test_data.py',
)
PRIVATE_FIXED = (
    'local/history.sqlite',
    'local/retrieval-router/index_artifact_manifest.json',
    'local/retrieval-router/protocol.lock.json',
    'local/retrieval-router/snapshot.sqlite',
    'local/retrieval-router/snapshot_manifest.json',
    'local/retrieval-router/char_index.npz',
    'local/retrieval-router/char_vocabulary.json',
    'local/retrieval-router/char_idf.npy',
    'local/neighbor-ml-v3/protocol.lock.json',
    'local/neighbor-ml-v3/inference-repair.lock.json',
    'local/neighbor-ml-v3/bundle/input_manifest.json',
    'local/neighbor-ml-v3/cuda-results/selection.lock.json',
    'local/neighbor-ml-v3/cuda-results/input_manifest.json',
    'local/neighbor-ml-v3/cuda-results/protocol.lock.json',
    'local/next-cycle-v3/reserve.results.json',
    'local/next-cycle-v3/reserve.evaluation.lock.json',
    'local/okpd-structure-v2/history_aux.sqlite',
    'local/okpd-structure-v2/code_support.json',
    'local/release-s9-audit/release/runtime_release/artifacts/runtime_index.sqlite',
    'local/enrichment-36m/companies.json',
    'local/enrichment-36m-dated-v2/reviewed_activity_patch.json',
    'local/registry-enrichment-expansion/companies.json',
    'local/colleague-enrichment-2026-10-02/registry_companies.json',
    'local/enrichment-all-suppliers-2026-10-02/supplier_profiles.json',
    'local/enrichment-all-suppliers-2026-10-02/history_summaries.sqlite',
)
BATCH_PATHS = (
    'local/enrichment-36m/companies.json',
    'local/enrichment-36m-dated-v2/reviewed_activity_patch.json',
    'local/registry-enrichment-expansion/companies.json',
    'local/colleague-enrichment-2026-10-02/registry_companies.json',
)
EXCLUDED_PARTS = frozenset(('.git', '.venv', 'venv', 'node_modules', '__pycache__',
    '.ipynb_checkpoints', 'archive', 'verification', 'dist'))
PRIVATE_SUFFIXES = ('.sqlite', '.sqlite3', '.db', '.log', '.ipynb', '.m4a', '.docx', '.pdf', '.pyc')
SECRET_PATTERNS = (
    ('private-key', re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----')),
    ('github-token', re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{50,}\b')),
    ('aws-access-key', re.compile(r'\bAKIA[A-Z0-9]{16}\b')),
    ('slack-token', re.compile(r'\bxox[baprs]-[0-9A-Za-z-]{20,}\b')),
    ('openai-token', re.compile(r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}\b')),
)
TRACE_PATTERN = re.compile(r'\b(?:Codex|Claude|ChatGPT|assistant|subagent)\b|/Users/|/Volumes/|/home/(?!supply\b)|smokkk', re.I)
MIT_META = 'MIT License\n\nCopyright (c) Meta Platforms, Inc. and affiliates.\n\nPermission is hereby granted, free of charge, to any person obtaining a copy\nof this software and associated documentation files (the "Software"), to deal\nin the Software without restriction, including without limitation the rights\nto use, copy, modify, merge, publish, distribute, sublicense, and/or sell\ncopies of the Software, and to permit persons to whom the Software is\nfurnished to do so, subject to the following conditions:\n\nThe above copyright notice and this permission notice shall be included in all\ncopies or substantial portions of the Software.\n\nTHE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\nIMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\nFITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\nAUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\nLIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\nOUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\nSOFTWARE.\n'


def sha256(path: Path) -> str:
    """Считает SHA-256 файла path; возвращает hex-строку, ничего не изменяет."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    """Проверяет относительный путь внутри root; возвращает Path без побочных эффектов."""
    value = Path(relative)
    if value.is_absolute() or '..' in value.parts or '\\' in relative:
        raise ValueError('Unsafe relative path: ' + relative)
    path = root / value
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Symlink or escaped path: ' + relative)
    return path


def source_paths(root: Path) -> list[str]:
    """Возвращает allowlist исходников root, исключая неиспользуемые старые экспорты.

    Аргументы: root - корень проекта. Возврат: относительные пути.
    Побочные эффекты отсутствуют; PDF создаётся сервером, старый клиентский код не нужен.
    """
    result = set(FIXED_SOURCES + FROZEN_CODE + MODEL_WEIGHTS)
    for path in (root / 'product/backend').rglob('*.py'):
        if '__pycache__' not in path.parts:
            result.add(path.relative_to(root).as_posix())
    for path in (root / 'product/frontend/src').rglob('*'):
        if path.is_file() and path.suffix in ('.ts', '.tsx', '.css'):
            result.add(path.relative_to(root).as_posix())
    result.discard('product/frontend/src/features/export/pdf-export.ts')
    result.discard('product/frontend/src/features/export/csv-export.ts')
    if (root / '.gitignore').is_file():
        result.add('.gitignore')
    return sorted(result)


def walk_references(value: object, keys: set[str]) -> list[str]:
    """Извлекает строковые ссылки keys из JSON value; возвращает список, не пишет файлы."""
    refs = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, str):
                refs.append(item)
            else:
                refs.extend(walk_references(item, keys))
    elif isinstance(value, list):
        for item in value:
            refs.extend(walk_references(item, keys))
    return refs


def asset_paths(root: Path) -> dict[str, str]:
    """Разворачивает ссылки ресурсов root; возвращает путь→назначение без сетевых действий."""
    result = {name: 'runtime' for name in PRIVATE_FIXED}
    for name in BATCH_PATHS:
        path = safe_path(root, name)
        data = json.loads(path.read_text(encoding='utf-8'))
        for ref in walk_references(data, {'payload_path', 'source_payload_path'}):
            target = safe_path(path.parent, ref)
            result[target.relative_to(root).as_posix()] = 'external_evidence'
    profile = json.loads((root / 'local/enrichment-all-suppliers-2026-10-02/supplier_profiles.json').read_text(encoding='utf-8'))
    for ref in walk_references(profile, {'localPayload', 'payloadPath'}):
        safe_path(root, ref)
        result.setdefault(ref, 'profile_evidence')
    return dict(sorted(result.items()))


def file_record(root: Path, name: str) -> dict:
    """Читает размер и хеш name внутри root; возвращает запись, не меняет файл."""
    path = safe_path(root, name)
    if not path.is_file():
        raise FileNotFoundError(name)
    before = path.stat()
    result = {'path': name, 'bytes': before.st_size, 'sha256': sha256(path)}
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise RuntimeError('File changed during audit: ' + name)
    return result


def scan_public(root: Path, paths: list[str]) -> list[dict]:
    """Проверяет публикуемые пути paths внутри root и возвращает безопасный список находок.

    Аргументы: root - корень, paths - allowlist. Возврат: тип, путь и строка находки.
    Побочных эффектов нет. Собственные шаблоны сканера не считаются атрибуцией.
    """
    findings = []
    for name in paths:
        path = safe_path(root, name)
        if any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts):
            findings.append({'path': name, 'kind': 'excluded-directory'})
        if path.suffix.lower() == '.md' and path.name != 'README.md':
            findings.append({'path': name, 'kind': 'non-readme-markdown'})
        if path.suffix.lower() in PRIVATE_SUFFIXES or path.name.startswith('.env'):
            findings.append({'path': name, 'kind': 'private-or-generated-file'})
        if path.suffix in ('.npz', '.ttf'):
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            findings.append({'path': name, 'kind': 'unexpected-binary'})
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append({'path': name, 'line': number, 'kind': label})
            if name != 'scripts/package_release.py' and TRACE_PATTERN.search(line):
                findings.append({'path': name, 'line': number, 'kind': 'assistant-or-machine-trace'})
    return findings


def write_json(path: Path, value: object) -> None:
    """Атомарно сохраняет value в path; возвращает None, создаёт родительскую папку."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def audit(root: Path, output: Path) -> dict:
    """Аудирует root и пишет JSON в output; возвращает сводку без копирования данных."""
    sources = source_paths(root)
    source_records = [file_record(root, name) for name in sources]
    assets = [{**file_record(root, name), 'purpose': purpose} for name, purpose in asset_paths(root).items()]
    source_bytes = sum(row['bytes'] for row in source_records)
    asset_bytes = sum(row['bytes'] for row in assets)
    findings = scan_public(root, sources)
    summary = {'sourceFiles': len(sources), 'sourceBytes': source_bytes,
               'privateAssetFiles': len(assets), 'privateAssetBytes': asset_bytes,
               'findings': findings, 'modelUnchanged': True,
               'sourceOnlyCanRecommend': False,
               'initialization': 'Exact private assets must be provided separately and pass SHA-256 checks.'}
    write_json(output / 'source-allowlist.json', {'files': source_records, 'generatedFiles': ['runtime-assets.json', 'THIRD_PARTY_NOTICES']})
    write_json(output / 'runtime-assets.json', {'schema': 'rlt.runtime-assets.v1', 'files': assets,
        'containsData': False, 'assetDistribution': 'separate trusted private provision',
        'warning': 'This manifest describes required private resources, but does not include their contents.'})
    write_json(output / 'audit.json', summary)
    return summary


def stage(root: Path, audit_dir: Path) -> dict:
    """Копирует согласованный allowlist из root в staging; возвращает размер, не меняет root."""
    allow = json.loads((audit_dir / 'source-allowlist.json').read_text(encoding='utf-8'))
    tree = audit_dir / 'source'
    if tree.exists():
        raise FileExistsError('Staging exists; select a new audit directory: ' + str(tree))
    findings = scan_public(root, [row['path'] for row in allow['files']])
    if findings:
        raise RuntimeError('Public audit findings must be resolved before staging: ' + json.dumps(findings, ensure_ascii=False))
    for row in allow['files']:
        if file_record(root, row['path']) != row:
            raise RuntimeError('Source changed after audit: ' + row['path'])
    tree.mkdir(parents=True)
    for row in allow['files']:
        target = safe_path(tree, row['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(safe_path(root, row['path']), target)
        target.chmod(0o644)
    shutil.copyfile(audit_dir / 'runtime-assets.json', tree / 'runtime-assets.json')
    notices = 'Third-party notices\n\nReact, React DOM and Scheduler\n' + MIT_META
    notices += '\nLiberation Sans\nThe complete SIL OFL license is preserved at product/backend/fonts/LICENSE_LIBERATION.\n'
    notices += '\nPython dependencies are installed from pinned requirement files; their upstream notices remain inside the installed distributions. No private data or third-party website snapshots are included in this source archive.\n'
    (tree / 'THIRD_PARTY_NOTICES').write_text(notices, encoding='utf-8')
    return {'tree': str(tree), 'files': len(allow['files']) + 2}


def create_zip(audit_dir: Path, destination: Path) -> dict:
    """Упаковывает проверенное staging-дерево; возвращает размер/SHA, пишет только новый ZIP."""
    tree = audit_dir / 'source'
    paths = sorted(path.relative_to(tree).as_posix() for path in tree.rglob('*') if path.is_file())
    allowed = json.loads((audit_dir / 'source-allowlist.json').read_text(encoding='utf-8'))
    expected = {row['path'] for row in allowed['files']} | set(allowed['generatedFiles'])
    if set(paths) != expected:
        raise ValueError('Staging contents differ from exact allowlist')
    for row in allowed['files']:
        if file_record(tree, row['path']) != row:
            raise ValueError('Staging content changed: ' + row['path'])
    findings = scan_public(tree, paths)
    if findings:
        raise ValueError('Staging audit failed: ' + json.dumps(findings, ensure_ascii=False))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in paths:
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 2, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, safe_path(tree, name).read_bytes())
    with zipfile.ZipFile(destination) as archive:
        if set(archive.namelist()) != expected or archive.testzip() is not None:
            raise ValueError('ZIP validation failed')
        for name in paths:
            if hashlib.sha256(archive.read(name)).hexdigest() != sha256(tree / name):
                raise ValueError('ZIP member mismatch: ' + name)
    result = {'path': str(destination), 'bytes': destination.stat().st_size, 'sha256': sha256(destination),
              'files': len(paths), 'excludedFound': [], 'secretPatternFindings': [],
              'note': 'Pattern scanning is not a proof of absence of every possible secret.'}
    write_json(audit_dir / 'zip-check.json', result)
    return result


def validate_assets(root: Path, manifest: Path) -> list[dict]:
    """Проверяет ресурсы root по manifest; возвращает расхождения, ничего не меняет."""
    records = json.loads(manifest.read_text(encoding='utf-8'))
    if records.get('schema') != 'rlt.runtime-assets.v1':
        raise ValueError('Unsupported asset manifest')
    errors = []
    for row in records['files']:
        try:
            if file_record(root, row['path']) != {key: row[key] for key in ('path', 'bytes', 'sha256')}:
                errors.append({'path': row['path'], 'reason': 'size_or_sha256'})
        except FileNotFoundError:
            errors.append({'path': row['path'], 'reason': 'missing'})
    return errors


def install_assets(root: Path, source: Path, manifest: Path) -> dict:
    """Устанавливает проверенные ресурсы source в root согласно manifest.

    Аргументы: source и root - корни папок, manifest - доверенный список SHA-256.
    Возврат: число установленных и уже совпадающих файлов.
    Побочные эффекты: создаёт каталоги и новые файлы; существующие файлы не заменяет.
    При расхождении SHA/размера или занятом отличающемся пути возбуждает исключение.
    Каждая установка атомарна: проверенный временный файл получает новое имя через
    исключительное создание hard link; прерванная копия не становится ресурсом.
    """
    errors = validate_assets(source, manifest)
    if errors:
        raise ValueError('Untrusted or incomplete asset directory: ' + json.dumps(errors, ensure_ascii=False))
    records = json.loads(manifest.read_text(encoding='utf-8'))['files']
    pending = []
    for row in records:
        target = safe_path(root, row['path'])
        if target.exists():
            if file_record(root, row['path']) != {key: row[key] for key in ('path', 'bytes', 'sha256')}:
                raise FileExistsError('Existing different asset is preserved: ' + row['path'])
        else:
            pending.append(row)
    for row in pending:
        target = safe_path(root, row['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.' + target.name + '.', delete=False) as output:
                temporary = Path(output.name)
                with safe_path(source, row['path']).open('rb') as input_stream:
                    shutil.copyfileobj(input_stream, output, length=1024 * 1024)
            if temporary.stat().st_size != row['bytes'] or sha256(temporary) != row['sha256']:
                raise ValueError('Copied asset did not pass verification: ' + row['path'])
            os.link(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return {'installed': len(pending), 'alreadyMatching': len(records) - len(pending)}


def main(argv: list[str] | None = None) -> int:
    """Разбирает argv и выполняет команду; возвращает exit code, эффекты описаны в командах."""
    parser = argparse.ArgumentParser(description='Компактный исходный пакет и проверяемые приватные ресурсы.')
    parser.add_argument('command', choices=('audit', 'stage', 'zip', 'check-assets', 'install-assets'))
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--audit-dir', type=Path, default=DEFAULT_STAGE)
    parser.add_argument('--zip-path', type=Path, default=ROOT / 'output/release/RLT-404-source-2026-10-02.zip')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--assets-from', type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    manifest = args.manifest or root / 'runtime-assets.json'
    if args.command == 'audit':
        result = audit(root, args.audit_dir.resolve())
    elif args.command == 'stage':
        result = stage(root, args.audit_dir.resolve())
    elif args.command == 'zip':
        result = create_zip(args.audit_dir.resolve(), args.zip_path.resolve())
    elif args.command == 'check-assets':
        errors = validate_assets(root, manifest)
        result = {'ok': not errors, 'errors': errors}
        print(json.dumps(result, ensure_ascii=False))
        return 1 if errors else 0
    else:
        if args.assets_from is None:
            parser.error('--assets-from is required')
        result = install_assets(root, args.assets_from.resolve(), manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
