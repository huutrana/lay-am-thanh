"""Check that the deployment's outer deadline also kills nested processes."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import engine


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux process groups')
class ProcessGroupTests(unittest.TestCase):
    def test_timeout_kills_nested_downloader(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            worker = directory / 'worker.py'
            worker.write_text(
                "import os,sys\n"
                f"sys.path.insert(0,{str(Path(engine.__file__).parent)!r})\n"
                "import engine\n"
                "os.environ['AUDIO_WORKER_CHILD']='1'\n"
                "code=\"import os,time; open('child.pid','w').write(str(os.getpid())); time.sleep(30)\"\n"
                "engine.run_process([sys.executable,'-c',code],engine.Path.cwd(),30)\n",
                encoding='utf-8',
            )
            try:
                with self.assertRaises(engine.DownloadError):
                    engine.run_process([sys.executable, str(worker)], directory, timeout=1)
                pid = int((directory / 'child.pid').read_text())
                time.sleep(0.1)
                stat = Path(f'/proc/{pid}/stat')
                self.assertTrue(not stat.exists() or stat.read_text().split()[2] == 'Z')
            finally:
                pidfile = directory / 'child.pid'
                if pidfile.exists():
                    try:
                        os.kill(int(pidfile.read_text()), 9)
                    except ProcessLookupError:
                        pass
