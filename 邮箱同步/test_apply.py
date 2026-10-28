# -*- coding: utf-8 -*-
"""写入逻辑自测：全程在临时目录跑，不碰真实的看板文件"""
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync

tmp = tempfile.mkdtemp(prefix="sync_test_")
dash = os.path.join(tmp, "dash.json")
cfg_p = os.path.join(tmp, "config.json")

records = [
    {"id": 1, "company": "广发证券", "position": "投行委实习生", "industry": "券商",
     "next": "—", "note": "", "ddl": "",
     "timeline": [{"s": "submitted", "d": "2026-10-20", "n": ""}]},
]
with open(dash, "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False)
with open(cfg_p, "w", encoding="utf-8") as f:
    json.dump({"dashboard_json": dash}, f)

sync.CONFIG = cfg_p
sync.STATE = os.path.join(tmp, "state.json")
sync.PENDING = os.path.join(tmp, "pending.json")

pending = {
    "generated_at": "2026-10-26 15:00",
    "new_records": [{
        "company": "华泰联合证券", "position": "境内外投行项目实习生",
        "industry": "券商", "next": "—", "note": "【邮箱同步】", "ddl": "",
        "timeline": [{"s": "submitted", "d": "2026-10-26", "n": ""}],
        "_source": {"key": "sent|abc", "date": "2026-10-26"},
    }],
    "updates": [{
        "target_id": 1, "target_company": "广发证券", "status": "r1",
        "date": "2026-10-30", "note": "主题：面试通知；时间：10/30 14:00",
        "next": "10/30 14:00 一面通知", "ddl": "2026-10-30",
        "_source": {"key": "inbox|xyz", "date": "2026-10-30"},
    }],
    "unmatched": [], "skipped": [],
}
with open(sync.PENDING, "w", encoding="utf-8") as f:
    json.dump(pending, f, ensure_ascii=False)

sync.apply()

with open(dash, encoding="utf-8") as f:
    out = json.load(f)

print("\n写入后看板：")
for r in out:
    print(f"  id={r['id']} {r['company']} / {r['position']}  next={r['next']!r} ddl={r['ddl']!r}")
    print(f"      timeline={[(e['s'], e['d']) for e in r['timeline']]}")

assert len(out) == 2, "应该新增 1 条"
assert out[1]["id"] == 2, "新记录 id 应接在最大 id 之后"
assert out[1]["timeline"][0]["s"] == "submitted"
assert out[0]["timeline"][-1]["s"] == "r1", "进度应追加到原记录"
assert out[0]["ddl"] == "2026-10-30", "ddl 应更新"
assert any(n.startswith("dash.备份_") for n in os.listdir(tmp)), "应生成备份"
assert not os.path.exists(sync.PENDING), "apply 后待确认文件应删除"
print("\n✅ 写入测试全部通过")
