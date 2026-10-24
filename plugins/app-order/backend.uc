'use strict';
/* 应用排序：读每个插件 manifest.json 的 order，交换后写回。
   不碰其它字段，也没有登录态，纯本地文件操作。 */
import { open, readfile, lsdir } from 'fs';

return function (ctx) {
    const DIR = '/etc/e5-infoscreen/plugins';

    function manifest_path(id) {
        return DIR + '/' + id + '/manifest.json';
    }

    function load_all() {
        let out = [];
        let names = lsdir(DIR) ?? [];
        for (let name in names) {
            let id = `${name}`;
            let raw = '';
            try { raw = readfile(manifest_path(id)) ?? ''; } catch (e) { continue; }
            if (length(raw) < 2) continue;
            let m = null;
            try { m = json(raw); } catch (e) { continue; }
            if (!m) continue;
            let nm = m.name;
            if (type(nm) == 'object') nm = nm.zh ?? nm.en ?? id;
            push(out, { id: id, name: `${nm ?? id}`, order: +(m.order ?? 50) });
        }
        sort(out, function (a, b) { return (a.order - b.order) || (a.id < b.id ? -1 : 1); });
        return out;
    }

    function save_order(id, order) {
        let p = manifest_path(id);
        let m = null;
        try { m = json(readfile(p) ?? ''); } catch (e) { return false; }
        if (!m) return false;
        m.order = order;
        let f = open(p, 'w', 0o644);
        if (!f) return false;
        f.write(sprintf('%J\n', m));
        f.close();
        return true;
    }

    return {
        'GET /list': function () {
            return { ok: true, list: load_all() };
        },
        'POST /move': function (req) {
            let b = req.body ?? {};
            let id = `${b.id ?? ''}`;
            let dir = `${b.dir ?? ''}`;
            if (length(id) < 1 || (dir !== 'up' && dir !== 'down'))
                return { ok: false, error: '参数不对' };
            let list = load_all();
            let idx = -1;
            for (let i = 0; i < length(list); i++)
                if (list[i].id === id) { idx = i; break; }
            if (idx < 0) return { ok: false, error: '找不到这个插件' };
            let j = dir === 'up' ? idx - 1 : idx + 1;
            if (j < 0 || j >= length(list)) return { ok: true, moved: false };
            let a = list[idx], c = list[j];
            /* 两个 order 相同时交换没有意义，按位置重新编号 */
            let oa = a.order, oc = c.order;
            if (oa === oc) { oa = (idx + 1) * 10; oc = (j + 1) * 10; }
            let r1 = save_order(a.id, oc);
            let r2 = save_order(c.id, oa);
            return { ok: r1 && r2, moved: r1 && r2 };
        }
    };
};
