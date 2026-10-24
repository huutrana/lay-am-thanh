import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import engine


VIDEO = 'https://www.tiktok.com/@tester/video/6742501081818877190'


class URLTests(unittest.TestCase):
    def test_accepts_tiktok_lite_link_copied_from_phone(self):
        self.assertEqual(engine.normalize_url('https://lite.tiktok.com/t/ZSgHx4bsG/'),
                         'https://lite.tiktok.com/t/ZSgHx4bsG/')

    def test_short_facebook_redirect_uses_browser_connection(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.status_code = 302
        response.headers = {'Location': '/reel/879765251892417/?mibextid=share'}
        with patch('engine.validate_public_host'), patch('curl_cffi.requests.Session') as factory:
            factory.return_value.__enter__.return_value.get.return_value = response
            result = engine.resolve_url('https://www.facebook.com/share/r/TestShare123/')
            self.assertEqual(result, 'https://www.facebook.com/reel/879765251892417/')
            self.assertEqual(factory.call_args.kwargs['impersonate'], 'chrome')
            call = factory.return_value.__enter__.return_value.get.call_args
            self.assertIs(call.kwargs['allow_redirects'], False)

    def test_short_link_does_not_fetch_untrusted_redirect_target(self):
        from unittest.mock import MagicMock
        response = MagicMock(status_code=302, headers={'Location': 'https://127.0.0.1/private'})
        with patch('engine.validate_public_host'), patch('curl_cffi.requests.Session') as factory:
            get = factory.return_value.__enter__.return_value.get
            get.return_value = response
            with self.assertRaises(engine.DownloadError):
                engine.resolve_url('https://www.facebook.com/share/r/TestShare123/')
            self.assertEqual(get.call_count, 1)
            response.close.assert_called_once()

    def test_short_link_loop_stops_without_repeated_fetch(self):
        from unittest.mock import MagicMock
        url = 'https://lite.tiktok.com/t/ZSgHx4bsG/'
        response = MagicMock(status_code=302, headers={'Location': url})
        with patch('engine.validate_public_host'), patch('curl_cffi.requests.Session') as factory:
            get = factory.return_value.__enter__.return_value.get
            get.return_value = response
            with self.assertRaisesRegex(engine.DownloadError, 'lặp'):
                engine.resolve_url(url)
            self.assertEqual(get.call_count, 1)

    def test_facebook_redirect_preserves_video_id_in_query(self):
        with patch('engine.validate_public_host'):
            result = engine.check_redirect_url('https://fb.watch/AbCd/',
                'https://www.facebook.com/watch/?v=879765251892417&ref=share')
        self.assertEqual(result, 'https://www.facebook.com/watch/?v=879765251892417')

    def test_facebook_video_reel_watch_and_share(self):
        pairs = [
            ('https://www.facebook.com/reel/123456789012345/?mibextid=abc', 'https://www.facebook.com/reel/123456789012345/'),
            ('https://www.facebook.com/watch/?v=123456789012345&ref=share', 'https://www.facebook.com/watch/?v=123456789012345'),
            ('https://m.facebook.com/test/videos/123456789012345/', 'https://www.facebook.com/test/videos/123456789012345/'),
            ('https://www.facebook.com/share/r/AbC123/', 'https://www.facebook.com/share/r/AbC123/'),
            ('https://fb.watch/AbC123/', 'https://fb.watch/AbC123/'),
        ]
        for url, expected in pairs:
            with self.subTest(url=url):
                self.assertEqual(engine.normalize_url(url), expected)

    def test_rejects_facebook_login_profile_and_fake_domain(self):
        for url in ['https://facebook.com.evil.test/reel/123456789012345/',
                    'https://www.facebook.com/login/?next=https://127.0.0.1',
                    'https://www.facebook.com/test', 'https://www.facebook.com/watch/?v=evil',
                    'https://www.facebook.com/l.php?u=https://evil.test']:
            with self.subTest(url=url), self.assertRaises(engine.DownloadError):
                engine.normalize_url(url)

    def test_tiktok_redirect_cannot_cross_to_facebook(self):
        with self.assertRaises(engine.DownloadError):
            engine.check_redirect_url(VIDEO,
                'https://www.facebook.com/reel/123456789012345/')

    def test_extracts_share_link_and_drops_tracking(self):
        self.assertEqual(engine.normalize_url(f'Xem video: {VIDEO}?foo=bar nhé'), VIDEO)

    def test_accepts_short_share_links(self):
        self.assertEqual(engine.normalize_url('https://vt.tiktok.com/ZS123Ab/'),
                         'https://vt.tiktok.com/ZS123Ab/')

    def test_rejects_untrusted_or_unsupported_urls(self):
        for url in ['https://tiktok.com.evil.test/@x/video/123',
                    'https://www.tiktok.com@127.0.0.1/video/123',
                    'http://www.tiktok.com/@x/video/123',
                    'https://www.tiktok.com:8888/@x/video/123',
                    'https://www.tiktok.com/@x', 'https://127.0.0.1/a',
                    '--exec arbitrary', '', VIDEO + ' ' + VIDEO]:
            with self.subTest(url=url), self.assertRaises(engine.DownloadError):
                engine.normalize_url(url)

    def test_rejects_private_dns_answer(self):
        with patch('engine.socket.getaddrinfo', return_value=[
            (2, 1, 6, '', ('127.0.0.1', 443))
        ]), self.assertRaises(engine.DownloadError):
            engine.validate_public_host('www.tiktok.com')

    def test_redirect_cannot_leave_tiktok(self):
        with self.assertRaises(engine.DownloadError):
            engine.check_redirect_url(VIDEO, 'http://127.0.0.1/private')


class ProcessingTests(unittest.TestCase):
    def test_extractor_configuration_includes_facebook_reels(self):
        from yt_dlp import YoutubeDL
        with YoutubeDL({'quiet': True, 'allowed_extractors': engine.EXTRACTORS.split(',')}) as downloader:
            self.assertIn('FacebookReel', downloader._ies)
            self.assertIn('Facebook', downloader._ies)
            self.assertIn('TikTok', downloader._ies)

    def test_total_deadline_covers_a_stalled_network_resolver(self):
        import time
        with tempfile.TemporaryDirectory() as temp:
            worker = Path(temp) / 'stalled_worker.py'
            worker.write_text('import time; time.sleep(10)', encoding='utf-8')

            def slow_dns(*args, **kwargs):
                time.sleep(0.8)
                return [(2, 1, 6, '', ('8.8.8.8', 443))]

            started = time.monotonic()
            with patch('engine.TIMEOUT', 0.15), patch('engine.__file__', str(worker)), \
                    patch('engine.socket.getaddrinfo', side_effect=slow_dns):
                with self.assertRaises(engine.DownloadError):
                    engine.convert(VIDEO, Path(temp) / 'job')
            self.assertLess(time.monotonic() - started, 0.7)

    def test_download_selects_video_with_audio_not_separate_music(self):
        # TikTok's audio-only format can point to the music, not the video's mix.
        from yt_dlp import YoutubeDL
        selector = YoutubeDL({'quiet': True}).build_format_selector(engine.VIDEO_FORMAT)
        formats = [
            {'format_id': 'video', 'ext': 'mp4', 'vcodec': 'h264', 'acodec': 'aac',
             'url': 'https://example.test/video'},
            {'format_id': 'music', 'ext': 'm4a', 'vcodec': 'none', 'acodec': 'aac',
             'url': 'https://example.test/music'},
        ]
        selected = list(selector({'formats': formats, 'has_merged_format': True,
                                  'incomplete_formats': False}))
        self.assertEqual([item['format_id'] for item in selected], ['video'])

    def test_rejects_long_video_and_known_oversize(self):
        for metadata in [{'duration': 601}, {'filesize': 100 * 1024**2 + 1}]:
            with self.subTest(metadata=metadata), self.assertRaises(engine.DownloadError):
                engine.check_metadata(metadata)

    def test_accepts_unknown_duration_for_later_probe(self):
        engine.check_metadata({})

    def test_timeout_stops_process_and_reports_clean_error(self):
        import sys
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(
            engine.DownloadError, 'quá lâu'
        ):
            engine.run_process([sys.executable, '-c', 'import time; time.sleep(10)'],
                               Path(temp), timeout=0.15)

    def test_actual_file_size_is_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'large.mp4'
            with path.open('wb') as file:
                file.truncate(100 * 1024**2 + 1)
            with self.assertRaises(engine.DownloadError):
                engine.check_input_file(path)

    def test_filename_is_safe_and_has_mp3_extension(self):
        name = engine.safe_filename('../CON: nhạc <test> / ?')
        self.assertTrue(name.endswith('.mp3'))
        self.assertNotRegex(name, r'[<>:"/\\|?*]')
        self.assertLessEqual(len(name), 100)


if __name__ == '__main__':
    unittest.main()
