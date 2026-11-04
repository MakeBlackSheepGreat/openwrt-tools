"""Installation preflight waits for a readable identity; all transports are fake."""
from copy import deepcopy
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.service import Service, plan_install
from backend.state import Context, Store
from backend.transport import AdbCommandError
from test_state import DEVICE, PACKAGE


class PreflightReconnect(unittest.TestCase):
    def run_flow(self, states, *, family='e5', cancel=False, changed_plan=False, legacy=False):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            service = Service('.', store, io.StringIO())
            device = dict(deepcopy(DEVICE), boot_id='original-boot')
            choices = dict(method='part', size_gib=4)
            package = dict(PACKAGE, adapter=family)
            plan = plan_install(package, device, choices)
            record = store.create(package, device, choices, plan)
            if legacy: record['legacy'] = str(Path(directory)/'legacy.json')
            context = Context(store, record, service.emit)
            context.cancel = cancel
            adapter = Mock(password='')
            adapter.probe.side_effect = states
            adapter.execute.return_value = None
            events = []
            original_stage = context.stage
            def stage(name, status='running', **kwargs):
                events.append((name, status))
                original_stage(name, status, **kwargs)
            context.stage = stage
            def completed(*_): context.stage('complete', 'completed')
            fresh = dict(plan, gap_start=1) if changed_plan else plan
            with patch('backend.service.load_ssh'), patch('backend.service.plan_install', return_value=fresh) as planner, \
                    patch.object(service.stop, 'wait', return_value=False), \
                    patch.object(service, 'wait_openwrt', side_effect=completed):
                service.run(context, adapter)
            return record, adapter, events, planner

    def test_offline_missing_authorization_and_initialization_wait_before_writing(self):
        for family in ('e5', 'mu300'):
            with self.subTest(family=family):
                ready = dict(deepcopy(DEVICE), boot_id='original-boot')
                states = [{'serial': DEVICE['serial'], 'readiness': state} for state in
                          ('android_boot', 'debug_authorization', 'android_setup', 'root_permission')]
                record, adapter, events, planner = self.run_flow(states+[ready], family=family)
                self.assertEqual(record['status'], 'completed', record.get('error'))
                adapter.execute.assert_called_once()
                self.assertEqual(adapter.probe.call_count, 5)
                self.assertIn(('android_boot', 'waiting_device'), events)
                self.assertIn(('debug_authorization', 'waiting_user'), events)
                planner.assert_called_once()

    def test_temporary_adb_errors_wait_and_recover(self):
        record, adapter, events, _ = self.run_flow([
            AdbCommandError('daemon unavailable'), ConnectionError('offline'),
            subprocess.TimeoutExpired('adb', 20), deepcopy(DEVICE)])
        self.assertEqual(record['status'], 'completed', record.get('error'))
        adapter.execute.assert_called_once()
        self.assertEqual(events.count(('android_boot', 'waiting_device')), 3)

    def test_real_identity_slot_or_profile_change_still_blocks_every_write(self):
        for field, value in (('cid', 'c'*32), ('slot', '_b'), ('profile', 'other')):
            with self.subTest(field=field):
                record, adapter, _, planner = self.run_flow([
                    {'readiness': 'android_boot'}, dict(deepcopy(DEVICE), **{field:value})])
                self.assertEqual(record['status'], 'failed')
                self.assertEqual(record['error']['code'], 'recovery_required')
                self.assertIn('slot changed', record['error']['message'])
                adapter.execute.assert_not_called()
                planner.assert_not_called()

    def test_reconnected_disk_geometry_is_replanned(self):
        record, adapter, _, planner = self.run_flow([
            {'readiness': 'android_boot'}, deepcopy(DEVICE)], changed_plan=True)
        self.assertEqual(record['status'], 'failed')
        self.assertIn('Installation plan changed', record['error']['message'])
        planner.assert_called_once()
        adapter.execute.assert_not_called()

    def test_cancel_while_waiting_cannot_start_writes(self):
        record, adapter, _, _ = self.run_flow([], cancel=True)
        self.assertEqual(record['status'], 'cancelled')
        adapter.probe.assert_not_called()
        adapter.execute.assert_not_called()

    def test_legacy_resume_also_rejects_a_real_slot_change(self):
        record, adapter, _, _ = self.run_flow([
            {'readiness': 'android_boot'}, dict(deepcopy(DEVICE), slot='_b')], legacy=True)
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(record['error']['code'], 'recovery_required')
        adapter.execute.assert_not_called()


if __name__ == '__main__': unittest.main()
