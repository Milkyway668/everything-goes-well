# -*- coding: utf-8 -*-
"""
把 QQ 邮箱里的求职邮件识别出来，暂存成「待确认清单」，你点头后再写进投递看板。

用法：
  python sync.py scan          只扫描，生成 待确认.json / 待确认.md，不动看板
  python sync.py apply         把待确认清单写进 我的投递记录.json（自动备份）
  python sync.py scan --days 7 只看最近 7 天
  python sync.py scan --all    忽略已处理记录，全部重扫（查错用）
"""
import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta
from email.utils import parseaddr

import mail_core

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "config.json")
STATE = os.path.join(BASE, "state.json")
PENDING = os.path.join(BASE, "待确认.json")
PENDING_MD = os.path.join(BASE, "待确认.md")

# ---------------------------------------------------------------- 词表

# 硬关键词：出现任一，基本可以确定是投递（"附件"太泛，故意不放进来）
APPLY_KW = ["简历", "应聘", "投递", "实习", "申请", "求职", "自荐",
            "个人简历", "管培", "校招", "resume", "cv"]

# 简历类附件才算投递证据
RESUME_FILE_KW = ["简历", "resume", "cv", "个人"]

# 收件箱进度分类：顺序很重要，先匹配到先得
STATUS_RULES = [
    ("rejected", ["未通过", "很遗憾", "遗憾", "不予", "不合适", "未能进入",
                  "未进入", "暂不考虑", "没有通过", "未被录用", "not selected"]),
    # 口头 Offer：还没发正式函，先单独一档
    ("verbal",   [r"口头\s*offer", r"口头录用", r"口头意向", r"口头确认", r"口头承诺",
                  r"口头.{0,4}(?:录取|录用)", r"拟录用", r"预录用"]),
    # "offer" 单独出现太危险（Steam 的 "Special offer"、商场促销都会命中），
    # 必须带求职语境才算
    ("offer",    [r"录用通知", r"录取通知", r"入职通知", r"签约",
                  r"offer\s*(?:letter|函)",
                  r"(?:恭喜|获得|收到|已获|拿到).{0,10}offer",
                  r"(?:已|被|正式).{0,2}录取"]),
    ("hr",       ["hr面", "hr 面", "人力.*面试", "人力资源.*面试"]),
    ("final",    ["终面", "最终面试", "final面", "合伙人面"]),
    ("r2",       ["二面", "复试", "第二轮面试", "第二次面试"]),
    ("written",  ["笔试", "机考", "在线考试", "在线笔试"]),
    ("test",     ["测评", "性格测试", "在线测评", "能力测试", "shl"]),
    ("r1",       ["面试邀请", "面试通知", "面试安排", "面试时间", "初面",
                  "一面", "面试"]),
    ("screening", ["简历筛选", "筛选中", "简历通过", "进入下一轮", "进入流程"]),
    ("submitted", ["已收到您的简历", "投递成功", "简历已收到", "收到您的申请",
                   "已成功投递"]),
]

STATUS_NAME = {
    "pending": "待投递", "submitted": "已投递", "screening": "简历筛选",
    "test": "测评", "written": "笔试", "ai": "AI面试", "r1": "一面",
    "r2": "二面", "final": "终面", "hr": "HR面", "verbal": "口头Offer",
    "offer": "Offer",
    "rejected": "已拒绝", "dropped": "已放弃",
}

# 域名 → 公司（命中就用，作为显示名缺失时的兜底）
DOMAIN_MAP = {
    "htsc.com": "华泰证券", "htlh": "华泰联合证券", "gf.com.cn": "广发证券",
    "gf.com": "广发证券", "citics.com": "中信证券", "citics.com.hk": "中信证券",
    "csc.com.cn": "中信建投", "cicc.com": "中金公司", "gtja.com": "国泰海通",
    "cmschina.com": "招商证券", "htsec.com": "海通证券", "ebscn.com": "光大证券",
    "swhy.com": "申万宏源", "xyzq.com.cn": "兴业证券", "gjzq.com.cn": "国金证券",
    "moonshot.ai": "月之暗面", "moonshot.cn": "月之暗面",
    "efunds.com.cn": "易方达基金", "csfund.com": "华夏基金", "gffund.com": "广发基金",
    "icbc.com.cn": "工商银行", "ccb.com": "建设银行", "abchina.com": "农业银行",
    "boc.cn": "中国银行", "cmbchina.com": "招商银行", "spdb.com.cn": "浦发银行",
    "pingan.com": "中国平安", "tencent.com": "腾讯", "bytedance.com": "字节跳动",
    "alibaba.com": "阿里巴巴", "baidu.com": "百度",
    # 常见互联网/科技公司（仅作正文没写公司名时的兜底）
    "xiaomi.com": "小米", "meituan.com": "美团", "jd.com": "京东",
    "pinduoduo.com": "拼多多", "kuaishou.com": "快手", "xiaohongshu.com": "小红书",
    "huawei.com": "华为", "antgroup.com": "蚂蚁集团", "didiglobal.com": "滴滴",
}

COMPANY_HINT = re.compile(
    r"(公司|证券|基金|银行|保险|信托|集团|资本|投资|资产|科技|咨询|事务所|"
    r"研究院|研究所|中心|大学|有限|控股|私募|公募|互联网)")

INDUSTRY_RULES = [
    ("券商", ["证券", "投行", "券商", "承销", "保荐", "研究所"]),
    ("私募基金", ["私募", "母基金", "风投", "创投", "vc", "pe", "资本", "投资管理"]),
    ("公募基金", ["基金", "公募", "资管", "资产管理"]),
    ("银行", ["银行", "农商", "信用社"]),
    ("保险", ["保险", "人寿", "财险", "平安"]),
    ("信托", ["信托"]),
    ("互联网", ["互联网", "科技", "ai", "人工智能", "字节", "腾讯", "阿里", "百度",
                "美团", "京东", "快手", "小红书", "小米", "华为", "滴滴", "拼多多",
                "网易", "蚂蚁", "月之暗面"]),
    ("咨询", ["咨询", "mbb", "麦肯锡", "贝恩", "波士顿"]),
    ("国企央企", ["集团", "国企", "央企", "国资"]),
]

# 发件人名里常见的前后缀噪声
NOISE = re.compile(r"^(hr|HR|招聘|人力资源|人事|校园招聘|校招|career|recruit|job|"
                   r"zhaopin)[\s\-_：:]*|[\s\-_]*"
                   r"(hr|HR|招聘组|招聘团队|招聘|人力资源部|校园招聘|校招)[\s\-_：:]*$")


# ---------------------------------------------------------------- 工具

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dashboard_path(cfg):
    """看板数据文件位置。支持相对路径：相对「邮箱同步」这一层算，
       这样整个文件夹搬到别人电脑上也不用改配置。"""
    p = cfg.get("dashboard_json") or "../我的投递记录.json"
    p = os.path.expandvars(os.path.expanduser(p))
    if not os.path.isabs(p):
        p = os.path.normpath(os.path.join(BASE, p))
    return p


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)   # 原子替换，写一半断电也不会毁掉原文件


def save_dashboard(path, data):
    """看板数据必须原地覆盖，不能用 os.replace。
       看板页面用 File System Access API 握着这个文件的句柄；
       原子替换会把目录项换成一个新文件，页面手里的句柄还指向旧文件，
       表现就是「脚本改了，看板永远看不到」。写前已经备份过了。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())


def base_domain(addr):
    if "@" not in addr:
        return ""
    d = addr.split("@")[-1].lower()
    parts = d.split(".")
    # hr.gf.com.cn → gf.com.cn；career.moonshot.ai → moonshot.ai
    if len(parts) >= 3 and parts[0] in ("hr", "job", "jobs", "recruit", "career",
                                        "careers", "campus", "talent", "mail",
                                        "email", "zhaopin", "apply"):
        return ".".join(parts[1:])
    return d


def is_free_mail(addr, free_domains):
    d = base_domain(addr)
    return any(d == f or d.endswith("." + f) for f in free_domains)


def clean_company(name):
    n = NOISE.sub("", (name or "").strip())
    n = re.sub(r"[【】\[\]（）()<>\"']", "", n).strip(" -_，,。.")
    return n


# 「看到 鹏华基金-机构业务经理助理 的招聘信息」这种写法：
# 公司名和职位用 - / | 连在一起，后面接「的招聘信息」。
BODY_MIXED_PAT = re.compile(
    r"(?:看到|关注到|了解到|得知|发现)\s*"
    r"([^\n，,。！!；;]{2,60}?)\s*的\s*"
    r"(?:招聘信息|招聘启事|招聘公告|实习信息|岗位信息|职位信息|招聘)")

# 公司名和职位之间的分隔符
ROLE_SEP = re.compile(r"\s*[-—–－|｜/／]\s*")


def split_company_position(raw):
    """把「鹏华基金-机构业务经理助理」拆成 (公司, 职位)。
       最后一段带岗位词就当职位，前面剩下的当公司。拆不开就整串当公司。"""
    raw = (raw or "").strip(' 　“”"\'「」')
    parts = [p.strip() for p in ROLE_SEP.split(raw) if p.strip()]
    if len(parts) >= 2 and JOB_WORD.search(parts[-1]):
        return "".join(parts[:-1]).strip(), parts[-1]
    return raw, ""


def mixed_from_body(body):
    """正文「看到 公司-职位 的招聘信息」写法，返回 (公司, 职位, 依据)。
       这是最贴近真实写信习惯的一条，优先于其他正文规则。"""
    m = BODY_MIXED_PAT.search(body or "")
    if not m:
        return "", "", ""
    comp, pos = split_company_position(m.group(1))
    if not comp or len(comp) < 2:
        return "", pos, ""
    # 整段其实是岗位名（比如「看到 实习生 的招聘信息」），不算公司
    if NOT_COMPANY.match(comp) or JOB_WORD.search(comp):
        return "", pos, ""
    return comp, pos, f"正文「{m.group(0).strip()[:30]}」"


# 正文里显式写公司名的句式。投递信模板：看到小米正在招聘"国际商业营销实习生"……
# 按可信度从高到低试，命中第一个就返回。
BODY_COMPANY_PATS = (
    # ① 标签式：应聘公司：小米 / 公司名称：小米
    re.compile(r"(?:公司名称|应聘公司|投递公司|申请公司|公司)\s*[：:]\s*([^\n，,。；;]{2,24})"),
    # ② 看到/关注到 + 公司名 + 正在招聘（主用写法）
    re.compile(r"(?:看到|关注到|了解到|得知|发现)\s*"
               r"([一-龥A-Za-z0-9（）()·]{2,20}?(?:公司|集团|证券|基金|银行|科技|控股|事务所)?)"
               r"\s*(?:正在|目前|近期|已|在)?\s*(?:招聘|招人|招新|发布|在招)"),
    # ③ 贵司 ＋ 公司名 ＋ 正在招聘（避免把「贵司"岗位"」当成公司）
    re.compile(r"(?:贵司|贵公司|贵单位)\s*"
               r"([一-龥A-Za-z0-9（）()·]{2,20}?(?:公司|集团|证券|基金|银行|科技|控股|事务所)?)"
               r"\s*(?:正在|目前|近期|已|在)?\s*(?:招聘|招人|招新|发布|在招)"),
    # ④ 贵司 ＋ 公司名 ＋ 引号岗位：贵司小米“国际商业营销实习生”
    #    （「贵司"岗位"」里贵司后面直接是引号，捕获不到，不会误判）
    re.compile(r"(?:贵司|贵公司|贵单位)\s*([一-龥A-Za-z0-9（）()·]{2,20}?)\s*[“\"「]"),
)

# 「公司名」位置上一定不是公司名的词
NOT_COMPANY = re.compile(
    r"^(贵司|贵公司|贵单位|该公司|公司|该企业|企业|贵行|贵部|贵院|"
    r"招聘|岗位|职位|实习|实习生|我们|您|你|我|该|本|此|那)$")


def guess_company_from_body(body):
    """正文里显式写的公司名。抓到的候选再用岗位词表和代词表排除，宁缺毋滥。"""
    for pat in BODY_COMPANY_PATS:
        for m in pat.finditer(body or ""):
            cand = clean_company(m.group(1))
            if not (2 <= len(cand) <= 24):
                continue
            if NOT_COMPANY.match(cand) or JOB_WORD.search(cand):
                continue
            return cand, f"正文「{m.group(0).strip()[:30]}」"
    return "", ""


def guess_company(msg, free_domains):
    """从正文显式写法 / 收件人显示名 / 域名推断公司，返回 (公司名, 依据)"""
    # 0) 正文「看到 公司-职位 的招聘信息」——最贴近写信习惯，最先试
    company, _pos, why = mixed_from_body(msg.get("body", ""))
    if company:
        return company, why
    # 0.5) 正文其他显式写法
    company, why = guess_company_from_body(msg.get("body", ""))
    if company:
        return company, why

    cands = []
    for raw in msg["to"]:
        disp, addr = parseaddr(raw)
        cands.append((clean_company(disp), addr.lower()))
    for addr in msg["to_addrs"]:          # 显示名缺失时补上
        if not any(a == addr for _, a in cands):
            cands.append(("", addr))

    # 1) 显示名像公司名
    for disp, addr in cands:
        if disp and not is_free_mail(addr, free_domains) and COMPANY_HINT.search(disp):
            return disp, f"收件人名称「{disp}」"
    # 2) 域名映射
    for disp, addr in cands:
        d = base_domain(addr)
        if d in DOMAIN_MAP:
            return DOMAIN_MAP[d], f"域名 {d}"
        for k, v in DOMAIN_MAP.items():
            if d.endswith("." + k):
                return v, f"域名 {d}"
    # 3) 正文里「贵司/公司 + 引号」提到的名字
    #    注意：投递信模板常写成「贵司"岗位名"的招聘信息」，引号里是岗位不是公司，
    #    所以候选含岗位词/代词时直接放弃，宁可返回空交给人工。
    m = re.search(r"(?:贵司|贵公司|公司)[“\"「]([^”\"」\n]{2,24})[”\"」]", msg["body"])
    if m:
        cand = clean_company(m.group(1))
        if cand and not NOT_COMPANY.match(cand) and not JOB_WORD.search(cand):
            return cand, "正文「贵司…」"

    # 4) 域名主体（只在企业域名上用，且不能是个人姓名样式）
    for disp, addr in cands:
        d = base_domain(addr)
        if d and not is_free_mail(addr, free_domains):
            return d.split(".")[0], f"域名 {d}"

    # 显示名是人名（chanteresa、zhangjingyao 这种）时，宁可不写，也不编一个公司
    return "", ""


POS_PAT = re.compile(
    r"[一-龥A-Za-z0-9/·\-]{2,24}"
    r"(?:实习生|分析师|研究员|管培生|管理培训生|助理|经理|专员|工程师|顾问|"
    r"主管|总监|专员|岗位|岗)")

# 岗位名里总会带一个这类字眼，没有就存疑
JOB_WORD = re.compile(
    r"(实习|分析|研究|投行|管培|助理|经理|专员|工程师|顾问|运营|产品|数据|"
    r"量化|交易|承做|承销|销售|风控|财务|会计|审计|法务|人力|研究|岗)")


def valid_pos(v):
    """挡掉日期、手机号、毕业年份这些被误当岗位的字段"""
    v = v.strip(" 　\"'“”‘’「」【】[]()（）:：-_·")
    if not (2 <= len(v) <= 30):
        return ""
    if re.fullmatch(r"[\d\s\-—–/年月日号:：.]+", v):
        return ""
    if re.search(r"\d{11}", v):
        return ""
    if re.search(r"(毕业|在读|级|届)", v) and not JOB_WORD.search(v):
        return ""
    return v


def guess_position(msg):
    """岗位，按可信度从高到低找：
       ① 正文「贵司"XXX"招聘/岗位」  ② 正文「岗位：XXX」
       ③ 主题【XXX】  ④ 主题里的岗位词  ⑤ 主题横线段落
       都不像就返回空，交给人工，不瞎猜。"""
    body = msg["body"]

    # ⓪ 「看到 鹏华基金-机构业务经理助理 的招聘信息」——公司和职位连写
    _c, pos, _w = mixed_from_body(body)
    if pos:
        v = valid_pos(pos)
        if v:
            return v

    # ① 投递信里最常见的写法
    for pat in (r"[“\"「]([^”\"」\n]{2,30})[”\"」]\s*的?\s*(?:招聘|岗位|职位|实习)",
                r"(?:贵司|贵公司)\s*[“\"「]?([^”\"」，,。\n]{2,24})[”\"」]?\s*的?(?:招聘|岗位)"):
        m = re.search(pat, body)
        if m:
            v = valid_pos(m.group(1))
            if v:
                return v

    # ② 正文「岗位：」
    m = re.search(r"(?:应聘|投递|申请|意向|报名)?\s*(?:岗位|职位)[：:]\s*([^\n，,。;；]{2,30})", body)
    if m:
        v = valid_pos(m.group(1))
        if v:
            return v

    # ③ 主题【基金运营实习生】
    m = re.match(r"\s*[【\[]([^】\]]{2,30})[】\]]", msg["subject"])
    if m:
        v = valid_pos(m.group(1))
        if v and JOB_WORD.search(v):
            return v

    subj = re.sub(r"^\s*[【\[][^】\]]{0,30}[】\]]\s*", "", msg["subject"])
    # ④ 主题里的岗位词
    m = POS_PAT.search(subj)
    if m:
        v = valid_pos(re.sub(r"^(应聘|申请|求职|投递|关于)", "", m.group(0)))
        if v:
            return v

    # ⑤ 「姓名-学校-专业-岗位」命名法：只取确实带岗位字眼的那段
    segs = [s.strip() for s in re.split(r"[-—–_|｜]", subj) if s.strip()]
    for s in reversed(segs):
        v = valid_pos(s)
        if v and JOB_WORD.search(v):
            return v[:30]
    return ""


def kw_hit(kw, text):
    """短英文词按整词匹配，避免 pe 命中 type、ai 命中 email"""
    if kw.isascii() and len(kw) <= 4:
        return re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", text) is not None
    return kw in text


def guess_industry(company, position):
    """行业只看公司名和岗位名，不看正文——正文里提到别家故事会串味"""
    text = f"{company} {position}".lower()
    for ind, kws in INDUSTRY_RULES:
        if any(kw_hit(k.lower(), text) for k in kws):
            return ind
    return "其他"


def has_resume_attach(msg):
    """只有文件名像简历才算；不拿「任意 pdf」当证据（会议材料也是 pdf）"""
    for name, ctype in msg["attachments"]:
        low = name.lower()
        if any(k in low for k in RESUME_FILE_KW):
            return True
    return False


def keyword_hit(text):
    low = text.lower()
    return [k for k in APPLY_KW if k.lower() in low]


# ---------------------------------------------------------------- 发件箱 → 新投递

def classify_sent(msg, cfg):
    """判断一封已发送邮件是不是「投递」，返回 dict 或 None"""
    free = cfg["free_mail_domains"]
    to_all = msg["to_addrs"] + msg["cc_addrs"]
    if not to_all:
        return None

    text = msg["subject"] + "\n" + msg["body"]
    hits = keyword_hit(text)
    resume = has_resume_attach(msg)
    corp_rcpt = [a for a in to_all if not is_free_mail(a, free)]

    # 判定规则（为过滤两类误报收紧过）：
    #   收件人是企业域名 → 标题/正文出现投递词 或 带简历附件，就算
    #   收件人全是个人邮箱 → 要求更硬：主题带投递词、或正文出现"投递/应聘/申请"
    #                       这类明确动作、或带简历附件
    #   （挡住"给同学发消息里随口提一句简历"、"给企业发会议材料"）
    HARD_KW = ("投递", "应聘", "申请", "求职", "个人简历", "resume", "cv", "自荐")
    subj_low = msg["subject"].lower()
    hard_action = any(k in text.lower() for k in HARD_KW)
    hard_subject = any(k in subj_low for k in (
        "简历", "实习", "应聘", "投递", "申请", "求职", "intern", "resume", "cv"))

    if corp_rcpt:
        ok = bool(hits) or resume
    else:
        ok = hard_action or hard_subject or resume
    if not ok:
        return None
    if re.search(r"退订|unsubscribe|自动回复|群发", msg["subject"], re.I):
        return None

    company, why_company = guess_company(msg, free)
    if not company:
        company, why_company = "(待确认)", "收件人域名/名称看不出公司，需手动补"

    position = guess_position(msg) or "(未识别岗位)"
    reasons = []
    if corp_rcpt:
        reasons.append("企业收件人")
    if hits:
        reasons.append("关键词 " + "/".join(hits[:3]))
    if resume:
        reasons.append("简历附件")

    note = (f"【邮箱同步】\n收件人：{', '.join(to_all)}\n"
            f"主题：{msg['subject']}\n依据：{'、'.join(reasons)}")

    return {
        "company": company,
        "position": position,
        "industry": guess_industry(company, position),
        "next": "—",
        "note": note,
        "ddl": "",
        "timeline": [{"s": "submitted", "d": msg["date"], "n": ""}],
        "_source": {
            "folder": msg["folder"], "date": msg["date"],
            "subject": msg["subject"], "to": to_all,
            "message_id": msg["message_id"],
            "company_basis": why_company, "reasons": reasons,
        },
    }


# ---------------------------------------------------------------- 收件箱 → 进度更新

# 这些字样出现在标题里，基本可以断定不是求职邮件（发票、快递、订阅、商店通知…）
NON_JOB_SUBJECT = re.compile(
    r"发票|收据|电子票据|账单|对账单|订单|物流|快递|签收|退款|验证码|"
    r"订阅|续费|到期|优惠|促销|特惠|优惠券|折扣|购物车|购物|支付成功|"
    r"receipt|invoice|order|purchase|subscription|special offer|sale|"
    r"your steam|steam|icloud|apple id|app store|云空间|储存空间|存储空间",
    re.I)

# 标题里出现这些，说明确实是求职邮件，可以盖过上面的排除规则。
# 故意不放 "offer"：它同时是促销广告的高频词（"Special offer"），
# 拿它当豁免理由等于给 Steam 开后门。
JOB_SUBJECT = re.compile(
    r"简历|面试|笔试|测评|录用|录取|投递|应聘|职位|岗位|招聘|"
    r"实习|求职|人才|校招|入职|终面|复试|申请", re.I)


def kw_pattern(kw):
    """短英文词必须整词匹配：shl 不能命中 wi-shl-ist，sale 不能命中 wholesale"""
    if kw.isascii() and len(kw) <= 12:
        return r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])"
    return kw


def classify_inbox(msg):
    """判断是不是求职进度通知，返回 (status, detail) 或 None

    白名单式判断：只认求职关键词，其余一律当没看见。
    Steam 收据、iCloud 存储提醒、电子发票这类根本进不来。"""
    subj = msg["subject"]
    text = (subj + "\n" + msg["body"]).lower()

    # 退订链接 + 标题无求职词 = 营销邮件
    if re.search(r"退订|unsubscribe", text[:3000]) and not JOB_SUBJECT.search(subj):
        return None
    # 标题像消费/系统通知，且没有求职词
    if NON_JOB_SUBJECT.search(subj) and not JOB_SUBJECT.search(subj):
        return None

    for status, kws in STATUS_RULES:
        for kw in kws:
            if re.search(kw_pattern(kw), text[:4000], re.I):
                return status, kw
    return None


def extract_schedule(msg):
    """从面试通知里抽时间、地点、会议链接"""
    text = msg["subject"] + "\n" + msg["body"]
    out = {}
    m = re.search(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})日?\s*(?:[（(][^）)]{0,10}[）)])?\s*"
                  r"(?:上午|下午|晚上)?\s*(\d{1,2})[:：](\d{2})", text)
    if m:
        y, mo, d, hh, mm = m.groups()
        out["date"] = f"{y}-{int(mo):02d}-{int(d):02d}"
        out["time"] = f"{int(hh):02d}:{mm}"
        out["label"] = f"{int(mo)}/{int(d)} {int(hh):02d}:{mm}"
    link = re.search(r"https?://(?:meeting\.tencent\.com|voovmeeting\.com|"
                     r"zoom\.us|meeting\.dingtalk\.com|teams\.microsoft\.com)/\S+",
                     text)
    if link:
        out["link"] = link.group(0).rstrip("）)。，,")
    loc = re.search(r"(?:地\s*点|面试地点|地址)[：:]\s*([^\n]{2,60})", text)
    if loc:
        out["place"] = loc.group(1).strip()
    return out


def match_record(company, records):
    """把邮件里的公司对到看板已有记录上，返回 (record, 分数)"""
    if not company:
        return None, 0
    c = re.sub(r"(有限公司|股份有限公司|集团|股份)", "", company).strip()
    best, best_score = None, 0
    for r in records:
        rc = re.sub(r"(有限公司|股份有限公司|集团|股份)", "", r.get("company", "")).strip()
        if not rc:
            continue
        if c == rc:
            score = 100
        elif len(c) >= 2 and (c in rc or rc in c):
            score = 70 + min(len(c), len(rc))
        else:
            # 共有的中文片段（≥3字）也算弱匹配
            common = set(re.findall(r"[一-龥]{3,}", c)) & \
                     set(re.findall(r"[一-龥]{3,}", rc))
            score = 40 if common else 0
        if score > best_score:
            best, best_score = r, score
    return best, best_score


# ---------------------------------------------------------------- scan / apply

def _squash(s):
    """去掉所有空白，用于判重比较"""
    return re.sub(r"\s", "", s or "")


def build_dedupe_key(company, date, status):
    return "|".join([_squash(company), date or "", status or ""])


def scan(cfg, days=None):
    state = load_json(STATE, {"seen": {}, "last_scan": ""})
    seen = state.get("seen", {})
    lookback = days or cfg.get("lookback_days", 90)
    since = datetime.now() - timedelta(days=lookback)

    M = mail_core.connect(cfg["email"], cfg["auth_code"])
    folders = mail_core.list_folders(M)

    # 待确认(_pending)和已忽略(_ignored)的临时记录不算"看板里已有"，
    # 否则第二轮扫描会把自己的待确认当成重复而跳过，待确认区就空了
    records = [r for r in load_json(dashboard_path(cfg), [])
               if not r.get("_pending") and not r.get("_ignored") and not r.get("_jd")]
    existing_keys = set()          # 公司|日期|状态
    existing_pos = set()           # 岗位|日期 —— 公司没认出来时靠这个认重
    for r in records:
        pos = re.sub(r"\s", "", r.get("position", "")).lower()
        for ev in r.get("timeline", []):
            d = ev.get("d", "")
            existing_keys.add(build_dedupe_key(r.get("company", ""), d, ev.get("s", "")))
            if pos and ev.get("s") == "submitted":
                existing_pos.add(f"{pos}|{d}")

    new_records, updates, unmatched, skipped = [], [], [], []

    # ---- 已发送：新投递
    if cfg.get("scan_sent", True):
        sent = mail_core.pick_folder(folders, "sent")
        if not sent:
            print("⚠ 没找到「已发送」文件夹，跳过发件箱。可用文件夹：",
                  [f[0] for f in folders])
        else:
            for msg in mail_core.fetch_since(M, sent, since):
                key = "sent|" + (msg["message_id"] or f"{msg['folder']}|{msg['uid']}")
                cand = classify_sent(msg, cfg)
                if not cand:
                    continue
                if key in seen:
                    continue
                pos_key = _squash(cand["position"]).lower() + "|" + msg["date"]
                if (build_dedupe_key(cand["company"], msg["date"], "submitted") in existing_keys
                        or pos_key in existing_pos):
                    skipped.append((cand["company"], cand["position"], "看板里已有同日同公司/同岗位记录"))
                    seen[key] = msg["date"]
                    continue
                cand["_source"]["key"] = key
                new_records.append(cand)

    # ---- 收件箱：进度
    if cfg.get("scan_inbox", True):
        inbox = mail_core.pick_folder(folders, "inbox")
        for msg in mail_core.fetch_since(M, inbox, since):
            key = "inbox|" + (msg["message_id"] or f"{msg['folder']}|{msg['uid']}")
            if key in seen:
                continue
            hit = classify_inbox(msg)
            if not hit:
                continue
            status, kw = hit

            # 公司：发件人名 → 域名 → 正文里对看板公司名
            sender = msg["from_name"] or ""
            company = ""
            disp = clean_company(sender)
            if COMPANY_HINT.search(disp) and len(disp) >= 2:
                company = disp
            if not company:
                d = base_domain(msg["from_addr"])
                company = DOMAIN_MAP.get(d, "")
            rec, score = match_record(company, records) if company else (None, 0)
            if score < 40:
                rec, score = match_record(sender, records)
            if score < 40 and not company:
                # 正文里找看板已有的公司名
                for r in records:
                    nm = r.get("company", "")
                    if len(nm) >= 2 and nm in msg["subject"] + msg["body"]:
                        rec, score, company = r, 60, nm
                        break

            sched = extract_schedule(msg) if status in ("r1", "r2", "final", "hr", "ai") else {}
            summary = STATUS_NAME.get(status, status) + "通知"
            note_bits = [f"主题：{msg['subject']}"]
            if kw:
                note_bits.append(f"命中：{kw}")
            if sched.get("time"):
                note_bits.append(f"时间：{sched['label']}")
            if sched.get("place"):
                note_bits.append(f"地点：{sched['place']}")
            if sched.get("link"):
                note_bits.append(f"链接：{sched['link']}")

            item = {
                "status": status,
                "date": msg["date"],
                "note": "；".join(note_bits)[:300],
                "next": (sched.get("label", "") + " " + summary).strip() if sched else "—",
                "ddl": sched.get("date", ""),
                "_source": {
                    "key": key, "folder": msg["folder"], "from": msg["from_addr"],
                    "subject": msg["subject"], "date": msg["date"],
                    "matched_company": rec.get("company") if rec else "",
                    "match_score": score,
                },
            }
            if rec and score >= 40:
                item["target_id"] = rec.get("id")
                item["target_company"] = rec.get("company")
                # 同状态同日期不重复加
                if build_dedupe_key(rec.get("company", ""), msg["date"], status) in existing_keys:
                    skipped.append((rec.get("company"), msg["subject"], "这条进度已在看板中"))
                    seen[key] = msg["date"]
                    continue
                updates.append(item)
            else:
                item["guess_company"] = company or sender
                unmatched.append(item)

    M.logout()

    pending = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "new_records": new_records,
        "updates": updates,
        "unmatched": unmatched,
        "skipped": [{"company": s[0], "detail": s[1], "why": s[2]} for s in skipped],
    }
    save_json(PENDING, pending)
    publish_pending_to_dashboard(cfg, pending, state)

    state["last_scan"] = pending["generated_at"]
    save_json(STATE, state)
    write_pending_md(pending)
    print_summary(pending)
    return pending


PENDING_ID_BASE = 900000      # 待确认记录用大号 id，和正式记录错开


# ---------------------------------------------------------------- JD 留存

def _jd_norm(s):
    s = re.sub(r"\s", "", s or "")
    s = re.sub(r"(有限公司|股份有限公司|集团|股份|公司)$", "", s)
    return s.lower()


def _pos_norm(s):
    """岗位名比较用：去掉「部/组/中心/团队」这类组织词，
    这样「投行部分析师」和「投行分析师」能对上。"""
    s = _jd_norm(s)
    return re.sub(r"(事业部|业务部|项目部|研发部|部门|部|组|中心|团队|室|方向)", "", s)


def match_jd(company, position, jds):
    """按「公司+岗位」在 JD 池里找对应那条；公司对上、岗位任一方为空也算。"""
    c, p = _jd_norm(company), _pos_norm(position)
    if not c:
        return None
    for j in jds:
        jc, jp = _jd_norm(j.get("company")), _pos_norm(j.get("position"))
        if not jc:
            continue
        if jc != c and jc not in c and c not in jc:
            continue
        if not p or not jp:
            return j
        if jp == p or jp in p or p in jp:
            return j
    return None


def jd_note(j):
    url  = f"\n链接：{j['url']}" if j.get("url") else ""
    body = re.sub(r"\s+", " ", j.get("text") or "").strip()
    tail = "…（完整 JD 见「JD 留存」）" if len(body) > 300 else ""
    return f"【JD】{j.get('company')} · {j.get('position')}{url}\n{body[:300]}{tail}"


def attach_jd(rec, jds):
    """新投递落地时把对应 JD 写进备注，并把 JD 标成已投递。"""
    if not jds or "【JD】" in (rec.get("note") or ""):
        return None
    jd = match_jd(rec.get("company"), rec.get("position"), jds)
    if not jd:
        return None
    rec["note"] = (rec["note"] + "\n\n" if rec.get("note") else "") + jd_note(jd)
    jd["linked_id"]  = rec.get("id")
    jd["status"]     = "applied"
    jd["applied_at"] = datetime.now().strftime("%Y-%m-%d")
    return jd


def publish_pending_to_dashboard(cfg, pending, state):
    """把本轮待确认的条目写进看板 JSON，每条带 _pending 标记。
       看板读到后显示在「待确认」区：点确认才转成正式记录，点忽略就丢弃。
       每次扫描先清掉上一轮没处理的 _pending，用本轮结果替换。"""
    path = dashboard_path(cfg)
    try:
        records = load_json(path, [])
    except (ValueError, OSError) as e:
        # 看板正在写文件时可能读到半截，这一轮跳过，下一轮再来
        print(f"⚠ 看板文件暂时读不了，本轮不发布待确认：{e}")
        return
    if not isinstance(records, list):
        return

    seen = state.setdefault("seen", {})
    keep = []
    for r in records:
        if r.get("_ignored"):
            # 看板上点了「忽略」：记进 seen，以后不再提示
            k = (r.get("_source") or {}).get("key")
            if k:
                seen[k] = (r.get("_source") or {}).get("date", "")
            continue
        if r.get("_pending"):
            continue                      # 上一轮未处理，用本轮结果替换
        keep.append(r)

    nid = PENDING_ID_BASE
    for r in pending.get("new_records", []):
        key = r["_source"]["key"]
        if key in seen:
            continue
        nid += 1
        item = {k: v for k, v in r.items() if not k.startswith("_")}
        item.update({"id": nid, "_pending": True, "_kind": "new", "_source": r["_source"]})
        keep.append(item)

    for u in pending.get("updates", []):
        key = u["_source"]["key"]
        if key in seen:
            continue
        nid += 1
        keep.append({
            "id": nid, "_pending": True, "_kind": "update",
            "company": u.get("target_company", ""),
            "position": "", "industry": "", "next": u.get("next", "—"),
            "note": u.get("note", ""), "ddl": u.get("ddl", ""),
            "timeline": [{"s": u["status"], "d": u["date"], "n": u.get("note", "")[:200]}],
            "_target_id": u.get("target_id"), "_status": u["status"],
            "_source": u["_source"],
        })

    save_dashboard(path, keep)


def write_pending_md(p):
    lines = [f"# 邮箱同步待确认　{p['generated_at']}", ""]
    lines.append(f"- 新投递：**{len(p['new_records'])}** 条")
    lines.append(f"- 进度更新：**{len(p['updates'])}** 条")
    lines.append(f"- 未匹配到看板记录：**{len(p['unmatched'])}** 条")
    lines.append(f"- 自动跳过（已存在）：{len(p['skipped'])} 条")
    lines.append("")

    if p["new_records"]:
        lines.append("## 一、新投递（将新建记录）\n")
        for i, r in enumerate(p["new_records"], 1):
            s = r["_source"]
            lines.append(f"**{i}. {r['company']}　{r['position']}**")
            lines.append(f"- 日期：{s['date']}　行业：{r['industry']}")
            lines.append(f"- 收件人：{', '.join(s['to'])}")
            lines.append(f"- 依据：{'、'.join(s['reasons'])}；公司来自{s['company_basis']}")
            lines.append(f"- 主题：{s['subject']}")
            lines.append("")

    if p["updates"]:
        lines.append("## 二、进度更新（追加到已有记录）\n")
        for i, u in enumerate(p["updates"], 1):
            lines.append(f"**{i}. {u['target_company']} → {STATUS_NAME.get(u['status'])}**（{u['date']}）")
            lines.append(f"- {u['note']}")
            lines.append("")

    if p["unmatched"]:
        lines.append("## 三、未匹配（公司对不上看板，不会写入）\n")
        for i, u in enumerate(p["unmatched"], 1):
            lines.append(f"**{i}. {u['guess_company']} · {STATUS_NAME.get(u['status'])}**（{u['date']}）")
            lines.append(f"- {u['note']}")
            lines.append("")

    if p["skipped"]:
        lines.append("## 四、已跳过\n")
        for s in p["skipped"]:
            lines.append(f"- {s['company']}：{s['why']}")
        lines.append("")

    with open(PENDING_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def print_summary(p):
    print("=" * 58)
    print(f"扫描完成 {p['generated_at']}")
    print(f"  新投递      {len(p['new_records'])} 条")
    print(f"  进度更新    {len(p['updates'])} 条")
    print(f"  未匹配      {len(p['unmatched'])} 条")
    print(f"  已跳过      {len(p['skipped'])} 条")
    print("-" * 58)
    for r in p["new_records"]:
        print(f"  [新] {r['company']} / {r['position']}  ({r['_source']['date']})")
    for u in p["updates"]:
        print(f"  [更] {u['target_company']} → {STATUS_NAME.get(u['status'])}  ({u['date']})")
    for u in p["unmatched"]:
        print(f"  [?] {u['guess_company']} · {STATUS_NAME.get(u['status'])}  ({u['date']})")
    print("=" * 58)
    print(f"详情看：{PENDING_MD}")
    print("确认无误后运行：python sync.py apply   （或双击 2_确认写入看板.bat）")


def apply():
    if not os.path.exists(PENDING):
        raise SystemExit("还没有待确认清单，请先运行 scan。")
    p = load_json(PENDING, None)
    cfg = load_json(CONFIG, {})
    path = dashboard_path(cfg)
    raw = load_json(path, [])
    # 待确认的临时记录和已忽略的都不参与这次写入
    ignored_keys = [(r.get("_source") or {}).get("key")
                    for r in raw if r.get("_ignored")]
    jds = [r for r in raw if r.get("_jd")]
    records = [r for r in raw
               if not r.get("_pending") and not r.get("_ignored") and not r.get("_jd")]

    # 备份
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.replace(".json", f".备份_{stamp}.json")
    shutil.copy2(path, backup)

    max_id = max([r.get("id", 0) for r in records] or [0])
    added = 0
    for r in p["new_records"]:
        max_id += 1
        rec = {k: v for k, v in r.items() if not k.startswith("_")}
        rec["id"] = max_id
        attach_jd(rec, jds)          # JD 池里有对应岗位就写进备注
        records.append(rec)
        added += 1

    updated = 0
    by_id = {r.get("id"): r for r in records}
    for u in p["updates"]:
        rec = by_id.get(u.get("target_id"))
        if not rec:
            continue
        ev = {"s": u["status"], "d": u["date"], "n": u["note"][:200]}
        rec.setdefault("timeline", []).append(ev)
        if u.get("next") and u["next"] != "—":
            rec["next"] = u["next"]
        if u.get("ddl"):
            rec["ddl"] = u["ddl"]
        updated += 1

    save_dashboard(path, records + jds)

    # 标记已处理，避免下次重复
    state = load_json(STATE, {"seen": {}, "last_scan": ""})
    seen = state.get("seen", {})
    for k in ignored_keys:
        if k:
            seen[k] = datetime.now().strftime("%Y-%m-%d")
    for r in p["new_records"]:
        seen[r["_source"]["key"]] = r["_source"]["date"]
    for u in p["updates"] + p["unmatched"]:
        seen[u["_source"]["key"]] = u["_source"]["date"]
    save_json(STATE, state)

    os.remove(PENDING)
    if os.path.exists(PENDING_MD):
        os.remove(PENDING_MD)

    print(f"✅ 已写入 {added} 条新记录、{updated} 条进度更新")
    print(f"   改前备份：{backup}")
    print("   打开看板后点一下「继续使用 / 打开已有文件」，数据就会读进来。")


class _Tee:
    """同时写到控制台和日志文件。计划任务用 pythonw 跑时没有控制台，只能靠它留痕。"""
    def __init__(self, fh):
        self.fh = fh

    def write(self, s):
        try:
            self.fh.write(s)
            self.fh.flush()
        except Exception:
            pass
        try:
            sys.__stdout__.write(s)
        except Exception:
            pass

    def flush(self):
        for f in (self.fh,):
            try:
                f.flush()
            except Exception:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["scan", "apply"])
    ap.add_argument("--days", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--log", action="store_true", help="把输出追加到 同步日志.txt")
    a = ap.parse_args()

    cfg = mail_core.load_config(CONFIG)

    if a.log:
        fh = open(os.path.join(BASE, "同步日志.txt"), "a", encoding="utf-8")
        fh.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} 开始 =====\n")
        sys.stdout = _Tee(fh)

    try:
        if a.action == "scan":
            if a.all and os.path.exists(STATE):
                os.rename(STATE, STATE + f".old_{datetime.now():%Y%m%d_%H%M%S}")
            # --all 是查错用的全量重扫，不受日常 lookback_days 限制
            scan(cfg, 365 if a.all else a.days)
        else:
            apply()
    except Exception as e:
        print(f"❌ 出错：{type(e).__name__}: {e}")
        if a.log:
            import traceback
            traceback.print_exc()
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
