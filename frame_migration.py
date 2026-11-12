"""One-time transactional conversion of stored credentials to FRAME encryption."""
import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def migrate_credentials(db, secret):
    marker = 'frame_credentials_v1'
    # Acquire a write lock before checking the marker, so concurrent workers
    # cannot attempt to convert the same ciphertext twice.
    db.execute('BEGIN IMMEDIATE')
    if db.execute('SELECT 1 FROM settings WHERE key=?', (marker,)).fetchone():
        return
    old = AESGCM(hashlib.sha256(('shiying-integrations-v1:' + secret).encode()).digest())
    new = AESGCM(hashlib.sha256(('frame-integrations-v1:' + secret).encode()).digest())

    def convert(value):
        if not value:
            return value
        raw = base64.urlsafe_b64decode(value)
        plaintext = old.decrypt(raw[:12], raw[12:], b'shiying-config-v1')
        nonce = os.urandom(12)
        return base64.urlsafe_b64encode(nonce + new.encrypt(nonce, plaintext, b'frame-config-v1')).decode()

    for key, fields in (('integration_config', ('tmdb_credential', 'emby_api_key', 'cms_token', 're0_gateway_token')),
                        ('notification_config', ('smtp_password',))):
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        if row:
            value = json.loads(row[0])
            for field in fields:
                if value.get(field):
                    value[field] = convert(value[field])
            db.execute('UPDATE settings SET value=? WHERE key=?', (json.dumps(value, ensure_ascii=False), key))
    for session_id, raw_identity in db.execute('SELECT id, identity FROM sessions WHERE identity IS NOT NULL').fetchall():
        identity = json.loads(raw_identity)
        if identity.get('token'):
            identity['token'] = convert(identity['token'])
            db.execute('UPDATE sessions SET identity=? WHERE id=?', (json.dumps(identity, ensure_ascii=False), session_id))
    db.execute('INSERT INTO settings (key, value) VALUES (?, ?)', (marker, '1'))
