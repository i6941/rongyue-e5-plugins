#!/usr/bin/python3
"""Local-only infoscreen bridge. Never return credentials or full profiles."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

RUN = Path('/tmp/run/e5-nikki-control')
INIT = '/etc/init.d/nikki'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ControlError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def command(args, timeout=10):
    # Fixed command paths and argument lists; no shell or credential argv.
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          start_new_session=True) as proc:
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
            raise ControlError('操作超时，请检查网络和 Nikki 日志', 504)
    return proc.returncode, out


def uci(option):
    rc, out = command(['/sbin/uci', '-q', 'get', 'nikki.' + option])
    return out.decode().strip() if rc == 0 else ''


def api(path, body=None):
    # Read existing credentials only here, never expose them to JS or argv.
    secret = uci('mixin.api_secret')
    if not secret:
        raise ControlError('未配置核心 API 密钥', 503)
    listen = uci('mixin.api_listen')
    if listen not in ('192.168.9.1:9090', '127.0.0.1:9090'):
        raise ControlError('核心 API 地址已改变，请先检查配置', 503)
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request('http://' + listen + path, data=data,
                                 headers={'Authorization': 'Bearer ' + secret,
                                          'Content-Type': 'application/json'},
                                 method='GET' if body is None else 'PUT')
    try:
        with OPENER.open(req, timeout=4) as response:
            raw = response.read(2 * 1024 * 1024)
        return json.loads(raw) if raw else {}
    except (OSError, ValueError, urllib.error.URLError):
        raise ControlError('核心 API 不可用，请先启动 Nikki 或检查日志', 503)


def running():
    return command([INIT, 'running'])[0] == 0


def prepare():
    RUN.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(RUN, 0o700)


@contextlib.contextmanager
def locked(wait=False):
    prepare()
    with (RUN / 'operation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            raise ControlError('已有操作正在进行，请稍候', 409)
        yield


def save_job(job):
    prepare()
    fd, path = tempfile.mkstemp(prefix='job-', dir=RUN)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(job, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(path, RUN / 'job.json')
    finally:
        if os.path.exists(path):
            os.unlink(path)


def read_job():
    try:
        return json.loads((RUN / 'job.json').read_text())
    except (OSError, ValueError):
        return None


def active(job):
    if not job or job.get('phase') not in ('queued', 'running'):
        return False
    if time.time() - job.get('started', 0) > 180:
        return False
    try:
        os.kill(job.get('pid', 0), 0)
        return bool(job.get('pid'))
    except (OSError, TypeError):
        return False


def proxy_summary(proxies):
    selectors = [(name, value) for name, value in proxies.items()
                 if value.get('type') == 'Selector' and name != 'GLOBAL']
    if not selectors:
        return None
    chosen = next(((name, value) for name, value in selectors
                   if '节点选择' in name or name.strip().lower() in ('proxy', 'proxies')), selectors[0])
    name, current = chosen
    chain, seen = [], set()
    while name not in seen and len(chain) < 16:
        chain.append(name)
        seen.add(name)
        current = proxies.get(name, {})
        selected = current.get('now')
        if not selected:
            break
        name = selected
    history = current.get('history', [])
    return {'group': chosen[0], 'chain': chain, 'node': chain[-1],
            'delay': history[-1].get('delay') if history else None}


def interface_rates(device):
    prepare()
    try:
        counts = {key: int(Path('/sys/class/net', device, 'statistics', key + '_bytes').read_text())
                  for key in ('rx', 'tx')}
        with (RUN / 'traffic.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                old = json.loads((RUN / 'traffic.json').read_text())
            except (OSError, ValueError):
                old = {}
            sample = dict(counts, device=device, time=time.monotonic())
            fd, temporary = tempfile.mkstemp(prefix='traffic-', dir=RUN)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(sample, stream)
                os.replace(temporary, RUN / 'traffic.json')
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            elapsed = sample['time'] - old.get('time', sample['time'])
            if old.get('device') != device or not 0.3 <= elapsed <= 30:
                return {'rx': None, 'tx': None}
            return {key: max(0, counts[key] - old[key]) / elapsed for key in ('rx', 'tx')}
    except (OSError, ValueError, KeyError):
        return {'rx': None, 'tx': None}


def network_status():
    try:
        rc, out = command(['/sbin/ip', '-json', '-4', 'route', 'show', 'default'], 3)
        routes = json.loads(out) if rc == 0 else []
        routes = [route for route in routes if 'linkdown' not in route.get('flags', [])]
        if not routes:
            return {'connected': False, 'kind': '无上联', 'rates': {'rx': None, 'tx': None}}
        route = min(routes, key=lambda item: item.get('metric', 0))
        device = route['dev']
        result = {'connected': True, 'kind': '其他网络', 'ip': route.get('prefsrc', ''),
                  'gateway': route.get('gateway', ''), 'device': device, 'rates': interface_rates(device)}
        if not result['ip']:
            rc, out = command(['/sbin/ip', '-json', '-4', 'address', 'show', 'dev', device], 3)
            addresses = json.loads(out) if rc == 0 else []
            result['ip'] = next((address['local'] for entry in addresses
                                 for address in entry.get('addr_info', []) if address.get('scope') == 'global'), '')
        if device.startswith('wlan'):
            rc, out = command(['/usr/sbin/iw', 'dev', device, 'link'], 3)
            text = out.decode(errors='replace') if rc == 0 else ''
            ssid = re.search(r'^\s*SSID: (.*)$', text, re.M)
            signal = re.search(r'signal:\s*(-?\d+)', text)
            result.update(kind='Wi-Fi', ssid=ssid.group(1).strip() if ssid else '',
                          signal=int(signal.group(1)) if signal else None)
        else:
            rc, out = command(['/bin/ubus', 'call', 'network.interface.wan', 'status'], 3)
            wan = json.loads(out) if rc == 0 else {}
            if wan.get('up') and wan.get('l3_device') == device and wan.get('proto') == 'modemmanager':
                result['kind'] = '移动网络'
        return result
    except (OSError, ValueError, KeyError, ControlError):
        return {'connected': None, 'kind': '状态暂不可读', 'rates': {'rx': None, 'tx': None}}


def status():
    is_running = running()
    version = ''
    proxy = None
    if is_running:
        try:
            version = api('/version').get('version', '')
            proxy = proxy_summary(api('/proxies').get('proxies', {}))
        except ControlError:
            pass
    job = read_job()
    if job and job['phase'] in ('queued', 'running') and not active(job):
        job = dict(job, phase='failed', error='上次操作已中断，请重试')
    return {'ok': True, 'running': is_running, 'apiReady': bool(version),
            'enabled': uci('config.enabled') == '1', 'version': version, 'job': job,
            'network': network_status(), 'proxy': proxy}


def groups():
    proxies = api('/proxies').get('proxies', {})
    result = []
    for name, group in proxies.items():
        if group.get('type') != 'Selector' or name == 'GLOBAL':
            continue
        choices = []
        for candidate in group.get('all', []):
            node = proxies.get(candidate, {})
            history = node.get('history', [])
            choices.append({'name': candidate, 'type': node.get('type', ''),
                            'delay': history[-1].get('delay') if history else None})
        result.append({'name': name, 'now': group.get('now', ''), 'choices': choices})
    return {'ok': True, 'groups': result}


def select(body):
    group, node = body.get('group'), body.get('node')
    if any(not isinstance(x, str) or not x or len(x) > 512 for x in (group, node)):
        raise ControlError('节点组或节点名称无效')
    with locked():
        if active(read_job()):
            raise ControlError('已有操作正在进行，请稍候', 409)
        proxies = api('/proxies').get('proxies', {})
        current = proxies.get(group, {})
        if group == 'GLOBAL' or current.get('type') != 'Selector' or node not in current.get('all', []):
            raise ControlError('节点已不在该组内，请刷新列表')
        if current.get('now') != node:
            api('/proxies/' + urllib.parse.quote(group, safe=''), {'name': node})
        actual = api('/proxies/' + urllib.parse.quote(group, safe=''))
        if actual.get('now') != node:
            raise ControlError('切换结果未通过回读检查', 502)
    return {'ok': True, 'group': group, 'now': node}


def enqueue(action):
    with locked():
        old = read_job()
        if active(old):
            raise ControlError('已有操作正在进行，请稍候', 409)
        job = {'id': uuid.uuid4().hex, 'action': action, 'phase': 'queued',
               'started': time.time(), 'pid': 0}
        save_job(job)
        try:
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'worker', job['id']],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
            job['pid'] = proc.pid
            save_job(job)
        except OSError:
            save_job(dict(job, phase='failed', error='后台任务无法启动'))
            raise ControlError('后台任务无法启动', 500)
    return {'ok': True, 'job': job}


def check_command(args, timeout=10):
    if command(args, timeout)[0] != 0:
        raise ControlError('操作失败，请查看 Nikki 日志', 502)


def worker(job_id):
    with locked(wait=True):
        job = read_job()
        if not job or job['id'] != job_id:
            return
        job.update(phase='running', pid=os.getpid())
        save_job(job)
        try:
            action = job['action']
            if action == 'update':
                profile = uci('config.profile')
                if not profile.startswith('subscription:'):
                    raise ControlError('当前配置不是订阅，无法更新')
                section = profile.split(':', 1)[1]
                if not section or not all(c.isalnum() or c == '_' for c in section):
                    raise ControlError('订阅配置名称无效')
                check_command([INIT, 'update_subscription', section], 120)
                if uci(section + '.success') != '1':
                    raise ControlError('订阅更新失败，现有缓存已保留', 502)
                # Apply the new subscription only if the user had the service on.
                if uci('config.enabled') == '1':
                    check_command([INIT, 'restart'], 45)
                    api('/version')
            else:
                enabled = '0' if action == 'stop' else '1'
                check_command(['/sbin/uci', 'set', 'nikki.config.enabled=' + enabled])
                check_command(['/sbin/uci', 'commit', 'nikki'])
                if action == 'stop':
                    check_command([INIT, 'stop'], 15)
                    if running():
                        raise ControlError('服务尚未停止，请查看日志', 502)
                else:
                    check_command([INIT, 'enable'])
                    if action == 'restart' or not running():
                        check_command([INIT, action], 45)
                    api('/version')
            job['phase'] = 'done'
        except ControlError as error:
            job.update(phase='failed', error=str(error))
        except Exception:
            job.update(phase='failed', error='操作异常，请查看 Nikki 日志')
        job['finished'] = time.time()
        save_job(job)


def dispatch(action, body):
    if not isinstance(body, dict):
        raise ControlError('请求内容无效')
    if action == 'status':
        return status()
    if action == 'groups':
        return groups()
    if action == 'select':
        return select(body)
    if action == 'update':
        return enqueue('update')
    if action == 'service' and body.get('action') in ('start', 'stop', 'restart'):
        return enqueue(body['action'])
    raise ControlError('不支持的操作')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'worker':
        worker(sys.argv[2])
    else:
        try:
            if len(sys.argv) != 3 or len(sys.argv[2]) > 8192:
                raise ControlError('请求大小或参数无效')
            result = dispatch(sys.argv[1], json.loads(sys.argv[2]))
        except (ValueError, ControlError) as error:
            result = {'ok': False, 'status': getattr(error, 'status', 400),
                      'error': str(error) if isinstance(error, ControlError) else '请求内容无效'}
        except Exception:
            result = {'ok': False, 'status': 500, 'error': '控制程序异常，请检查本机日志'}
        print(json.dumps(result, ensure_ascii=False))
