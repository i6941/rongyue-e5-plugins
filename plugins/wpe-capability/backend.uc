'use strict';
import { open } from 'fs';

// 只做一件事：把前端探测结果原样写到 /tmp/wpe-probe.json，供 SSH 侧读取。
// 不执行命令、不读设备信息、不写 /etc。
return function(_ctx) {
    return {
        'POST /save': function(req) {
            let path = '/tmp/wpe-probe.json';
            try {
                let data = sprintf('%J\n', req.body ?? {});
                let f = open(path, 'w', 0o644);
                if (!f) return { ok: false, error: 'cannot open ' + path };
                f.write(data);
                f.close();
                return { ok: true, path: path, bytes: length(data) };
            } catch (e) {
                return { ok: false, error: `${e}` };
            }
        },
        'GET /result': function() {
            let path = '/tmp/wpe-probe.json';
            try {
                let f = open(path, 'r');
                if (!f) return { ok: false, error: 'no result yet' };
                let text = f.read('all');
                f.close();
                return { ok: true, raw: text };
            } catch (e) {
                return { ok: false, error: `${e}` };
            }
        }
    };
};
