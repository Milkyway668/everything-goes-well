# -*- coding: utf-8 -*-
"""离线验证：不连邮箱，用假邮件测识别规则准不准"""
import sys, os, email
from email.message import EmailMessage
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mail_core, sync

CFG = {
    "free_mail_domains": ["qq.com", "foxmail.com", "163.com", "126.com",
                          "gmail.com", "outlook.com", "icloud.com"],
    "dashboard_json": "",
}


def build(frm, to, subject, body, attach=None, date="Fri, 24 Oct 2026 10:00:00 +0800"):
    m = EmailMessage()
    m["From"] = frm
    m["To"] = to
    m["Subject"] = subject
    m["Date"] = date
    m["Message-ID"] = f"<{abs(hash(subject))}@test>"
    m.set_content(body)
    if attach:
        m.add_attachment(b"fake", maintype="application", subtype="pdf", filename=attach)
    raw = m.as_bytes()
    msg = email.message_from_bytes(raw)
    return {
        "folder": "Sent", "uid": "1",
        "message_id": msg["Message-ID"], "date": "2026-10-24",
        "subject": mail_core.dec(msg["Subject"]),
        "from_name": mail_core.dec(email.utils.parseaddr(msg["From"])[0]),
        "from_addr": email.utils.parseaddr(msg["From"])[1].lower(),
        "to": [mail_core.dec(a) for a in msg["To"].split(",") if a.strip()],
        "to_addrs": [email.utils.parseaddr(a)[1].lower() for a in msg["To"].split(",") if a.strip()],
        "cc_addrs": [],
        "body": mail_core.body_text(msg),
        "attachments": mail_core.attachments(msg),
    }


SENT_CASES = [
    ("华泰联合（企业域名+简历附件）",
     "求职者 <me@qq.com>", "华泰联合证券招聘 <htlhhr_internsz@htsc.com>",
     "【华泰联合证券】境内外投行项目实习生招聘",
     "老师您好，附件是我的个人简历，应聘境内外投行项目实习生岗位。", "求职者-简历.pdf", True),

    ("月之暗面直投个人邮箱",
     "求职者 <me@qq.com>", "徐天天 <Xutiantian@moonshot.ai>",
     "应聘金融AI实习生-某大学",
     "您好，想应聘金融ai领域实习生，附件为简历。", "简历.pdf", True),

    ("给同学发闲聊（应拒绝）",
     "求职者 <me@qq.com>", "张三 <zhangsan@qq.com>",
     "明天吃饭吗",
     "简历那事回头再说。", None, False),

    ("企业收件人但只是商务往来（应拒绝）",
     "求职者 <me@qq.com>", "某公司 <contact@somecorp.com>",
     "关于下周会议",
     "附件是会议材料，请查收。", "会议材料.pdf", False),

    ("正文含岗位字段",
     "求职者 <me@qq.com>", "广发证券HR <hr@gf.com.cn>",
     "求职申请",
     "应聘岗位：投行委实习生\n每周可出勤3天。", None, True),
]

INBOX_CASES = [
    ("面试通知（含时间地点）",
     "华泰联合证券 <htlhhr_internsz@htsc.com>", "me@qq.com",
     "【面试通知】境内外投行项目实习生",
     "您好，请于2026年10月30日 14:00参加面试。\n地点：深圳市福田区xx大厦\n腾讯会议：https://meeting.tencent.com/dm/abc123", True),
    ("拒信",
     "广发证券 <hr@gf.com.cn>", "me@qq.com",
     "关于您的求职申请",
     "很遗憾，您本次未能进入下一轮。感谢关注。", True),
    ("笔试通知",
     "华泰证券 <hr@htsc.com>", "me@qq.com",
     "在线笔试通知",
     "请于10月31日 19:00 前完成在线笔试。", True),
    ("中文 Offer 通知",
     "中金公司 <hr@cicc.com>", "me@qq.com",
     "录用通知",
     "恭喜您通过全部面试，现正式向您发出录用通知。", True),

    # —— 以下是应该被挡掉的噪音 ——
    ("营销广告（应拒绝）",
     "某平台 <promo@shop.com>", "me@qq.com",
     "双十一大促，点击退订",
     "全场五折，优惠不容错过。", False),
    ("电子发票",
     "车盈网 <service@email.busboss.net>", "me@qq.com",
     "您收到一张电子发票（发票金额：¥61.00）",
     "附件为您的行程单与电子发票，请查收。", False),
    ("Steam 促销（英文 offer 陷阱）",
     "Steam <noreply@steampowered.com>", "me@qq.com",
     "Special offer this weekend!",
     "Your wishlist games are on sale. Special offer ends soon. 退订", False),
    ("Steam 购买收据",
     "Steam Support <noreply@steampowered.com>", "me@qq.com",
     "Your Steam purchase receipt",
     "Thanks for your purchase. Order summary attached. 退订", False),
    ("iCloud 存储提醒",
     "iCloud <no_reply@email.apple.com>", "me@qq.com",
     "您的 iCloud 储存空间即将用尽",
     "升级您的方案，享受更多存储空间。点击退订", False),
    ("Apple 收据",
     "Apple <no_reply@email.apple.com>", "me@qq.com",
     "Your receipt from Apple",
     "Thanks for your purchase. This is your receipt. 退订", False),
    ("快递签收通知",
     "顺丰速运 <sf-express@sf.com>", "me@qq.com",
     "您的快递已签收",
     "订单号 SF123456，已由本人签收。", False),
    ("招聘相关但被误判的边界：邮件里既有发票又有面试",
     "某公司 <hr@somecorp.com>", "me@qq.com",
     "面试通知（附报销发票要求）",
     "请于10月30日参加面试，差旅发票请保留。", True),
]

print("=" * 70)
print("一、已发送邮件识别")
print("=" * 70)
for name, frm, to, subj, body, att, expect in SENT_CASES:
    msg = build(frm, to, subj, body, att)
    r = sync.classify_sent(msg, CFG)
    got = r is not None
    flag = "✅" if got == expect else "❌"
    print(f"{flag} {name}")
    if r:
        print(f"    → 公司={r['company']!r} 岗位={r['position']!r} 行业={r['industry']!r}")
        print(f"      依据={r['_source']['reasons']} 公司来源={r['_source']['company_basis']}")

print()
print("=" * 70)
print("二、收件箱进度识别")
print("=" * 70)
for name, frm, to, subj, body, expect in INBOX_CASES:
    msg = build(frm, to, subj, body)
    hit = sync.classify_inbox(msg)
    got = hit is not None
    flag = "✅" if got == expect else "❌"
    print(f"{flag} {name} → {hit}")
    if hit and hit[0] in ("r1", "r2", "final", "hr", "ai"):
        print(f"    排期={sync.extract_schedule(msg)}")

print()
print("=" * 70)
print("三、公司匹配（对现有 5 条看板记录）")
print("=" * 70)
records = [
    {"id": 1, "company": "3W Fund Management"},
    {"id": 2, "company": "广发证券"},
    {"id": 3, "company": "月之暗面Kimi"},
    {"id": 4, "company": "广东省粤科母基金"},
    {"id": 5, "company": "华泰联合证券"},
]
for name in ["华泰联合证券", "华泰联合证券招聘", "广发证券", "月之暗面", "粤科母基金", "中信证券"]:
    rec, score = sync.match_record(name, records)
    print(f"  {name:<16} → {rec['company'] if rec else '无'}  (分数 {score})")

print()
print("公司推断测试：")
for to in ["华泰联合证券招聘 <htlhhr_internsz@htsc.com>", "hr@gf.com.cn",
           "徐天天 <Xutiantian@moonshot.ai>", "某公司 <contact@somecorp.com>"]:
    msg = build("me", to, "应聘", "简历")
    print(f"  {to:<45} → {sync.guess_company(msg, CFG['free_mail_domains'])}")
