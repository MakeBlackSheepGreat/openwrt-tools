"""Isolated real rpcd/ubus registration; explicitly selected ARM64 test image."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get('OPENWRT_OTA_RPCD_TEST_IMAGE')


@unittest.skipUnless(os.name == 'posix' and IMAGE, 'select an existing OpenWrt Docker test image')
class Registration(unittest.TestCase):
    def test_registration_survives_unavailable_python_and_real_hup(self):
        proxy = ROOT/'runtime/luci-app-unisoc-ota/root/usr/lib/unisoc-ota/proxy.sh'
        script = r'''
set -eu
mkdir -p /tmp/bin /var/run/ubus
cat > /tmp/bin/python3 <<'PYTHON'
#!/bin/sh
# Deliberately unavailable for plugin enumeration; status is a harmless fixture.
[ "$1" = /usr/lib/unisoc-ota/rpc.py ] || exit 1
shift
if [ "$1" = call ] && [ "$2" = status ]; then
    printf '%s\n' '{"identity":{"version":"fixture"}}'
    exit 0
fi
exit 1
PYTHON
chmod 755 /tmp/bin/python3
export PATH=/tmp/bin:/usr/sbin:/usr/bin:/sbin:/bin
cat > /usr/libexec/rpcd/unisoc-ota <<'LEGACY'
#!/bin/sh
exec python3 /usr/lib/unisoc-ota/rpc.py "$@"
LEGACY
chmod 755 /usr/libexec/rpcd/unisoc-ota
/sbin/ubusd -s /tmp/ota-test.sock & bus=$!
rpc=''
trap 'kill ${rpc:-} "$bus" 2>/dev/null || true' EXIT
for attempt in $(seq 1 10); do [ ! -S /tmp/ota-test.sock ] || break; sleep 1; done
/sbin/rpcd -s /tmp/ota-test.sock -t 5 & rpc=$!
ready() {
    for attempt in $(seq 1 10); do
        if ubus -s /tmp/ota-test.sock -t 1 call session list '{}' >/dev/null 2>&1; then return 0; fi
        sleep 1
    done
    return 1
}
ready
if ubus -s /tmp/ota-test.sock list unisoc-ota | grep -q unisoc-ota; then
    echo 'Legacy fixture unexpectedly registered without its interpreter' >&2
    exit 1
fi
cat > /usr/libexec/rpcd/unisoc-ota <<'FIXED'
#!/bin/sh
exec /bin/sh /diag/proxy.sh "$@"
FIXED
/usr/libexec/rpcd/unisoc-ota list
kill -HUP "$rpc"
for attempt in $(seq 1 10); do
    if ubus -s /tmp/ota-test.sock -t 1 call unisoc-ota status | grep -q fixture; then break; fi
    sleep 1
done
if ! ubus -s /tmp/ota-test.sock -t 1 call unisoc-ota status | grep -q fixture; then ps; exit 1; fi
before=$(ubus -s /tmp/ota-test.sock -v list unisoc-ota | head -n 1)
kill -HUP "$rpc"
for attempt in $(seq 1 10); do
    after=$(ubus -s /tmp/ota-test.sock -v list unisoc-ota | head -n 1)
    if [ -n "$after" ] && [ "$before" != "$after" ]; then break; fi
    sleep 1
done
[ -n "$after" ] && [ "$before" != "$after" ]
ubus -s /tmp/ota-test.sock -t 1 call unisoc-ota status | grep -q fixture
printf '%s\n' 'PASS real rpcd: lightweight registration and fresh object after SIGHUP'
'''
        result = subprocess.run([
            'docker', 'run', '--rm', '--network', 'none', '--platform', 'linux/arm64',
            '--tmpfs', '/tmp:exec,mode=1777', '--tmpfs', '/usr/libexec/rpcd:exec,mode=755',
            '--mount', 'type=bind,src='+str(proxy)+',dst=/diag/proxy.sh,readonly',
            '--entrypoint', '/bin/sh', IMAGE, '-ec', script,
        ], capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('PASS real rpcd', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
