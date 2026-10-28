# -*- coding: utf-8 -*-
"""
排查工具：列出邮箱文件夹、统计每封邮件被判成什么。
用法：python debug_scan.py            只看文件夹+收件箱概况
      python debug_scan.py sent 3     看已发送前3封的完整正文
"""
import sys, os, re
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mail_core, sync

cfg = mail_core.load_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"))
M = mail_core.connect(cfg["email"], cfg["auth_code"])
folders = mail_core.list_folders(M)
print("文件夹列表：")
for name, flags in folders:
    try:
        typ, cnt = M.select(f'"{name}"', readonly=True)
        n = cnt[0].decode() if typ == "OK" and cnt and cnt[0] else "?"
    except Exception as e:
        n = f"err {e}"
    print(f"  {name:<28} 共 {n} 封   标志={sorted(flags)}")

sent = mail_core.pick_folder(folders, "sent")
inbox = mail_core.pick_folder(folders, "inbox")
print(f"\n识别到 已发送={sent!r}  收件箱={inbox!r}\n")

since = datetime.now() - timedelta(days=int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "sent" else 120)
target = sent if (len(sys.argv) > 1 and sys.argv[1] == "sent") else inbox
mails = mail_core.fetch_since(M, target, since, max_n=200)
print(f"{target} 里 {since:%Y-%m-%d} 之后共 {len(mails)} 封\n")

for m in mails[: (int(sys.argv[2]) if len(sys.argv) > 2 else 15)]:
    c = sync.classify_sent(m, cfg) if target == sent else sync.classify_inbox(m)
    print("=" * 70)
    print(f"日期 {m['date']}  发件 {m['from_name']} <{m['from_addr']}>")
    print(f"收件 {m['to_addrs']}")
    print(f"主题 {m['subject']}")
    print(f"附件 {[a[0] for a in m['attachments']]}")
    if len(sys.argv) > 1 and sys.argv[1] == "sent" and len(sys.argv) > 2:
        print("--- 正文前 800 字 ---")
        print(m["body"][:800])
        print("--- 判定 ---")
        print(c)
    else:
        print(f"判定 {c}")
M.logout()
