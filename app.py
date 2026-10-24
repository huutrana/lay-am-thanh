"""Single-process PWA server; one worker keeps FFmpeg resource use bounded."""
import atexit
import collections
import importlib.util
import logging
import os
import queue
import secrets
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

from engine import DownloadError, convert, normalize_url


class BusyError(Exception):
    pass


class JobManager:
    def __init__(self, root, converter, ttl=1800, janitor_interval=30):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.converter = converter
        self.ttl = ttl
        self.lock = threading.RLock()
        self.jobs = {}
        self.queue = queue.Queue()
        self.stop = threading.Event()
        self.janitor_interval = janitor_interval
        self.cleanup()
        self.worker = threading.Thread(target=self._work, daemon=True, name='audio-worker')
        self.janitor = threading.Thread(target=self._clean_loop, daemon=True, name='file-cleanup')
        self.worker.start()
        self.janitor.start()

    def submit(self, url):
        with self.lock:
            active = sum(job['status'] in {'queued', 'processing'} for job in self.jobs.values())
            if active >= 3 or len(self.jobs) >= 256:
                raise BusyError
            job_id = secrets.token_urlsafe(24)
            self.jobs[job_id] = {'id': job_id, 'status': 'queued', 'url': url,
                                 'created': time.time()}
            self.queue.put(job_id)
            return job_id

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job and job.get('finished') and time.time() - job['finished'] > self.ttl:
                return None
            return dict(job) if job else None

    def _work(self):
        while not self.stop.is_set():
            try:
                job_id = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            directory = self.root / job_id
            try:
                with self.lock:
                    job = self.jobs[job_id]
                    job['status'] = 'processing'
                directory.mkdir()
                result = self.converter(job['url'], directory)
                output = directory / 'audio.mp3'
                if not output.is_file() or output.stat().st_size == 0:
                    raise DownloadError('Không tạo được tệp MP3. Hãy thử lại.')
                with self.lock:
                    job.update({key: result[key] for key in ('title', 'filename', 'duration', 'size')})
                    job.update(status='ready', finished=time.time())
            except Exception as error:
                shutil.rmtree(directory, ignore_errors=True)
                message = str(error) if isinstance(error, DownloadError) else 'Xử lý âm thanh bị lỗi. Hãy thử lại sau.'
                # Record only the class, never downloader output, URL signatures or secrets.
                logging.getLogger(__name__).warning('Audio job failed: %s', type(error).__name__)
                with self.lock:
                    job.update(status='error', error=message, finished=time.time())
            finally:
                self.queue.task_done()

    def cleanup(self):
        now = time.time()
        with self.lock:
            expired = [key for key, job in self.jobs.items()
                       if job.get('finished') and now - job['finished'] > self.ttl]
            for key in expired:
                shutil.rmtree(self.root / key, ignore_errors=True)
                del self.jobs[key]
            # On restart, old task files have no corresponding in-memory record.
            for path in self.root.iterdir():
                if path.is_dir() and not path.is_symlink() and path.name not in self.jobs:
                    if now - path.stat().st_mtime > self.ttl:
                        shutil.rmtree(path, ignore_errors=True)

    def _clean_loop(self):
        while not self.stop.wait(self.janitor_interval):
            self.cleanup()

    def close(self):
        self.stop.set()
        self.worker.join(timeout=4)
        self.janitor.join(timeout=2)


def create_app(config=None):
    app = Flask(__name__, static_folder='static')
    app.config.update(
        DATA_DIR=os.environ.get('DATA_DIR', str(Path(__file__).parent / 'data')),
        CONVERTER=convert, JOB_TTL=1800, JANITOR_INTERVAL=30, RATE_LIMIT=6,
        MAX_CONTENT_LENGTH=8192,
        TRUSTED_HOSTS=[host.strip() for host in os.environ.get(
            'ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1]').split(',') if host.strip()],
    )
    if config:
        app.config.update(config)
    render_hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
    if render_hostname:
        app.config['TRUSTED_HOSTS'] = [*app.config['TRUSTED_HOSTS'], render_hostname]
    manager = JobManager(app.config['DATA_DIR'], app.config['CONVERTER'],
                         app.config['JOB_TTL'], app.config['JANITOR_INTERVAL'])
    app.extensions['jobs'] = manager
    atexit.register(manager.close)
    attempts = collections.OrderedDict()
    rate_lock = threading.Lock()

    @app.before_request
    def guard_api():
        if request.method != 'POST' or not request.path.startswith('/api/'):
            return None
        origin = request.headers.get('Origin')
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            return jsonify(error='Yêu cầu phải gửi từ chính ứng dụng.'), 403
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in {'http', 'https'} or parsed.netloc != request.host:
                return jsonify(error='Yêu cầu phải gửi từ chính ứng dụng.'), 403
        if not request.is_json:
            return jsonify(error='Yêu cầu không hợp lệ. Hãy tải lại trang.'), 400
        return None

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; media-src 'self'; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith('/api/'):
            return jsonify(error='Yêu cầu không hợp lệ hoặc dữ liệu đã hết hạn.'), error.code
        return 'Không tìm thấy trang hoặc yêu cầu không hợp lệ.', error.code

    @app.get('/')
    def index():
        return send_from_directory(app.static_folder, 'index.html')

    @app.get('/sw.js')
    def service_worker():
        response = send_from_directory(app.static_folder, 'sw.js', mimetype='text/javascript')
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    @app.get('/manifest.webmanifest')
    def manifest():
        return send_from_directory(app.static_folder, 'manifest.webmanifest',
                                   mimetype='application/manifest+json')

    @app.get('/api/health')
    def health():
        ready = bool(shutil.which('ffmpeg') and shutil.which('ffprobe')
                     and importlib.util.find_spec('yt_dlp'))
        return jsonify(ready=ready), 200 if ready else 503

    @app.post('/api/jobs')
    def submit():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='Hãy dán một link video TikTok hoặc Facebook.'), 400
        try:
            url = normalize_url(data.get('url'))
        except DownloadError as error:
            return jsonify(error=str(error)), 400
        with rate_lock:
            now = time.monotonic()
            ip = request.remote_addr or 'unknown'
            # Trust socket address only; spoofed forwarded headers cannot bypass the limit.
            while attempts and now - next(iter(attempts.values()))[-1] > 60:
                attempts.popitem(last=False)
            recent = [entry for entry in attempts.get(ip, []) if now - entry < 60]
            if len(recent) >= app.config['RATE_LIMIT']:
                return jsonify(error='Bạn tải hơi nhanh. Hãy chờ một phút rồi thử lại.'), 429, {'Retry-After': '60'}
            if len(attempts) >= 2048 and ip not in attempts:
                return jsonify(error='Máy chủ đang bận. Hãy thử lại sau.'), 429, {'Retry-After': '60'}
            recent.append(now)
            attempts[ip] = recent
            attempts.move_to_end(ip)
        try:
            job_id = manager.submit(url)
        except BusyError:
            return jsonify(error='Máy chủ đang xử lý đủ lượt. Hãy chờ một chút rồi thử lại.'), 429, {'Retry-After': '15'}
        return jsonify(id=job_id, status='queued'), 202

    @app.get('/api/jobs/<job_id>')
    def status(job_id):
        job = manager.get(job_id)
        if job is None:
            return jsonify(error='Lượt tải đã hết hạn. Hãy dán link để tải lại.'), 404
        result = {key: job[key] for key in ('id', 'status', 'error', 'title', 'filename', 'duration', 'size') if key in job}
        if job['status'] == 'ready':
            result['download_url'] = f'/api/jobs/{job_id}/download'
        return jsonify(result)

    @app.get('/api/jobs/<job_id>/download')
    def download(job_id):
        job = manager.get(job_id)
        if job is None:
            return jsonify(error='Tệp đã hết hạn. Hãy tải lại từ link video.'), 404
        if job['status'] != 'ready':
            return jsonify(error='Tệp MP3 chưa sẵn sàng.'), 409
        path = manager.root / job_id / 'audio.mp3'
        if not path.is_file():
            return jsonify(error='Tệp đã hết hạn. Hãy tải lại từ link video.'), 404
        return send_file(path, mimetype='audio/mpeg', as_attachment=True,
                         download_name=job['filename'], conditional=True, max_age=0)

    return app


if __name__ == '__main__':
    from waitress import serve
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '8765'))
    application = create_app()
    print(f'Ung dung dang chay: http://{host}:{port}', flush=True)
    serve(application, host=host, port=port, threads=6, max_request_body_size=8192)
