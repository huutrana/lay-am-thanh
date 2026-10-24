import tempfile
import threading
import time
import unittest
from pathlib import Path

from app import create_app
from engine import DownloadError

VIDEO = 'https://www.tiktok.com/@tester/video/6742501081818877190'


def successful_convert(url, directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'audio.mp3').write_bytes(b'ID3test-audio')
    return {'title': '<script>bad</script>', 'filename': 'TikTok - test.mp3',
            'duration': 27, 'size': 13}


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'DATA_DIR': self.temp.name,
                               'CONVERTER': successful_convert, 'RATE_LIMIT': 50,
                               'JOB_TTL': 2, 'JANITOR_INTERVAL': 0.05})
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions['jobs'].close()
        self.temp.cleanup()

    def submit(self):
        response = self.client.post('/api/jobs', json={'url': VIDEO})
        self.assertEqual(response.status_code, 202)
        return response.json['id']

    def wait_for(self, job_id, state='ready'):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            response = self.client.get('/api/jobs/' + job_id)
            if response.json.get('status') == state:
                return response.json
            time.sleep(0.01)
        self.fail(f'job did not reach {state}: {response.json}')

    def test_real_job_lifecycle_and_attachment(self):
        job_id = self.submit()
        result = self.wait_for(job_id)
        self.assertEqual(result['title'], '<script>bad</script>')
        download = self.client.get(result['download_url'])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, b'ID3test-audio')
        self.assertEqual(download.mimetype, 'audio/mpeg')
        self.assertIn('attachment', download.headers['Content-Disposition'])
        self.assertIn('no-store', download.headers['Cache-Control'])
        download.close()

    def test_rejects_bad_url_and_non_object_body(self):
        for body in [{'url': 'https://evil.test/a'}, [], None]:
            response = self.client.post('/api/jobs', json=body, content_type='application/json')
            self.assertEqual(response.status_code, 400)

    def test_rejects_cross_origin_and_host_spoofing(self):
        for headers in [{'Origin': 'https://evil.test'},
                        {'Sec-Fetch-Site': 'cross-site'},
                        {'Host': 'evil.test'}]:
            response = self.client.post('/api/jobs', json={'url': VIDEO}, headers=headers)
            self.assertIn(response.status_code, (400, 403))

    def test_missing_and_unfinished_download_are_not_success(self):
        self.assertEqual(self.client.get('/api/jobs/no-such-id/download').status_code, 404)
        gate = threading.Event()

        def blocked(url, directory):
            gate.wait(2)
            return successful_convert(url, directory)

        self.app.extensions['jobs'].converter = blocked
        try:
            job_id = self.submit()
            self.assertEqual(self.client.get(f'/api/jobs/{job_id}/download').status_code, 409)
        finally:
            gate.set()
            self.wait_for(job_id)

    def test_failure_is_safe_and_partial_files_removed(self):
        def fails(url, directory):
            (directory / 'source.part').write_bytes(b'partial')
            raise RuntimeError('secret-internal-data')

        self.app.extensions['jobs'].converter = fails
        with self.assertLogs('app', level='WARNING'):
            job_id = self.submit()
            result = self.wait_for(job_id, 'error')
        self.assertNotIn('secret-internal-data', str(result))
        self.assertFalse((Path(self.temp.name) / job_id).exists())

    def test_missing_output_is_reported_as_error(self):
        self.app.extensions['jobs'].converter = lambda *_: {'title': 'empty'}
        with self.assertLogs('app', level='WARNING'):
            self.wait_for(self.submit(), 'error')

    def test_expired_files_are_removed_without_new_requests(self):
        job_id = self.submit()
        self.wait_for(job_id)
        manager = self.app.extensions['jobs']
        with manager.lock:
            manager.jobs[job_id]['finished'] = time.time() - 5
        deadline = time.monotonic() + 2
        while (Path(self.temp.name) / job_id).exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse((Path(self.temp.name) / job_id).exists())
        self.assertEqual(self.client.get(f'/api/jobs/{job_id}').status_code, 404)

    def test_queue_capacity_is_bounded(self):
        gate = threading.Event()
        entered = threading.Event()

        def blocked(url, directory):
            entered.set()
            gate.wait(3)
            return successful_convert(url, directory)

        self.app.extensions['jobs'].converter = blocked
        try:
            self.submit()
            self.assertTrue(entered.wait(1))
            self.submit()
            self.submit()
            self.assertEqual(self.client.post('/api/jobs', json={'url': VIDEO}).status_code, 429)
        finally:
            gate.set()

    def test_rate_limit_returns_retry_after(self):
        self.app.config['RATE_LIMIT'] = 1
        self.submit()
        response = self.client.post('/api/jobs', json={'url': VIDEO})
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response.headers)

    def test_static_and_manifest_routes(self):
        with self.client.get('/') as response:
            self.assertEqual(response.status_code, 200)
        with self.client.get('/manifest.webmanifest') as manifest:
            self.assertEqual(manifest.status_code, 200)
            self.assertEqual(manifest.json['display'], 'standalone')
        with self.client.get('/sw.js') as response:
            self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()
