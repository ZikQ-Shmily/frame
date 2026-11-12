import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('cms_frame_migration', Path(__file__).parents[1] / 'deploy/migrate_cms_frame.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CMSMigrationTests(unittest.TestCase):
    def test_registry_token_and_routes_are_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'usercustomize.py'
            target.write_text('''# BEGIN SHIYING EXECUTOR V1\nold = 1\n# END SHIYING EXECUTOR V1\ndef _make_panso_middleware(original_app):\n    async def inner(scope, receive, send):\n        path = scope["path"]\n        if path.startswith("/api/shiying/"):\n            await _shiying_bridge(scope, receive, send)\n            return\n        if path.startswith("/api/shiying-executor/"):\n            await _shiying_executor(scope, receive, send)\n            return\n''')
            (root / 'shiying-executor.token').write_text('token-value')
            (root / 'shiying-executor.json').write_text('{}')
            (root / 'shiying-registry-established').touch()
            executor, bridge = root / 'frame-executor.py', root / 'frame-bridge.py'
            executor.write_text('def _frame_executor(): pass')
            bridge.write_text('def _frame_bridge(): pass')
            with sqlite3.connect(root / 'cms-online.db') as db:
                db.execute('CREATE TABLE cms_config (key TEXT PRIMARY KEY, config_json TEXT)')
                db.execute('INSERT INTO cms_config VALUES (?,?)', ('cms_shiying_subscriptions_v1', json.dumps({'entries': {'a': 1}, 'owners': {'b': 2}})))
            module.migrate(root, target, executor, bridge)
            with sqlite3.connect(root / 'cms-online.db') as db:
                self.assertEqual(db.execute('SELECT key FROM cms_config').fetchone()[0], 'cms_frame_subscriptions_v1')
            self.assertEqual((root / 'frame-executor.token').read_text(), 'token-value')
            self.assertIn('/api/frame/', target.read_text())
            self.assertNotIn('/api/shiying/', target.read_text())
            self.assertEqual(len(list(root.glob('frame-migration-*/cms-online.db'))), 1)
