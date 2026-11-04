"""Device-based removal entry; all devices and transports are simulated."""
import io
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_uninstall as fx
import test_uninstall_evidence as evidence
from backend.service import Service
from backend.state import Cancelled, DeviceLock, RecoveryRequired
from backend.uninstall import prepare, pending_removal, Uninstaller


class DeviceEntry(unittest.TestCase):
    def setUp(self):
        self.case=evidence.NoOriginalRecord();self.case.setUp()
        self.f=self.case.fixture
    def tearDown(self):self.case.tearDown()

    def pending(self, after=True):
        ctx=self.case.plan();r=ctx.record
        r['effects']['uninstall-arm']={'state':'done'};r['status']='failed'
        self.case.store.save(r)
        device={**self.f.device,'serial':'192.168.0.1:5555'}
        if after:
            current=[(ctx.directory/'uninstall'/name).read_bytes() for name in ('after-first','after-last')]
            self.f.adapter.read_gpt=Mock(return_value={'first':current[0],'last':current[1]})
            device.update(existing=False,userdata_bytes=32*fx.GIB)
            device['storage']={**device['storage'],'SIZE':32*fx.GIB//512}
        service=Service('.',self.case.store,io.StringIO());service.package=self.f.package
        return ctx,device,service

    def test_planning_does_not_read_installation_records(self):
        self.case.store.list=Mock(side_effect=AssertionError('installation history dependency'))
        ctx=self.case.plan()
        self.assertIsNone(ctx.record['plan']['source_transaction'])
        self.assertEqual(ctx.record['plan']['layout_source'],'device')

    def test_entry_automatically_finds_progress_and_rebinds_wireless_address(self):
        ctx,device,service=self.pending()
        recovered=pending_removal(service,self.f.adapter,device,bytes(4096))
        self.assertEqual(recovered['id'],ctx.record['id'])
        self.assertEqual(recovered['device']['serial'],device['serial'])
        self.assertTrue(recovered['plan']['continuing_removal'])
        self.assertTrue(recovered['uninstall_recheck'])
        self.assertEqual(len(self.case.store.list()),1)

    def test_normal_plan_command_detects_progress_without_a_record_id(self):
        ctx,device,service=self.pending()
        self.f.adapter.probe=Mock(return_value=device)
        self.f.adb.read=Mock(return_value=bytes(4096))
        service.adapters=lambda *_:self.f.adapter
        result=service.dispatch({'protocol':1,'command':'plan','params':{
            'serial':device['serial'],'choices':{'method':'uninstall'}}})
        self.assertEqual(result['id'],ctx.record['id'])
        self.assertTrue(result['plan']['continuing_removal'])

    def test_stale_checkpoint_does_not_adopt_a_fresh_installation(self):
        _,device,service=self.pending(after=False)
        self.assertIsNone(pending_removal(service,self.f.adapter,device,bytes(4096)))
        header=bytearray(4096);header[44:63]=b'openwrt.uninstall=1 '
        self.assertIsNotNone(pending_removal(service,self.f.adapter,device,bytes(header)))

    def test_foreign_hardware_slot_and_storage_do_not_resume(self):
        _,device,service=self.pending()
        for changed in ({'cid':'0'*32},{'slot':'_b'},{'profile':'other'},
                        {'storage':{**device['storage'],'NODE':'sda4'}}):
            with self.subTest(changed=changed):
                self.assertIsNone(pending_removal(service,self.f.adapter,{**device,**changed},bytes(4096)))

    def test_damaged_checkpoint_cannot_authorize_writes(self):
        ctx,device,service=self.pending()
        (ctx.directory/'uninstall/after-first').write_bytes(b'bad')
        self.assertIsNone(pending_removal(service,self.f.adapter,device,bytes(4096)))
        self.assertFalse(any('of=' in c.args[0] for c in self.f.adb.shell.call_args_list))

    def test_another_installer_owns_the_checkpoint_until_its_write_finishes(self):
        ctx,device,service=self.pending()
        self.f.adapter.read_gpt.reset_mock()
        with DeviceLock(self.case.store.base,device['cid']):
            with self.assertRaises((OSError,RuntimeError)):
                pending_removal(service,self.f.adapter,device,bytes(4096))
        self.f.adapter.read_gpt.assert_not_called()
        self.assertEqual(self.case.store.load(ctx.record['id'])['status'],'failed')

    def test_delayed_root_authorization_waits_without_rearming(self):
        ctx=self.case.plan();worker=Uninstaller(None,ctx,self.f.adapter)
        worker.service=SimpleNamespace(stop=SimpleNamespace(wait=Mock(return_value=False)))
        ready={**self.f.device,'readiness':'ready'}
        with patch.object(worker,'ready',side_effect=[{'readiness':'root_permission'},ready]),\
             patch.object(worker,'layout_state',return_value='before'),\
             patch.object(worker,'arm',side_effect=Cancelled()) as arm:
            with self.assertRaises(Cancelled):worker.run()
        self.assertEqual(worker.service.stop.wait.call_count,1)
        arm.assert_called_once_with(ready)


class NativeRetry(unittest.TestCase):
    def setUp(self):
        self.f=fx.Journal();self.f.setUp();self.addCleanup(self.f.tearDown)

    def worker(self, slot='b'):
        self.f.configure('mu300',slot,gap=True)
        ctx=self.f.plan();r=ctx.record
        r['package']['profile']='u30pro'
        self.f.adapter.package=r['package']
        r.update(uninstall_recheck=True,uninstall_android_sha256='a'*64)
        r['effects']['uninstall-arm']={'state':'done'}
        device={**self.f.device,'boot_id':'returned-android'}
        worker=Uninstaller(None,ctx,self.f.adapter)
        previous={'committed':True,'planned':{name:str(i)*64 for i,name in enumerate(
            ('boot','vendor_boot','init_boot','dtbo'),1)}}
        other='b' if slot=='a' else 'a'
        hashes={'boot_'+slot:'a'*64,**{name+'_'+other:value for name,value in previous['planned'].items()}}
        def shell(command,**kwargs):
            name=command.split('/dev/block/by-name/',1)[1]
            return hashes[name]+'  '+name
        self.f.adb.shell=Mock(side_effect=shell)
        return worker,ctx,device,previous,hashes

    def test_explicit_retry_checks_every_container_and_preserves_original_backups(self):
        for slot in ('a','b'):
            with self.subTest(slot=slot):
                worker,ctx,device,previous,_=self.worker(slot)
                original={p.name:p.read_bytes() for p in (ctx.directory/'uninstall').iterdir() if p.is_file()}
                with patch.object(worker,'layout_state',return_value='before'), \
                        patch('backend.native_boot.native_receipt',return_value=previous), \
                        patch.object(worker,'arm') as arm:
                    self.assertTrue(worker.retry_native_removal(device))
                arm.assert_called_once_with(device)
                self.assertFalse(worker.resume_growth)
                self.assertNotIn('uninstall_recheck',ctx.record)
                self.assertEqual(ctx.record['uninstall_wait_boot_id'],device['boot_id'])
                self.assertEqual(ctx.record['uninstall_retry_linux_sha256'],previous['planned']['boot'])
                self.assertEqual(original,{p.name:p.read_bytes() for p in (ctx.directory/'uninstall').iterdir() if p.is_file()})
                self.assertFalse(any('of=' in call.args[0] for call in self.f.adb.shell.call_args_list))

    def test_changed_android_or_companion_refuses_retry_before_staging(self):
        for changed in ('boot_b','boot_a','vendor_boot_a','init_boot_a','dtbo_a'):
            with self.subTest(changed=changed):
                worker,ctx,device,previous,hashes=self.worker();hashes[changed]='f'*64
                with patch.object(worker,'layout_state',return_value='before'), \
                        patch('backend.native_boot.native_receipt',return_value=previous), \
                        patch.object(worker,'arm') as arm, self.assertRaises(RecoveryRequired):
                    worker.retry_native_removal(device)
                arm.assert_not_called()
                self.assertEqual(ctx.record['effects']['uninstall-arm']['state'],'done')

    def test_missing_or_uncommitted_native_receipt_refuses_retry(self):
        for receipt in (None,{'committed':False}):
            worker,ctx,device,_,_=self.worker()
            with patch.object(worker,'layout_state',return_value='before'), \
                    patch('backend.native_boot.native_receipt',return_value=receipt), \
                    patch.object(worker,'arm') as arm, self.assertRaises(RecoveryRequired):
                worker.retry_native_removal(device)
            arm.assert_not_called()

    def test_other_families_reset_and_completed_layout_never_use_this_retry(self):
        for condition in ('other-family','reset','after'):
            worker,ctx,device,_,_=self.worker()
            if condition=='other-family':self.f.adapter.package={'profile':'mu300-family'}
            if condition=='reset':ctx.record['plan']['wipe']=True
            with patch.object(worker,'layout_state',return_value='after' if condition=='after' else 'before'), \
                    patch('backend.native_boot.native_receipt') as receipt, patch.object(worker,'arm') as arm:
                self.assertFalse(worker.retry_native_removal(device))
            receipt.assert_not_called();arm.assert_not_called()

    def test_a_second_failed_boot_reports_failure_instead_of_rearming_forever(self):
        worker,ctx,device,previous,_=self.worker()
        worker.service=SimpleNamespace(stop=SimpleNamespace(wait=Mock(return_value=False)))
        def armed(_):ctx.record['effects']['uninstall-arm']={'state':'done'}
        with patch.object(worker,'ready',side_effect=[device,{**device,'boot_id':'second-failed-boot'}]), \
                patch.object(worker,'layout_state',return_value='before'), \
                patch('backend.native_boot.native_receipt',return_value=previous), \
                patch.object(worker,'arm',side_effect=armed) as arm, self.assertRaisesRegex(RecoveryRequired,'Android returned'):
            worker.run()
        arm.assert_called_once_with(device)

    def test_retry_write_failure_is_not_swallowed_as_an_expected_disconnect(self):
        worker,ctx,device,previous,_=self.worker()
        worker.service=SimpleNamespace(stop=SimpleNamespace(wait=Mock(return_value=False)))
        with patch.object(worker,'ready',return_value=device), \
                patch.object(worker,'layout_state',return_value='before'), \
                patch('backend.native_boot.native_receipt',return_value=previous), \
                patch.object(worker,'arm',side_effect=ConnectionError('write interrupted')), \
                self.assertRaisesRegex(ConnectionError,'write interrupted'):
            worker.run()
        worker.service.stop.wait.assert_not_called()


if __name__=='__main__':unittest.main()
