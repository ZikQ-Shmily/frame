import base64
import hashlib
import json
import sqlite3
import unittest

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from frame_migration import migrate_credentials


class FrameMigrationTests(unittest.TestCase):
    def setUp(self):
        self.secret = 'x' * 64
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.db.execute('CREATE TABLE sessions (id TEXT PRIMARY KEY, identity TEXT)')

    def old_encrypt(self, text):
        cipher = AESGCM(hashlib.sha256(('shiying-integrations-v1:' + self.secret).encode()).digest())
        nonce = b'a' * 12
        return base64.urlsafe_b64encode(nonce + cipher.encrypt(nonce, text.encode(), b'shiying-config-v1')).decode()

    def decrypt_new(self, encoded):
        raw = base64.urlsafe_b64decode(encoded)
        cipher = AESGCM(hashlib.sha256(('frame-integrations-v1:' + self.secret).encode()).digest())
        return cipher.decrypt(raw[:12], raw[12:], b'frame-config-v1').decode()

    def test_preserves_all_credentials_and_sessions_once(self):
        keys = ('tmdb_credential', 'emby_api_key', 'cms_token', 're0_gateway_token')
        self.db.execute('INSERT INTO settings VALUES (?, ?)', ('integration_config', json.dumps({k: self.old_encrypt(k) for k in keys})))
        self.db.execute('INSERT INTO settings VALUES (?, ?)', ('notification_config', json.dumps({'smtp_password': self.old_encrypt('smtp')})))
        self.db.execute('INSERT INTO sessions VALUES (?, ?)', ('session', json.dumps({'token': self.old_encrypt('session-token')})))
        self.db.commit()
        migrate_credentials(self.db, self.secret)
        self.db.commit()
        values = dict(self.db.execute('SELECT key, value FROM settings'))
        for key in keys:
            self.assertEqual(self.decrypt_new(json.loads(values['integration_config'])[key]), key)
        self.assertEqual(self.decrypt_new(json.loads(values['notification_config'])['smtp_password']), 'smtp')
        self.assertEqual(self.decrypt_new(json.loads(self.db.execute('SELECT identity FROM sessions').fetchone()[0])['token']), 'session-token')
        migrate_credentials(self.db, self.secret)
        self.db.commit()
        self.assertEqual(values, dict(self.db.execute('SELECT key, value FROM settings')))

    def test_bad_credential_rolls_back_without_marking_success(self):
        original = json.dumps({'tmdb_credential': self.old_encrypt('valid'), 'cms_token': 'invalid'})
        self.db.execute('INSERT INTO settings VALUES (?, ?)', ('integration_config', original))
        self.db.commit()
        with self.assertRaises(Exception):
            try:
                migrate_credentials(self.db, self.secret)
            except Exception:
                self.db.rollback()
                raise
        self.assertEqual(self.db.execute('SELECT value FROM settings WHERE key=?', ('integration_config',)).fetchone()[0], original)
        self.assertIsNone(self.db.execute('SELECT value FROM settings WHERE key=?', ('frame_credentials_v1',)).fetchone())
