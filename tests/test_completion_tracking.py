"""Completed collections pause only source work and resume after verified loss."""
import json
import unittest
from unittest.mock import Mock, patch

from test_integrations import IntegrationTests
from integrations import IntegrationError


class CompletionTrackingTests(unittest.TestCase):
    setUpClass = classmethod(IntegrationTests.setUpClass.__func__)
    tearDownClass = classmethod(IntegrationTests.tearDownClass.__func__)
    setUp = IntegrationTests.setUp
    metadata = IntegrationTests.metadata
    record = IntegrationTests.record
    configure = IntegrationTests.configure

    def saved(self, item):
        with self.mod.database() as db:
            return self.mod.get_item(db, item['id'])

    def sync(self, tmdb, emby, query, executor):
        self.mod.SYNC_LOCK.acquire()
        with patch.object(self.mod, 'tmdb_client', return_value=tmdb), \
             patch.object(self.mod, 'emby_client', return_value=emby), \
             patch.object(self.mod, 'cms_client', return_value=query), \
             patch.object(self.mod, 'executor_client', return_value=executor), \
             patch.object(self.mod, 'read_share_episodes') as scan:
            self.mod.run_sync()
        return scan

    def test_confirm_pause_failure_preserves_state_then_missing_resumes(self):
        self.configure()
        config = self.mod.integration_config()
        config.update(cms_url='http://cms.example', cms_token=self.mod.encrypt_secret('token'),
                      re0_via_cms=True)
        self.mod.persist_config(config)
        item = self.record(sources=[dict(id='s', share_url='https://115.com/s/abc', episodes='1-4')],
                           active_source_id='s')
        with self.mod.database() as db:
            value = self.mod.get_item(db, item['id'])
            value['re0'] = dict(slug='fixed', uploader='发布者', source_id='s', error='旧来源错误')
            db.execute('UPDATE items SET payload=? WHERE id=?', (json.dumps(value), item['id']))
        tmdb, emby, query, executor = Mock(), Mock(), Mock(), Mock()
        tmdb.tracking_metadata.return_value = self.metadata()
        emby.compare.return_value = dict(state='matched', episodes=[1, 2, 3, 4], item_ids=['series'], error='', unnumbered=0)
        executor.subscribe.side_effect = lambda payload: dict(state='submitted', active=payload['active'], subscription_id='1')

        scan = self.sync(tmdb, emby, query, executor)
        saved = self.saved(item)
        self.assertTrue(saved['collection_confirmed'])
        self.assertEqual(saved['cms_delivery']['state'], 'paused')
        self.assertFalse(executor.subscribe.call_args.args[0]['active'])
        query.resolve.assert_not_called()
        scan.assert_not_called()
        self.assertFalse(self.mod.decorate(saved)['needs_attention'])

        emby.compare.side_effect = IntegrationError('Emby 暂不可达')
        scan = self.sync(tmdb, emby, query, executor)
        self.assertTrue(self.saved(item)['collection_confirmed'])
        self.assertEqual(self.saved(item)['cms_delivery']['state'], 'paused')
        query.resolve.assert_not_called()
        scan.assert_not_called()
        self.assertIn('Emby', self.mod.decorate(self.saved(item))['attention_reasons'][0]['detail'])

        emby.compare.side_effect = None
        emby.compare.return_value = dict(state='matched', episodes=[1, 2, 3], item_ids=['series'], error='', unnumbered=0)
        query.resolve.side_effect = IntegrationError('来源暂不可用')
        self.sync(tmdb, emby, query, executor)
        saved = self.saved(item)
        self.assertFalse(saved['collection_confirmed'])
        self.assertEqual(saved['cms_delivery']['state'], 'submitted')
        self.assertTrue(executor.subscribe.call_args.args[0]['active'])
        query.resolve.assert_called_once()
        self.assertEqual(saved['library_episodes'], '1-3')

    def test_increased_total_resumes_and_failed_pause_is_reported(self):
        self.configure()
        config = self.mod.integration_config()
        config.update(cms_url='http://cms.example', cms_token=self.mod.encrypt_secret('token'), re0_via_cms=True)
        self.mod.persist_config(config)
        item = self.record(library_episodes='1-4')
        with self.mod.database() as db:
            value = self.mod.get_item(db, item['id'])
            value.update(collection_confirmed=True, emby=dict(state='matched'), re0=dict(slug='fixed', uploader='甲', error=''))
            db.execute('UPDATE items SET payload=? WHERE id=?', (json.dumps(value), item['id']))
        tmdb, emby, query, executor = Mock(), Mock(), Mock(), Mock()
        tmdb.tracking_metadata.return_value = self.metadata()
        emby.compare.side_effect = lambda *args: dict(state='matched', episodes=[1, 2, 3, 4], item_ids=['series'], error='', unnumbered=0)
        executor.subscribe.side_effect = IntegrationError('暂停请求失败')
        self.sync(tmdb, emby, query, executor)
        saved = self.saved(item)
        self.assertTrue(saved['collection_confirmed'])
        self.assertEqual(saved['cms_delivery']['state'], 'error')
        self.assertIn('CMS', self.mod.decorate(saved)['attention_reasons'][0]['detail'])
        query.resolve.assert_not_called()

        executor.subscribe.side_effect = lambda payload: dict(state='submitted', active=payload['active'], subscription_id='1')
        tmdb.tracking_metadata.return_value = self.metadata(total_episodes=5)
        query.resolve.side_effect = IntegrationError('来源暂不可用')
        self.sync(tmdb, emby, query, executor)
        self.assertFalse(self.saved(item)['collection_confirmed'])
        self.assertTrue(executor.subscribe.call_args.args[0]['active'])
        query.resolve.assert_called_once()

    def test_existing_verified_complete_and_unverified_record_are_distinguished(self):
        item = self.record(library_episodes='1-4')
        item['emby'] = dict(state='matched')
        item['re0'] = dict(error='旧来源失败')
        self.assertTrue(self.mod.source_checks_paused(item))
        self.assertEqual(self.mod.decorate(item)['attention_reasons'], [])
        item['emby'] = dict(state='error', error='不可达')
        self.assertFalse(self.mod.source_checks_paused(item))
        self.assertIn('RE0', self.mod.decorate(item)['attention_reasons'][0]['detail'])

    def test_manual_bind_of_complete_collection_does_not_start_transfer(self):
        item = self.record(library_episodes='1-4')
        with self.mod.database() as db:
            value = self.mod.get_item(db, item['id'])
            value.update(collection_confirmed=True, emby=dict(state='matched'))
            db.execute('UPDATE items SET payload=? WHERE id=?', (json.dumps(value), item['id']))
        query = Mock()
        query.resolve.return_value = dict(slug='fixed', uploader='甲', title='作品', share_url='https://115.com/s/abc',
            code='', resolution='4K', source='WEB', remark='', size='', resource_url='https://re0.me/resource/115/fixed')
        executor = Mock()
        executor.subscribe.return_value = dict(state='paused', active=False)
        with patch.object(self.mod, 'cms_client', return_value=query), \
             patch.object(self.mod, 'executor_client', return_value=executor), \
             patch.object(self.mod, 'run_cms_item') as run:
            response = self.client.post('/api/items/' + item['id'] + '/re0',
                json=dict(slug='fixed', uploader='甲'), headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertTrue(response.json['item']['source_checks_paused'])
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
