#!/usr/bin/python3
"""E5 ZeroTier 控制：读状态、加入/离开网络。

设计原则：
- 只操作 ZeroTier 自己的配置（/etc/config/zerotier），不碰路由、防火墙和 Nikki；
- 网络 ID 只做 16 位十六进制校验，不接受其他字符，避免拼命令时被注入；
- 不返回任何密钥。节点身份/私钥由 ZeroTier 自己放在 /var/lib/zerotier-one。
"""
import json
import re
import subprocess
import sys
import time

CONFIG = '/etc/config/zerotier'
CLI = '/usr/bin/zerotier-cli'   # 软链指向 zerotier-one，/usr/sbin 下没有
NETWORK_RE = re.compile(r'^[0-9a-fA-F]{16}$')


class ZtError(Exception):
    def __init__(self, text, status=400):
        super().__init__(text)
        self.status = status


def run(args, timeout=20):
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return 255, ''
    return p.returncode, p.stdout.decode('utf-8', 'replace').strip()


def uci(*args):
    return run(['/sbin/uci'] + list(args))


def enabled():
    code, out = uci('get', 'zerotier.global.enabled')
    return code == 0 and out.strip() == '1'


def info():
    code, out = run([CLI, 'info'], timeout=8)
    if code != 0 or not out:
        return {'online': False, 'address': '', 'version': '', 'detail': out}
    parts = out.split()
    # 200 info <address> <version> <status>
    if len(parts) >= 5 and parts[0] == '200':
        return {'online': parts[4] == 'ONLINE', 'address': parts[2],
                'version': parts[3], 'detail': parts[4]}
    return {'online': False, 'address': '', 'version': '', 'detail': out}


def networks():
    """当前加入的网络；解析 zerotier-cli listnetworks。"""
    code, out = run([CLI, 'listnetworks'], timeout=10)
    result = []
    if code != 0 or not out:
        return result
    for line in out.splitlines()[1:]:      # 第一行是表头
        parts = line.split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        # 200 listnetworks <nwid> <name> <mac> <status> <type> <dev> <ips...>
        result.append({
            'id': parts[2],
            'name': parts[3] if parts[3] != '-' else '',
            'status': parts[5] if len(parts) > 5 else '',
            'device': parts[7] if len(parts) > 7 else '',
            'ips': ' '.join(parts[8:]).split(',') if len(parts) > 8 else [],
        })
    return result


def configured():
    """配置里声明要加入的网络（可能还没连上）。"""
    code, out = uci('show', 'zerotier')
    result = []
    if code != 0:
        return result
    for line in out.splitlines():
        m = re.match(r"zerotier\.(\S+)=network", line)
        if not m:
            continue
        section = m.group(1)
        c, nwid = uci('get', 'zerotier.%s.id' % section)
        if c == 0 and nwid:
            result.append({'section': section, 'id': nwid.strip()})
    return result


def status():
    cfg = configured()
    live = {n['id']: n for n in networks()}
    merged = []
    for item in cfg:
        net = live.get(item['id'], {})
        merged.append({'id': item['id'], 'section': item['section'],
                       'name': net.get('name', ''), 'status': net.get('status', 'REQUESTING_CONFIGURATION'),
                       'device': net.get('device', ''), 'ips': net.get('ips', [])})
    for nwid, net in live.items():
        if nwid not in [m['id'] for m in merged]:
            merged.append({'id': nwid, 'section': '', 'name': net['name'],
                           'status': net['status'], 'device': net['device'], 'ips': net['ips']})
    return {'ok': True, 'enabled': enabled(), 'node': info(),
            'address': info().get('address', ''), 'networks': merged,
            'cli': bool(run([CLI, 'info'], timeout=5)[0] == 0)}


def join(body):
    nwid = str(body.get('id', '')).strip().lower()
    if not NETWORK_RE.match(nwid):
        raise ZtError('网络 ID 必须是 16 位十六进制')
    if not enabled():
        uci('set', 'zerotier.global.enabled=1')
    # 已有同 ID 段就复用，否则新建
    existing = [c for c in configured() if c['id'] == nwid]
    if existing:
        section = existing[0]['section']
    else:
        code, out = uci('add', 'zerotier', 'network')
        if code != 0:
            raise ZtError('无法写入 ZeroTier 配置', 500)
        section = out.strip()
        uci('set', 'zerotier.%s.id=%s' % (section, nwid))
    uci('set', 'zerotier.%s.allow_managed=1' % section)
    uci('commit', 'zerotier')
    run(['/etc/init.d/zerotier', 'restart'], timeout=30)
    time.sleep(3)
    return {'ok': True, 'joined': nwid, 'section': section}


def leave(body):
    nwid = str(body.get('id', '')).strip().lower()
    if not NETWORK_RE.match(nwid):
        raise ZtError('网络 ID 必须是 16 位十六进制')
    for item in configured():
        if item['id'] == nwid:
            uci('delete', 'zerotier.%s' % item['section'])
    uci('commit', 'zerotier')
    run(['/etc/init.d/zerotier', 'restart'], timeout=30)
    time.sleep(3)
    return {'ok': True, 'left': nwid}


def toggle(body):
    """开启/关闭守护进程。关闭后不删网络配置，重新打开会回到原来的网络。"""
    want = body.get('enabled')
    if want is None:
        want = not enabled()
    uci('set', 'zerotier.global.enabled=%d' % (1 if want else 0))
    uci('commit', 'zerotier')
    run(['/etc/init.d/zerotier', 'restart' if want else 'stop'], timeout=30)
    time.sleep(2)
    return {'ok': True, 'enabled': bool(want)}


def dispatch(action, body):
    if not isinstance(body, dict):
        raise ZtError('请求内容无效')
    if action == 'status':
        return status()
    if action == 'join':
        return join(body)
    if action == 'leave':
        return leave(body)
    if action == 'toggle':
        return toggle(body)
    raise ZtError('不支持的操作')


if __name__ == '__main__':
    try:
        if len(sys.argv) != 3:
            raise ZtError('请求参数无效')
        with open(sys.argv[2], 'rb') as f:
            raw = f.read(8192)
        result = dispatch(sys.argv[1], json.loads(raw or b'{}'))
    except (ValueError, ZtError) as error:
        result = {'ok': False, 'status': getattr(error, 'status', 400),
                  'error': str(error) if isinstance(error, ZtError) else '请求内容无效'}
    except Exception:
        result = {'ok': False, 'status': 500, 'error': 'ZeroTier 控制程序异常'}
    print(json.dumps(result, ensure_ascii=False))
