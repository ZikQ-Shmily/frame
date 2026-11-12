"""Migrate the 9527 CMS plugin and registry while that CMS is stopped.

Run with python -S in a helper container with the same /config and
/cms/cms-api/usercustomize.py mounts. The script never prints credentials.
"""
import ast
import datetime
import json
import shutil
import sqlite3
from pathlib import Path


def migrate(config, target, executor, bridge):
    source = target.read_text()
    old_begin, old_end = '# BEGIN SHIYING EXECUTOR V1\n', '# END SHIYING EXECUTOR V1\n'
    new_begin, new_end = '# BEGIN FRAME EXECUTOR V1\n', '# END FRAME EXECUTOR V1\n'
    if old_begin not in source or source.count(old_begin) != 1 or source.count(old_end) != 1:
        raise RuntimeError('Expected exactly one legacy plugin block; no changes made')
    if new_begin in source:
        raise RuntimeError('FRAME plugin already present; no changes made')
    old_source = source
    before, rest = source.split(old_begin, 1)
    _, after = rest.split(old_end, 1)
    source = before + after
    for path, handler in (('shiying-executor', '_shiying_executor'), ('shiying', '_shiying_bridge')):
        injection = (f'        if path.startswith("/api/{path}/"):\n'
                     f'            await {handler}(scope, receive, send)\n'
                     '            return\n')
        if source.count(injection) != 1:
            raise RuntimeError('Legacy route injection does not match expected plugin; no changes made')
        source = source.replace(injection, '', 1)
    marker = 'def _make_panso_middleware(original_app):'
    assert source.count(marker) == 1
    source = source.replace(marker, new_begin + bridge.read_text() + '\n' + executor.read_text() + '\n' + new_end + '\n' + marker, 1)
    routes = ''.join(f'        if path.startswith("/api/{path}/"):\n'
                     f'            await {handler}(scope, receive, send)\n'
                     '            return\n' for path, handler in
                     (('frame', '_frame_bridge'), ('frame-executor', '_frame_executor')))
    marker = '        path = scope["path"]\n'
    assert source.count(marker) == 1
    source = source.replace(marker, marker + routes, 1)
    ast.parse(source)

    backup = config / ('frame-migration-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(mode=0o700)
    (backup / 'usercustomize.py').write_text(old_source)
    (backup / 'usercustomize.py').chmod(0o600)
    files = ('executor.token', 'executor.json', 'registry-established')
    for suffix in files:
        old_file = config / ('shiying-' + suffix)
        if old_file.exists():
            shutil.copy2(old_file, backup / old_file.name)
    if not (config / 'shiying-executor.token').is_file():
        raise RuntimeError('Existing CMS token missing; no changes made')
    with sqlite3.connect(config / 'cms-online.db') as db:
        with sqlite3.connect(backup / 'cms-online.db') as dest:
            db.backup(dest)
        (backup / 'cms-online.db').chmod(0o600)
        db.execute('BEGIN IMMEDIATE')
        old_key, new_key = 'cms_shiying_subscriptions_v1', 'cms_frame_subscriptions_v1'
        row = db.execute('SELECT config_json FROM cms_config WHERE key=?', (old_key,)).fetchone()
        if db.execute('SELECT 1 FROM cms_config WHERE key=?', (new_key,)).fetchone():
            raise RuntimeError('FRAME registry already exists; no changes made')
        if row:
            registry = json.loads(row[0])
            if not isinstance(registry.get('entries'), dict) or not isinstance(registry.get('owners'), dict):
                raise RuntimeError('Invalid registry; no changes made')
            db.execute('UPDATE cms_config SET key=? WHERE key=?', (new_key, old_key))
        elif (config / 'shiying-registry-established').exists():
            raise RuntimeError('Established registry missing; no changes made')
        created = []
        try:
            for suffix in files:
                old_file, new_file = config / ('shiying-' + suffix), config / ('frame-' + suffix)
                if old_file.exists():
                    if new_file.exists():
                        raise RuntimeError('FRAME configuration already exists; no changes made')
                    shutil.copy2(old_file, new_file)
                    new_file.chmod(0o600)
                    created.append(new_file)
            target.write_text(source)
            db.commit()
        except BaseException:
            db.rollback()
            target.write_text(old_source)
            for path in created:
                path.unlink(missing_ok=True)
            raise
    print('CMS migration complete; backup:', backup)


if __name__ == '__main__':
    migrate(Path('/config'), Path('/cms/cms-api/usercustomize.py'),
            Path('/config/frame-executor.py'), Path('/config/frame-bridge.py'))
