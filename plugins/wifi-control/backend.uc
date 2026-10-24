'use strict';
import { mkdtemp, open, unlink, rmdir } from 'fs';

return function(ctx) {
    function call(action, body) {
        // Passwords travel in a root-only file, never in a shell argument.
        let dir = mkdtemp('/tmp/e5-wifi-request.XXXXXX');
        if (!dir) return { ok:false, status:500, error:'无法创建请求文件' };
        let path = dir + '/request.json', result = null;
        try {
            let f = open(path, 'wx', 0o600);
            if (f) {
                f.write(sprintf('%J', body ?? {})); f.close();
                let raw = ctx.sh(`/usr/bin/python3 /etc/e5-infoscreen/plugins/wifi-control/control.py ${action} ${path} 2>/dev/null`);
                result = json(raw ?? 'null');
            }
        } catch (_) { result = null; }
        unlink(path); rmdir(dir);
        return result ?? { ok:false, status:500, error:'Wi-Fi 控制程序未返回结果' };
    }
    return {
        'GET /status': () => call('status'),
        'GET /scan': () => call('scan'),
        'POST /connect': req => call('connect', req.body),
        'POST /hotspot': () => call('hotspot'),
        'POST /forget': req => call('forget', req.body),
        'POST /restore': () => call('restore'),
        'POST /restart': () => call('restart')
    };
};
