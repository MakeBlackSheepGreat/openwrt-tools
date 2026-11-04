"""Native writer exclusion: exact argv, bounded packaged tool, explicit result."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.native_boot import codec

WORKER='/data/local/tmp/mu300-desktop-012345abcdef/run.sh'
PREVIOUS=WORKER.rsplit('/',1)[0]+'/busybox'
BUSYBOX=os.environ.get('OPENWRT_TEST_BUSYBOX') or shutil.which('busybox')


class WorkerResult(unittest.TestCase):
    def test_missing_timeout_failure_or_masked_su_status_never_means_idle(self):
        check=codec().native_worker_active
        for output in ('','NATIVE_CHECK_FAILED','Killed\nNATIVE_CHECK_FAILED','unexpected','NATIVE_BUSY\nNATIVE_IDLE'):
            with self.subTest(output=output),self.assertRaisesRegex(ValueError,'Cannot verify'):
                check(lambda command:output,'/packaged/busybox',WORKER)
        self.assertFalse(check(lambda command:'NATIVE_IDLE\n','/packaged/busybox',WORKER))
        self.assertTrue(check(lambda command:'NATIVE_BUSY\n','/packaged/busybox',WORKER))

    def test_untrusted_worker_path_is_rejected_before_any_command(self):
        for worker in ('/tmp/run.sh',WORKER+'; reboot',WORKER+' extra'):
            with self.subTest(worker=worker),self.assertRaisesRegex(ValueError,'Invalid'):
                codec().native_worker_active(lambda command:self.fail('must not execute'),'/packaged/busybox',worker)

    def test_only_the_packaged_bounded_single_process_probe_is_executed(self):
        commands=[]
        codec().native_worker_active(lambda command:commands.append(command) or 'NATIVE_IDLE', '/packaged/busybox',WORKER)
        self.assertEqual(len(commands),1)
        self.assertIn('/packaged/busybox timeout -s KILL 5 /packaged/busybox pgrep -f -x',commands[0])
        self.assertNotIn('/proc/',commands[0])
        self.assertNotIn('tr ',commands[0])


@unittest.skipUnless(os.name=='posix' and BUSYBOX and shutil.which('cc'),'POSIX BusyBox and fixture compiler')
class LiveWorker(unittest.TestCase):
    def setUp(self):
        applets=subprocess.run([BUSYBOX,'--list'],capture_output=True,text=True,check=True).stdout.splitlines()
        if 'pgrep' not in applets:self.skipTest('selected BusyBox lacks pgrep; supply OPENWRT_TEST_BUSYBOX')

    def test_actual_busybox_detects_our_writer_but_not_embedded_command_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'sleep.c';program=root/'sleep'
            source.write_text('#include <unistd.h>\nint main(void) { sleep(30); return 0; }\n')
            subprocess.run(['cc',str(source),'-o',str(program)],check=True)
            def execute(command):
                return subprocess.run(['sh','-c',command],capture_output=True,text=True,timeout=8,check=True).stdout
            check=codec().native_worker_active;bb=BUSYBOX
            self.assertFalse(check(execute,bb,WORKER))
            for argv in ([PREVIOUS,'sh',WORKER],[PREVIOUS,'nsenter','-t','1','-m',PREVIOUS,'sh',WORKER]):
                with self.subTest(argv=argv):
                    child=subprocess.Popen(argv,executable=str(program))
                    try:self.assertTrue(check(execute,bb,WORKER))
                    finally:child.terminate();child.wait(timeout=3)
            unrelated=subprocess.Popen(['sh','-c','grep -Fx '+WORKER],executable=str(program))
            try:self.assertFalse(check(execute,bb,WORKER))
            finally:unrelated.terminate();unrelated.wait(timeout=3)
            self.assertFalse(check(execute,bb,WORKER))

    def test_real_timeout_is_not_treated_as_an_idle_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            wrapper=Path(directory)/'busybox';bb=BUSYBOX
            wrapper.write_text('#!/bin/sh\nif [ "$1" = pgrep ]; then exec sleep 30; fi\nexec '+bb+' "$@"\n')
            wrapper.chmod(0o755)
            def execute(command):
                # Some Android su versions return zero after a killed child.
                # Ignore the outer status exactly as those hosts do.
                return subprocess.run(['sh','-c',command],capture_output=True,text=True,timeout=8).stdout
            with self.assertRaisesRegex(ValueError,'Cannot verify'):
                codec().native_worker_active(execute,str(wrapper),WORKER)


if __name__=='__main__':unittest.main()
