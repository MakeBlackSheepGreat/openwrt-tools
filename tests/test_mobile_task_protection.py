"""Worker wake ownership survives UI detachment and all coordinator exit paths."""
import sys
from pathlib import Path
import threading
import tempfile
import unittest
from unittest.mock import Mock,call,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mobile/python'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mobile/vendor/adb_shell-0.4.4-py3-none-any.whl'))
from android_host.runtime import Runtime


class MobileTaskProtectionTests(unittest.TestCase):
    def test_runtime_installs_power_callback_on_the_actual_coordinator_worker(self):
        native=Mock(spec=['backendTaskChanged','bindTcpSocket'])
        coordinator=Mock();coordinator.run.return_value='completed'
        with tempfile.TemporaryDirectory() as temp,patch('backend.host.install'), \
                patch('android_host.runtime.Provider'),patch('tempfile.tempdir',None), \
                patch('backend.service.Service',return_value=coordinator):
            Runtime(native,None,temp,temp)
            self.assertEqual(coordinator.run('context','adapter'),'completed')
            self.assertEqual(native.backendTaskChanged.call_args_list,[call(True),call(False)])

    def runtime(self,worker):
        runtime=Runtime.__new__(Runtime)
        runtime.native=Mock(spec=['backendTaskChanged'])
        runtime._run_worker=worker
        return runtime

    def test_protection_outlives_terminal_event_until_cleanup_finishes(self):
        cleaning=threading.Event();finish=threading.Event();states=[]
        def worker():
            # The terminal event is already emitted, but a device lock is still held.
            cleaning.set()
            if not finish.wait(5):raise TimeoutError('test cleanup was not released')
        runtime=self.runtime(worker)
        runtime.native.backendTaskChanged.side_effect=states.append
        thread=threading.Thread(target=runtime.run_worker)
        thread.start()
        try:
            self.assertTrue(cleaning.wait(5))
            self.assertEqual(states,[True])
        finally:finish.set();thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(states,[True,False])

    def test_success_safe_pause_failure_and_cancellation_all_release(self):
        # Cancellation inherits BaseException in some host paths; finally must cover it too.
        class Cancel(BaseException):pass
        for result in ('completed','decision-required',RuntimeError('failed'),Cancel()):
            with self.subTest(result=result):
                def worker(context,adapter):
                    self.assertEqual((context,adapter),('context','adapter'))
                    if isinstance(result,BaseException):raise result
                    return result
                runtime=self.runtime(worker)
                if isinstance(result,BaseException):
                    with self.assertRaises(type(result)):runtime.run_worker('context',adapter='adapter')
                else:self.assertEqual(runtime.run_worker('context',adapter='adapter'),result)
                self.assertEqual(runtime.native.backendTaskChanged.call_args_list,
                                 [call(True),call(False)])
