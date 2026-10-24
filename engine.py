"""TikTok/Facebook network boundary and bounded audio conversion."""
import ipaddress
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
from pathlib import Path

MAX_BYTES = 100 * 1024**2
MAX_DURATION = 600
TIMEOUT = 180
VIDEO_FORMAT = 'best[vcodec!=none][acodec!=none]'
EXTRACTORS = 'TikTok,facebook,facebook:reel'
TIKTOK_HOSTS = {'tiktok.com', 'www.tiktok.com', 'm.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com', 'lite.tiktok.com'}
FACEBOOK_HOSTS = {'facebook.com', 'www.facebook.com', 'm.facebook.com', 'web.facebook.com', 'fb.watch', 'www.fb.watch'}
HOSTS = TIKTOK_HOSTS | FACEBOOK_HOSTS
VIDEO_PATH = re.compile(r'^/@[^/\s]+/video/[0-9]{10,25}/?$')
SHORT_PATH = re.compile(r'^/(?:t/)?[a-zA-Z0-9_-]+/?$')


class DownloadError(Exception):
    """Safe, user-facing failure; never contains raw subprocess output."""


def normalize_url(text: str) -> str:
    if not isinstance(text, str) or len(text) > 4096:
        raise DownloadError('Hãy dán một link video TikTok hoặc Facebook hợp lệ.')
    matches = re.findall(r'https?://[^\s<>"\u200b]+', text)
    if len(matches) != 1:
        raise DownloadError('Mỗi lượt chỉ nhận một link video TikTok hoặc Facebook.')
    raw = matches[0].rstrip('.,;!)]}。')
    try:
        parsed = urllib.parse.urlsplit(raw)
        if (parsed.scheme != 'https' or parsed.hostname not in HOSTS
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise ValueError
    except ValueError:
        raise DownloadError('Chỉ nhận link HTTPS của TikTok hoặc Facebook.') from None
    path = parsed.path
    if parsed.hostname in FACEBOOK_HOSTS:
        host = 'fb.watch' if parsed.hostname.endswith('fb.watch') else 'www.facebook.com'
        query = ''
        if host == 'fb.watch':
            valid = SHORT_PATH.fullmatch(path)
        elif path in ('/watch', '/watch/', '/video.php'):
            values = urllib.parse.parse_qs(parsed.query).get('v', [])
            valid = len(values) == 1 and re.fullmatch(r'[0-9]{5,25}', values[0])
            if valid:
                query = urllib.parse.urlencode({'v': values[0]})
        else:
            valid = (re.fullmatch(r'/reel/[0-9]{5,25}/?', path)
                     or re.fullmatch(r'/[a-zA-Z0-9._-]+/videos/(?:[a-zA-Z0-9._-]+/)?[0-9]{5,25}/?', path)
                     or re.fullmatch(r'/share/[rv]/[a-zA-Z0-9_-]+/?', path))
        if not valid:
            raise DownloadError('Hãy dùng link video hoặc Reel Facebook công khai.')
        return urllib.parse.urlunsplit(('https', host, path, query, ''))
    if parsed.hostname in {'vm.tiktok.com', 'vt.tiktok.com'}:
        valid = SHORT_PATH.fullmatch(path)
    else:
        valid = VIDEO_PATH.fullmatch(path) or re.fullmatch(r'/t/[a-zA-Z0-9_-]+/?', path)
    if not valid:
        raise DownloadError('Hãy dùng link của một video, không phải trang tài khoản.')
    return urllib.parse.urlunsplit(('https', parsed.hostname, path, '', ''))


def validate_public_host(host: str) -> None:
    if host not in HOSTS:
        raise DownloadError('Link chuyển hướng ra ngoài nền tảng được hỗ trợ.')
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not answers or any(not ipaddress.ip_address(answer[4][0]).is_global for answer in answers):
            raise DownloadError('Địa chỉ nền tảng video không hợp lệ trên mạng hiện tại.')
    except OSError:
        raise DownloadError('Không kết nối được nền tảng video. Hãy kiểm tra mạng và thử lại.') from None


def check_redirect_url(previous_url: str, new_url: str) -> str:
    normalized = normalize_url(urllib.parse.urljoin(previous_url, new_url))
    old_fb = urllib.parse.urlsplit(previous_url).hostname in FACEBOOK_HOSTS
    new_fb = urllib.parse.urlsplit(normalized).hostname in FACEBOOK_HOSTS
    if old_fb != new_fb:
        raise DownloadError('Link chuyển sang nền tảng khác nên không được xử lý.')
    validate_public_host(urllib.parse.urlsplit(normalized).hostname)
    return normalized


def is_direct_video(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname in FACEBOOK_HOSTS:
        return parsed.hostname != 'fb.watch' and not parsed.path.startswith('/share/')
    return bool(VIDEO_PATH.fullmatch(parsed.path))


def resolve_url(url: str) -> str:
    url = normalize_url(url)
    validate_public_host(urllib.parse.urlsplit(url).hostname)
    if is_direct_video(url):
        return url
    # App share links need the same browser TLS connection as Facebook extraction.
    # Follow redirects manually so curl cannot fetch an unchecked destination.
    from curl_cffi import requests
    try:
        with requests.Session(impersonate='chrome', trust_env=False) as session:
            visited = {url}
            for _ in range(5):
                response = session.get(url, allow_redirects=False, timeout=12, stream=True)
                try:
                    if response.status_code not in (301, 302, 303, 307, 308):
                        raise DownloadError('Link chia sẻ chưa mở được. Hãy sao chép lại link từ video công khai.')
                    location = response.headers.get('Location')
                    if not location:
                        raise DownloadError('Link chia sẻ không có địa chỉ video đích. Hãy sao chép lại link.')
                    target = check_redirect_url(url, location)
                finally:
                    response.close()
                if target in visited:
                    raise DownloadError('Link chia sẻ chuyển hướng lặp. Hãy sao chép lại link video.')
                if is_direct_video(target):
                    return target
                visited.add(target)
                url = target
            raise DownloadError('Link chia sẻ chuyển hướng quá nhiều lần. Hãy dùng link video đầy đủ.')
    except (requests.exceptions.RequestException, TimeoutError, OSError):
        raise DownloadError('Không mở được link chia sẻ. Hãy thử link video đầy đủ.') from None


def safe_filename(title: str, platform: str = 'TikTok') -> str:
    title = unicodedata.normalize('NFC', title)
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', ' ', title)
    title = re.sub(r'\s+', ' ', title).strip(' .')[:80].rstrip(' .')
    # Prefix also avoids Windows reserved names such as CON and AUX.
    return f'{platform} - {title or "am thanh"}.mp3'


def check_metadata(info: dict) -> None:
    duration = info.get('duration')
    if duration is not None and (not isinstance(duration, (int, float))
                                 or not math.isfinite(duration) or duration > MAX_DURATION):
        raise DownloadError('Bản này nhận video dài tối đa 10 phút.')
    size = info.get('filesize') or info.get('filesize_approx')
    if size is not None and size > MAX_BYTES:
        raise DownloadError('Video vượt giới hạn 100 MB. Hãy chọn video nhỏ hơn.')


def check_input_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise DownloadError('Không nhận được tệp âm thanh từ video.')
    if path.stat().st_size > MAX_BYTES:
        raise DownloadError('Video vượt giới hạn 100 MB. Hãy chọn video nhỏ hơn.')


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
    else:
        try:
            if os.getpgid(process.pid) == process.pid:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def run_process(args: list[str], directory: Path, timeout: float = TIMEOUT) -> str:
    if timeout <= 0:
        raise DownloadError('Xử lý quá lâu. Hãy thử lại với video ngắn hơn.')
    options = ({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt'
               else {'start_new_session': os.environ.get('AUDIO_WORKER_CHILD') != '1'})
    # Anonymous files keep signed media URLs and library errors out of logs/UI.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            process = subprocess.Popen(args, cwd=directory, stdout=out, stderr=err,
                                       stdin=subprocess.DEVNULL, **options)
        except OSError:
            raise DownloadError('Máy chủ thiếu công cụ xử lý. Hãy kiểm tra cấu hình.') from None
        started = time.monotonic()
        try:
            while process.poll() is None:
                if time.monotonic() - started > timeout:
                    raise DownloadError('Xử lý quá lâu. Hãy thử lại với video ngắn hơn.')
                total = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
                if total > MAX_BYTES * 2 or out.tell() > 8 * 1024**2 or err.tell() > 2 * 1024**2:
                    raise DownloadError('Tệp quá lớn hoặc phản hồi không hợp lệ. Hãy thử video khác.')
                time.sleep(0.1)
            if process.returncode:
                err.seek(0)
                detail = err.read(2 * 1024**2).decode('utf-8', errors='replace').lower()
                if 'file is larger' in detail or 'max-filesize' in detail:
                    raise DownloadError('Video vượt giới hạn 100 MB.')
                raise DownloadError('Chưa lấy được âm thanh. Video có thể không công khai, yêu cầu đăng nhập hoặc nền tảng đang chặn tải. Hãy thử link video khác.')
            out.seek(0)
            return out.read(8 * 1024**2).decode('utf-8', errors='replace')
        finally:
            stop_process(process)


def fetch_source(url: str, directory: Path, deadline: float) -> tuple[Path, dict]:
    common = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-cache-dir',
              '--no-playlist', '--no-progress', '--no-warnings', '--quiet',
              '--socket-timeout', '12', '--retries', '1', '--extractor-retries', '1',
              '--use-extractors', EXTRACTORS, '--proxy', '']
    if urllib.parse.urlsplit(url).hostname in FACEBOOK_HOSTS:
        common.extend(['--impersonate', 'chrome'])
    raw = run_process(common + ['--skip-download', '--dump-single-json', '--', url],
                      directory, deadline - time.monotonic())
    try:
        info = json.loads(raw)
        if not isinstance(info, dict) or info.get('_type', 'video') != 'video':
            raise ValueError
        check_metadata(info)
    except (ValueError, TypeError):
        raise DownloadError('Nền tảng video trả về dữ liệu không hợp lệ. Hãy thử lại sau.') from None
    # Facebook often separates DASH audio/video. TikTok audio-only can be music.
    format_choice = 'bestaudio/best' if urllib.parse.urlsplit(url).hostname in FACEBOOK_HOSTS else VIDEO_FORMAT
    run_process(common + ['--format', format_choice, '--max-filesize', str(MAX_BYTES),
                          '--abort-on-unavailable-fragments', '--output', 'source.%(ext)s',
                          '--', url], directory, deadline - time.monotonic())
    files = [p for p in directory.glob('source.*') if p.suffix not in {'.part', '.ytdl'}]
    if len(files) != 1:
        raise DownloadError('Không tải được tệp nguồn đầy đủ từ video.')
    check_input_file(files[0])
    return files[0], info


def probe(path: Path, directory: Path, deadline: float) -> dict:
    raw = run_process(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                       '-show_entries', 'format=duration:stream=codec_type,codec_name',
                       '-of', 'json', str(path)], directory, deadline - time.monotonic())
    try:
        data = json.loads(raw)
        duration = float(data['format']['duration'])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
        if not any(s.get('codec_type') == 'audio' for s in data.get('streams', [])):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise DownloadError('Video không có luồng âm thanh đọc được.') from None
    check_metadata({'duration': duration})
    return {'duration': duration, 'streams': data['streams']}


def _convert(url: str, directory: Path) -> dict:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + TIMEOUT
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise DownloadError('Máy chủ chưa có FFmpeg/FFprobe. Hãy kiểm tra cấu hình.')
    resolved = resolve_url(url)
    source, metadata = fetch_source(resolved, directory, deadline)
    probe(source, directory, deadline)
    output = directory / 'audio.mp3'
    run_process(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                 '-protocol_whitelist', 'file,pipe', '-i', str(source), '-map', '0:a:0',
                 '-vn', '-sn', '-dn', '-map_metadata', '-1', '-t', str(MAX_DURATION),
                 '-codec:a', 'libmp3lame', '-b:a', '192k', str(output)],
                directory, deadline - time.monotonic())
    checked = probe(output, directory, deadline)
    check_input_file(output)
    if not any(stream.get('codec_name') == 'mp3' for stream in checked['streams']):
        raise DownloadError('Không tạo được MP3 hợp lệ. Hãy thử lại.')
    source.unlink(missing_ok=True)
    platform = 'Facebook' if urllib.parse.urlsplit(resolved).hostname in FACEBOOK_HOSTS else 'TikTok'
    title = str(metadata.get('title') or f'Âm thanh {platform}')[:200]
    return {'title': title, 'filename': safe_filename(title, platform), 'duration': checked['duration'],
            'size': output.stat().st_size}


def convert(url: str, directory: Path) -> dict:
    """Bound the entire job, including OS DNS calls, in a killable process tree."""
    url = normalize_url(url)
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    raw = run_process([sys.executable, str(Path(__file__).resolve()), url], directory, TIMEOUT)
    try:
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError
    except (ValueError, TypeError):
        raise DownloadError('Không nhận được kết quả xử lý hợp lệ. Hãy thử lại.') from None
    if 'error' in result:
        raise DownloadError(result['error'])
    return result


if __name__ == '__main__':
    # On Linux keep nested download/FFmpeg processes in the outer worker's group,
    # so the API's hard timeout also stops their resource use.
    os.environ['AUDIO_WORKER_CHILD'] = '1'
    try:
        result = _convert(sys.argv[1], Path.cwd())
    except DownloadError as error:
        result = {'error': str(error)}
    except Exception:
        result = {'error': 'Xử lý âm thanh bị lỗi. Hãy thử lại sau.'}
    print(json.dumps(result, ensure_ascii=True))
