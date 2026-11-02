"""U30 Pro container preparation shared by desktop and Android hosts.

Storage, confirmation and transport stay with the common MU300 adapter.
Only the selected package opts into native boot containers.
"""
import hashlib
import importlib.util
from pathlib import Path
import re
from types import SimpleNamespace

from .resources import resource


def native_receipt(adapter, device, folder_name, canonical):
    """Bind an interrupted native write to verified local evidence."""
    import json
    from .state import RecoveryRequired, sha
    folder = adapter.ctx.directory/folder_name/'backup'
    path = folder/'native-before.json'
    if not path.is_file(): return None
    record = json.loads(path.read_text())
    if not record.get('write_started'): return None
    checks = json.loads((folder/'checksums.json').read_text())
    if (record.get('serial') != device['serial'] or
            record.get('android_slot') != device['slot'].removeprefix('_') or
            record.get('canonical_sha256') != sha(canonical)):
        raise RecoveryRequired('Native boot receipt differs / 原生启动写入记录与当前事务不符')
    for name, expected in record['files'].items():
        if (not re.fullmatch(r'(?:boot|vendor_boot|init_boot|dtbo)_[ab]',name) or
                checks.get(name+'.bin') != expected or sha(folder/(name+'.bin')) != expected):
            raise RecoveryRequired('Native boot backup differs / 原生启动备份校验失败')
    # A crash between atomic record/checksum publication may leave only the
    # JSON receipt checksum stale. Prove the planned cohort from immutable
    # source backups and canonical input instead of trusting that checksum.
    slot=record['android_slot']
    inputs={name:(folder/(name+'_'+slot+'.bin')).read_bytes() for name in ('boot','vendor_boot','init_boot')}
    planned=codec().native_images(canonical.read_bytes(),inputs)
    planned['dtbo']=(folder/('dtbo_'+slot+'.bin')).read_bytes()
    if record.get('planned') != {name:hashlib.sha256(raw).hexdigest() for name,raw in planned.items()}:
        raise RecoveryRequired('Native boot plan differs / 原生启动计划与备份不符')
    return record


def restore_android_companions(adapter, device):
    """Return the inactive native containers to this device's working Android."""
    import json
    from .state import RecoveryRequired, atomic_json, sha
    ctx = adapter.ctx
    folder = ctx.directory/'uninstall/native-final'
    folder.mkdir(parents=True,exist_ok=True)
    record_path = folder/'restore.json'
    android = adapter.legacy.Android(SimpleNamespace(adb=None,serial=device['serial'],probe=False))
    slot = device['slot'].removeprefix('_')
    if android.slot != slot: raise RecoveryRequired('Android slot changed during native restoration')
    other = android.linux
    record = json.loads(record_path.read_text()) if record_path.is_file() else dict(serial=device['serial'],slot=slot,rows=[])
    if record.get('serial') != device['serial'] or record.get('slot') != slot:
        raise RecoveryRequired('Native restoration belongs to another device or slot')
    if len(record['rows']) > 3 or len({r['name'] for r in record['rows']}) != len(record['rows']) or any(r['name'] not in ('vendor_boot','init_boot','dtbo') for r in record['rows']):
        raise RecoveryRequired('Invalid native restoration receipt')
    worker = record.get('worker')
    if worker:
        if not re.fullmatch('/data/local/tmp/mu300-desktop-[a-f0-9]{12}/run.sh',worker):
            raise RecoveryRequired('Invalid native restoration worker')
        if 'NATIVE_BUSY' in android.shell('for f in /proc/[0-9]*/cmdline; do tr "\\000" "\\n" < "$f" 2>/dev/null | grep -Fx '+worker+' && echo NATIVE_BUSY; done; true').split():
            raise RecoveryRequired('Native restoration still running / 原生启动恢复仍在运行，请稍后重试')
    for name in ('vendor_boot','init_boot','dtbo'):
        row = next((r for r in record['rows'] if r['name']==name),None)
        source='/dev/block/by-name/'+name+'_'+slot
        target='/dev/block/by-name/'+name+'_'+other
        source_sha=android.shell('sha256sum '+source).split()[0]
        size=int(android.shell('blockdev --getsize64 '+source).strip())
        if not re.fullmatch('[a-f0-9]{64}',source_sha) or not 4096 <= size <= 256 << 20 or int(android.shell('blockdev --getsize64 '+target)) != size:
            raise RecoveryRequired('Native Android restoration size/identity differs: '+name)
        if row is None:
            for path,part in ((folder/(name+'-android.img'),source),(folder/(name+'-before.img'),target)):
                android.download('dd if='+part+' bs=1048576 2>/dev/null',path,expected_size=size)
                if sha(path) != android.shell('sha256sum '+part).split()[0]:
                    raise RecoveryRequired('Native Android backup readback differs: '+name)
            row=dict(name=name,size=size,source=source_sha,before=sha(folder/(name+'-before.img')))
            record['rows'].append(row);atomic_json(record_path,record)
        if row['size'] != size or row['source'] != source_sha:
            raise RecoveryRequired('Android companion changed after restoration was prepared: '+name)
        for suffix,key in (('android','source'),('before','before')):
            path=folder/(name+'-'+suffix+'.img')
            if path.stat().st_size != size or sha(path) != row[key]:
                raise RecoveryRequired('Native Android restoration backup is damaged: '+name)
            android.push(path,'restore-'+name+'-'+suffix+'.img')
    android.push(adapter.legacy.payload_file(adapter.root,'busybox'),'busybox')
    android.shell('chmod 755 '+android.bb)
    # Persist before starting so a disconnected host can resume the same cohort.
    pending = record.get('started') and not record.get('complete')
    for row in record['rows']:
        actual = android.shell('sha256sum /dev/block/by-name/'+row['name']+'_'+other).split()[0]
        if actual not in (row['before'],row['source']) and not pending:
            raise RecoveryRequired('Inactive Android companion changed outside this restoration')
    record.update(started=True,complete=False,worker=android.p+'/run.sh');atomic_json(record_path,record)
    guards=[];writes=[];restores=[]
    for row in record['rows']:
        name=row['name'];source='/dev/block/by-name/'+name+'_'+slot;target='/dev/block/by-name/'+name+'_'+other
        guards.append('[ "$(sha256sum '+source+' | cut -d" " -f1)" = '+row['source']+' ]')
        guards.append('[ "$(sha256sum "$P/restore-'+name+'-android.img" | cut -d" " -f1)" = '+row['source']+' ]')
        guards.append('[ "$(sha256sum "$P/restore-'+name+'-before.img" | cut -d" " -f1)" = '+row['before']+' ]')
        writes.append('dd if="$P/restore-'+name+'-android.img" of='+target+' bs=1048576 conv=fsync\n[ "$(sha256sum '+target+' | cut -d" " -f1)" = '+row['source']+' ]')
        restores.append('dd if="$P/restore-'+name+'-before.img" of='+target+' bs=1048576 conv=fsync\n[ "$(sha256sum '+target+' | cut -d" " -f1)" = '+row['before']+' ] || echo "NATIVE RESTORE FAILED: '+name+'"')
    script=('set -e\n'+
        '[ "$(getprop ro.boot.slot_suffix)" = _'+slot+' ]\n'+'\n'.join(guards)+
        '\ncommitted=0\nrestore() { rc=$?; trap - EXIT INT TERM; if [ "$committed" != 1 ]; then set +e; '+
        '\n'.join(restores)+'\nfi; exit "$rc"; }\ntrap restore EXIT\ntrap "exit 130" INT\ntrap "exit 143" TERM\n'+
        '\n'.join(writes)+'\ncommitted=1\n'+
        'for name in vendor_boot init_boot dtbo; do rm -f "$P/restore-$name-android.img" "$P/restore-$name-before.img" || :; done\n')
    key='uninstall-native-final'
    if ctx.record['effects'].get(key): ctx.record['effects'].pop(key);ctx.store.save(ctx.record)
    ctx.effect(key,lambda:android.run(script),retry_safe=True)
    record['complete']=True;atomic_json(record_path,record)


def codec():
    spec = importlib.util.spec_from_file_location('openwrt_native_boot', resource('boot.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_ssh(client, execute, read_exact, canonical, linux, directory):
    """Read/check current Linux templates; never write partitions over SSH."""
    if linux not in ('a', 'b'):
        raise ValueError('Native Linux slot is unknown / 原生 Linux 槽位未知')
    directory = Path(directory)
    templates = {}
    rows = []
    for name in ('vendor_boot', 'init_boot'):
        device = '/dev/block/by-name/'+name+'_'+linux
        info = execute(client, 'p=$(readlink -f '+device+'); n=${p##*/}; '
            'cat /sys/class/block/$n/size; sha256sum '+device).split()
        if (len(info) != 3 or not info[0].isdigit() or
                not re.fullmatch('[a-f0-9]{64}', info[1])):
            raise ValueError('Cannot verify native boot partition / 无法校验原生启动分区: '+name)
        size = int(info[0])*512
        if not 4096 <= size <= 256 << 20:
            raise ValueError('Invalid native boot partition capacity / 原生启动分区容量无效')
        raw = read_exact(client, 'dd if='+device+' bs=1048576 2>/dev/null', size)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != info[1]:
            raise ValueError('Native template readback differs / 原生启动模板读取校验失败: '+name)
        path = directory/(name+'-before.img')
        path.write_bytes(raw)
        del raw
        templates[name] = path
        rows.append((name, size, info[1]))
    outputs = codec().native_image_files(canonical, templates, directory/'native', names=templates)
    manifest = directory/'native-boot.tsv'
    text = 'U30PRO-BOOT-V1 '+linux+'\n'
    for name, size, before in rows:
        path = outputs[name]
        if path.stat().st_size != size:
            raise ValueError('Native boot output capacity differs')
        with path.open('rb') as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda:stream.read(1 << 20), b''): digest.update(chunk)
            sha = digest.hexdigest()
        text += f'{name} {size} {before} {sha}\n'
    manifest.write_text(text, encoding='ascii', newline='\n')
    return outputs, manifest


def write_android(adapter, device, image, control, folder_name, **options):
    """Run the packaged native writer with common binary ADB and context."""
    folder = adapter.ctx.directory/folder_name
    android = adapter.legacy.Android(SimpleNamespace(adb=None,serial=device['serial'],probe=False))
    if android.slot != device['slot'].removeprefix('_'):
        raise ValueError('Native Android slot changed / 原生 Android 槽位发生变化')
    for name in ('busybox','android-bootchain.sh'):
        source = adapter.root/'desktop'/name if name == 'android-bootchain.sh' else adapter.legacy.payload_file(adapter.root,name)
        android.push(source,name)
    android.shell('chmod 755 '+android.bb)
    spec=importlib.util.spec_from_file_location('native_writer',adapter.root/'desktop/native_u30pro.py')
    writer=importlib.util.module_from_spec(spec);spec.loader.exec_module(writer)
    writer.flash(android,image.read_bytes(),control,adapter.root,
                 SimpleNamespace(ctx=SimpleNamespace(directory=folder)),**options)
    import json
    return json.loads((folder/'backup/native-before.json').read_text())


def repair_android(adapter, device, info, image):
    """Use the package's native writer, inside the shared confirmed repair."""
    ctx = adapter.ctx
    def operation():
        from .state import RecoveryRequired
        previous = native_receipt(adapter,device,'boot-repair-native',image) or {}
        interrupted = previous.get('write_started') and not previous.get('committed')
        for name, expected in dict(info['native_before'], boot=info['before_sha256']).items():
            path = '/dev/block/by-name/'+name+'_'+info['slot']
            actual = adapter.adb.shell('sha256sum '+path,root=True).split()[0]
            if actual not in (expected, previous.get('planned',{}).get(name)) and not interrupted:
                raise RecoveryRequired('Native boot changed after confirmation / 确认后原生启动分区发生变化')
        if device['slot'].removeprefix('_') != info['android_slot']:
            raise RecoveryRequired('Native boot slot changed after confirmation / 确认后原生启动槽位发生变化')
        # Keep misc unchanged here. The shared trial action commits selection
        # after it verifies the complete repaired native route.
        control=adapter.adb.read('dd if=/dev/block/by-name/misc bs=1 skip=2048 count=32 2>/dev/null')
        write_android(adapter,device,image,control,'boot-repair-native')
        codec().native_inspect_route(adapter.adb.read,lambda command:adapter.adb.shell(command,root=True),info['slot'])
        return 'BOOT-REPAIR-VERIFIED'
    return ctx.effect('boot-repair-write', operation, retry_safe=True)
