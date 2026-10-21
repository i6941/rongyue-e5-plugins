#!/usr/bin/python3
"""E5 Wi-Fi transactions over the existing loopback infoscreen API."""
import base64
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

RUN = Path('/tmp/run/e5-wifi-control')
SAVED = Path('/etc/e5-infoscreen/wifi-control')
CONFIG = Path('/etc/config')
CONFIGS = ('wireless', 'network', 'firewall')


class WifiError(Exception):
    def __init__(self, text, status=400):
        super().__init__(text)
        self.status = status


def command(args, data=None, timeout=10):
    with subprocess.Popen(args, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True) as p:
        try:
            out, _ = p.communicate(data, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.communicate()
            raise WifiError('系统操作超时', 504)
    return p.returncode, out


def checked(args, data=None, timeout=10):
    rc, out = command(args, data, timeout)
    if rc:
        raise WifiError('网络配置操作失败', 502)
    return out


def uci(option):
    rc, out = command(['/sbin/uci', '-q', 'get', option])
    return out.decode().rstrip('\n') if rc == 0 else ''


def json_command(args, timeout=5):
    rc, out = command(args, timeout=timeout)
    return json.loads(out) if rc == 0 else {}


def prepare():
    for path in (RUN, SAVED):
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)


def atomic(path, data, mode=0o600):
    fd, name = tempfile.mkstemp(prefix=path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_json(path, value):
    atomic(path, json.dumps(value, ensure_ascii=False).encode())


def read_json(path, default=None):
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError):
        return default


@contextlib.contextmanager
def lock(wait=False):
    prepare()
    with (RUN / 'operation.lock').open('a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            raise WifiError('已有网络操作正在进行', 409)
        yield


def active(job):
    if not job or job.get('phase') not in ('queued', 'running') or time.time() - job.get('started', 0) > 150:
        return False
    try:
        os.kill(job.get('pid', 0), 0)
        return bool(job.get('pid'))
    except OSError:
        return False


def public_job(job):
    if not job:
        return None
    result = {key: job[key] for key in ('id', 'action', 'phase', 'started', 'finished', 'error', 'rolledBack') if key in job}
    if result['phase'] in ('queued', 'running') and not active(job):
        result.update(phase='failed', error='上次操作中断，可选择恢复上次配置')
    return result


def profiles():
    return read_json(SAVED / 'profiles.json', {})


def status():
    prepare()
    station = uci('wireless.uplink.disabled') != '1' and bool(uci('wireless.uplink.ssid'))
    ap = uci('wireless.default_radio0.disabled') != '1'
    rc, out = command(['/usr/sbin/iw', 'dev', 'wlan0', 'link'], timeout=3)
    text = out.decode(errors='replace') if rc == 0 else ''
    ssid = re.search(r'^\s*SSID: (.*)$', text, re.M)
    signal = re.search(r'signal:\s*(-?\d+)', text)
    interface = json_command(['/bin/ubus', 'call', 'network.interface.wwan', 'status'])
    saved = profiles()
    current_ssid = uci('wireless.uplink.ssid')
    if current_ssid and current_ssid not in saved:
        # Offer existing UCI profile without copying or returning its password.
        saved[current_ssid] = {'band': uci('wireless.radio0.band'), 'encryption': uci('wireless.uplink.encryption')}
    return {'ok': True, 'mode': 'station' if station else 'hotspot' if ap else 'off',
            'ssid': ssid.group(1).strip() if ssid else '',
            'configuredSsid': current_ssid, 'signal': int(signal.group(1)) if signal else None,
            'connected': bool(ssid and interface.get('up')),
            'ip': next((x['address'] for x in interface.get('ipv4-address', [])), ''),
            'hotspotSsid': uci('wireless.default_radio0.ssid'),
            'profiles': [{'ssid': name, 'band': p.get('band', '5g')} for name, p in saved.items()],
            'canRestore': (SAVED / 'previous.json').is_file(),
            'job': public_job(read_json(RUN / 'job.json'))}


def scan():
    result = json_command(['/bin/ubus', 'call', 'iwinfo', 'scan', '{"device":"wlan0"}'], timeout=12)
    if 'results' not in result:
        raise WifiError('扫描失败，请稍后重试或手动添加网络', 502)
    networks = {}
    for row in result['results']:
        ssid = row.get('ssid', '')
        if not ssid:
            continue
        encryption = row.get('encryption', {})
        personal = encryption.get('authentication', [])
        supported = not encryption.get('enabled') or any(kind in personal for kind in ('psk', 'sae'))
        security = 'none' if not encryption.get('enabled') else 'psk2' if 'psk' in personal else 'sae'
        band = '2g' if row.get('band') == 2 or row.get('channel', 100) <= 14 else '5g'
        key = (ssid, band)
        item = {'ssid': ssid, 'band': band, 'signal': row.get('signal'),
                'encryption': security, 'supported': supported}
        if key not in networks or (item['signal'] or -200) > (networks[key]['signal'] or -200):
            networks[key] = item
    return {'ok': True, 'networks': sorted(networks.values(), key=lambda x: x['signal'] or -200, reverse=True)}


def validate(body):
    ssid = body.get('ssid')
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or any(ord(c) < 32 or ord(c) == 127 for c in ssid):
        raise WifiError('Wi-Fi 名称须为1至32字节，不能包含换行')
    if body.get('useSaved'):
        profile = profiles().get(ssid)
        if not profile and ssid == uci('wireless.uplink.ssid'):
            profile = {'password': uci('wireless.uplink.key'), 'encryption': uci('wireless.uplink.encryption'),
                       'band': uci('wireless.radio0.band')}
        if not profile:
            raise WifiError('没有该网络的已保存密码')
        # Keep detected scan metadata while reusing only the saved credential.
        overrides = {key: body[key] for key in ('band', 'encryption') if key in body}
        body = dict(profile, ssid=ssid, **overrides)
    encryption = body.get('encryption', 'psk2')
    password = body.get('password', '')
    band = body.get('band', '5g')
    if encryption not in ('none', 'psk2', 'sae') or band not in ('2g', '5g'):
        raise WifiError('仅支持2.4/5GHz个人网络或开放网络')
    if not isinstance(password, str) or any(ord(c) < 32 or ord(c) > 126 for c in password):
        raise WifiError('密码须为可打印的ASCII字符')
    if encryption != 'none' and not (8 <= len(password) <= 63 or len(password) == 64 and re.fullmatch('[0-9a-fA-F]+', password)):
        raise WifiError('密码须为8至63字符，或64位十六进制密钥')
    return {'ssid': ssid, 'password': password if encryption != 'none' else '', 'encryption': encryption, 'band': band}


def backup():
    for name in CONFIGS:
        if checked(['/sbin/uci', 'changes', name]).strip():
            raise WifiError('网络有未应用的改动，请先在 LuCI 处理', 409)
    value = {name: {'data': base64.b64encode((CONFIG / name).read_bytes()).decode(),
                    'mode': stat.S_IMODE((CONFIG / name).stat().st_mode)} for name in CONFIGS}
    save_json(SAVED / 'previous.json', value)


def restore():
    value = read_json(SAVED / 'previous.json')
    if not value or set(value) != set(CONFIGS):
        raise WifiError('没有可恢复的网络配置')
    for name in CONFIGS:
        command(['/sbin/uci', '-q', 'revert', name])
        atomic(CONFIG / name, base64.b64decode(value[name]['data']), value[name]['mode'])
    reload_network()


def quote(value):
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def batch(settings):
    lines = ['set ' + key + '=' + quote(value) for key, value in settings.items()]
    # Ensure wwan appears once in the existing WAN zone, discovered by name.
    zone = None
    for index in range(16):
        if uci('firewall.@zone[' + str(index) + '].name') == 'wan':
            zone = 'firewall.@zone[' + str(index) + '].network'
            break
    if zone is None:
        raise WifiError('没有找到现有 WAN 防火墙区域')
    if 'wwan' not in uci(zone).split():
        lines.append('add_list ' + zone + "='wwan'")
    lines.extend('commit ' + name for name in CONFIGS)
    checked(['/sbin/uci', 'batch'], ('\n'.join(lines) + '\n').encode())
    os.chmod(CONFIG / 'wireless', 0o600)
    reload_network()


def reload_network():
    checked(['/bin/ubus', 'call', 'network', 'reload'])
    checked(['/sbin/wifi', 'reload'])
    checked(['/etc/init.d/firewall', 'reload'], timeout=15)


def wait_for(profile=None):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if profile:
            current = status()
            if current['connected'] and current['ssid'] == profile['ssid']:
                return
        else:
            wireless = json_command(['/bin/ubus', 'call', 'network.wireless', 'status'])
            if any(radio.get('up') and any(x.get('section') == 'default_radio0'
                   and x.get('config', {}).get('mode') == 'ap' and not x.get('config', {}).get('disabled')
                   for x in radio.get('interfaces', [])) for radio in wireless.values()):
                return
        time.sleep(1)
    raise WifiError('连接未成功或未取得地址，已恢复原网络', 504)


def enqueue(action, body):
    prepare()
    if action == 'connect':
        body = validate(body)
    elif action == 'forget' and body.get('ssid') not in [p['ssid'] for p in status()['profiles']]:
        raise WifiError('没有该已保存网络')
    with lock():
        if active(read_json(RUN / 'job.json')):
            raise WifiError('已有网络操作正在进行', 409)
        job = {'id': uuid.uuid4().hex, 'action': action, 'phase': 'queued', 'started': time.time(),
               'pid': 0, 'payload': body}
        save_json(RUN / 'job.json', job)
        try:
            p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'worker', job['id']],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
            job['pid'] = p.pid
            save_json(RUN / 'job.json', job)
        except OSError:
            job.update(phase='failed', error='后台网络任务无法启动')
            job.pop('payload', None)
            save_json(RUN / 'job.json', job)
            raise WifiError('后台网络任务无法启动', 500)
    return {'ok': True, 'job': public_job(job)}


def worker(job_id):
    with lock(wait=True):
        job = read_json(RUN / 'job.json')
        if not job or job['id'] != job_id:
            return
        job.update(phase='running', pid=os.getpid())
        save_json(RUN / 'job.json', job)
        backed_up = False
        try:
            action, body = job['action'], job['payload']
            if action == 'restore':
                restore()
            elif action == 'forget' and body['ssid'] != uci('wireless.uplink.ssid'):
                saved = profiles()
                saved.pop(body['ssid'], None)
                save_json(SAVED / 'profiles.json', saved)
            else:
                backup()
                backed_up = True
                if action == 'connect':
                    batch({'network.wwan': 'interface', 'network.wwan.proto': 'dhcp', 'network.wwan.metric': '20',
                           'wireless.default_radio0.disabled': '1', 'wireless.radio0.disabled': '0',
                           'wireless.radio0.band': body['band'], 'wireless.radio0.channel': 'auto',
                           'wireless.radio0.htmode': 'HT20' if body['band'] == '2g' else 'VHT80',
                           'wireless.uplink': 'wifi-iface', 'wireless.uplink.device': 'radio0',
                           'wireless.uplink.ifname': 'wlan0', 'wireless.uplink.network': 'wwan',
                           'wireless.uplink.mode': 'sta', 'wireless.uplink.disabled': '0',
                           'wireless.uplink.ssid': body['ssid'], 'wireless.uplink.encryption': body['encryption'],
                           'wireless.uplink.key': body['password']})
                    wait_for(body)
                    saved = profiles()
                    saved[body['ssid']] = body
                    save_json(SAVED / 'profiles.json', saved)
                else:
                    batch({'wireless.uplink.disabled': '1', 'wireless.default_radio0.disabled': '0',
                           'wireless.radio0.disabled': '0', 'wireless.radio0.band': '5g',
                           'wireless.radio0.channel': '149', 'wireless.radio0.htmode': 'VHT80'})
                    wait_for()
                    if action == 'forget':
                        command(['/sbin/uci', '-q', 'delete', 'wireless.uplink.key'])
                        command(['/sbin/uci', '-q', 'delete', 'wireless.uplink.ssid'])
                        checked(['/sbin/uci', 'commit', 'wireless'])
                        saved = profiles()
                        saved.pop(body['ssid'], None)
                        save_json(SAVED / 'profiles.json', saved)
            job['phase'] = 'done'
        except Exception as error:
            job.update(phase='failed', error=str(error) if isinstance(error, WifiError) else '网络操作异常')
            if backed_up:
                try:
                    restore()
                    job.update(rolledBack=True, error='操作失败，已恢复原网络配置')
                except Exception:
                    job.update(rolledBack=False, error='自动恢复失败，请用 USB 管理或重试恢复配置')
        job.pop('payload', None)
        job['finished'] = time.time()
        save_json(RUN / 'job.json', job)


def dispatch(action, body):
    if not isinstance(body, dict):
        raise WifiError('请求内容无效')
    if action == 'status':
        return status()
    if action == 'scan':
        return scan()
    if action in ('connect', 'hotspot', 'restore', 'forget'):
        return enqueue(action, body)
    raise WifiError('不支持的网络操作')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'worker':
        worker(sys.argv[2])
    else:
        try:
            if len(sys.argv) != 3:
                raise WifiError('请求参数无效')
            raw = Path(sys.argv[2]).read_bytes()
            if len(raw) > 8192:
                raise WifiError('请求过大')
            result = dispatch(sys.argv[1], json.loads(raw))
        except (ValueError, WifiError) as error:
            result = {'ok': False, 'status': getattr(error, 'status', 400),
                      'error': str(error) if isinstance(error, WifiError) else '请求内容无效'}
        except Exception:
            result = {'ok': False, 'status': 500, 'error': 'Wi-Fi 控制程序异常'}
        print(json.dumps(result, ensure_ascii=False))
