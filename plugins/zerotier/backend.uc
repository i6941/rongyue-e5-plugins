'use strict';
import { mkdtemp, open, unlink, rmdir } from 'fs';

return function(ctx) {
    function call(action, body) {
        // 请求体放 root-only 临时文件，不要经过 shell 参数
        let dir = mkdtemp('/tmp/e5-zt-request.XXXXXX');
        if (!dir) return { ok:false, status:500, error:'无法创建请求文件' };
        let path = dir + '/request.json', result = null;
        try {
            let f = open(path, 'wx', 0o600);
            if (f) {
                f.write(sprintf('%J', body ?? {})); f.close();
                let raw = ctx.sh(`/usr/bin/python3 /etc/e5-infoscreen/plugins/zerotier/control.py ${action} ${path} 2>/dev/null`);
                result = json(raw ?? 'null');
            }
        } catch (_) { result = null; }
        unlink(path); rmdir(dir);
        return result ?? { ok:false, status:500, error:'ZeroTier 控制程序未返回结果' };
    }
    return {
        'GET /status': () => call('status'),
        'POST /join': req => call('join', req.body),
        'POST /leave': req => call('leave', req.body),
        'POST /toggle': req => call('toggle', req.body)
    };
};
