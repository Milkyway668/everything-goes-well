# -*- coding: utf-8 -*-
"""
QQ 邮箱 IMAP 读取层。
只做两件事：连上邮箱、把邮件拆成干净的字段。不含任何业务判断。
"""
import imaplib
import ssl
import email
import re
import os
import json
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime

IMAP_HOST = "imap.qq.com"
IMAP_PORT = 993

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def imap_date(d):
    """转成 IMAP 认的 01-Oct-2026 格式（手工拼，避免受系统中文 locale 影响）"""
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"


def dec(raw):
    """解码 =?utf-8?b?...?= 这类邮件头"""
    if not raw:
        return ""
    out = []
    for txt, enc in decode_header(raw):
        if isinstance(txt, bytes):
            for e in (enc, "utf-8", "gb18030"):
                if not e:
                    continue
                try:
                    out.append(txt.decode(e, "strict"))
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            else:
                out.append(txt.decode("utf-8", "replace"))
        else:
            out.append(txt)
    return "".join(out).strip()


def strip_html(html):
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", html)
    html = re.sub(r"<[^>]+>", " ", html)
    html = (html.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return html


def body_text(msg, limit=6000):
    """优先取纯文本，没有就退化成去标签的 HTML"""
    plain, html = [], []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            ctype = part.get_content_type()
            if part.get("Content-Disposition", "").startswith("attachment"):
                continue
            try:
                payload = part.get_payload(decode=True)
            except Exception:
                continue
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, "replace")
            except (LookupError, UnicodeDecodeError):
                text = payload.decode("utf-8", "replace")
            if ctype == "text/plain":
                plain.append(text)
            elif ctype == "text/html":
                html.append(text)
    else:
        payload = msg.get_payload(decode=True) or b""
        charset = msg.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, "replace")
        except (LookupError, UnicodeDecodeError):
            text = payload.decode("utf-8", "replace")
        (html if msg.get_content_type() == "text/html" else plain).append(text)

    text = "\n".join(plain).strip() or strip_html("\n".join(html))
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:limit]


def attachments(msg):
    """返回 [(文件名, content_type)]，只关心名字，不读内容"""
    out = []
    if not msg.is_multipart():
        return out
    for part in msg.walk():
        disp = part.get("Content-Disposition", "")
        if not disp.startswith("attachment"):
            continue
        name = dec(part.get_filename())
        if name:
            out.append((name, part.get_content_type()))
    return out


def connect(email_addr, auth_code):
    """登录 QQ IMAP。QQ 要求先发 ID 命令，否则可能报 Unsafe Login"""
    ctx = ssl.create_default_context()
    M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx)
    try:
        M._simple_command(
            "ID", '("name" "qqmail-sync" "version" "1.0" "vendor" "local")')
        M._untagged_response("OK", [None], "ID")
    except Exception:
        pass  # ID 只是锦上添花，失败了也能继续
    M.login(email_addr, auth_code)
    return M


def list_folders(M):
    """返回 [(名称, 标志集合)]，用来找「已发送」"""
    typ, data = M.list()
    if typ != "OK":
        return []
    folders = []
    for line in data:
        if line is None:
            continue
        s = line.decode("utf-8", "replace") if isinstance(line, bytes) else line
        m = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', s.strip())
        if not m:
            continue
        flags = set(m.group("flags").split())
        name = m.group("name").strip().strip('"')
        folders.append((name, flags))
    return folders


def pick_folder(folders, want):
    """want = 'sent' / 'inbox'。优先按 IMAP 标准标志找，再按名字兜底"""
    if want == "inbox":
        for name, _ in folders:
            if name.upper() == "INBOX":
                return name
        return "INBOX"

    for name, flags in folders:
        if r"\Sent" in flags:
            return name
    for kw in ("Sent Messages", "Sent", "已发送", "已发送邮件", "&XfJT0ZAB-"):
        for name, _ in folders:
            if name.lower() == kw.lower() or kw in name:
                return name
    return None


def fetch_since(M, folder, since_date, max_n=400):
    """取某文件夹 since_date 之后的邮件，最新优先，返回解析好的 dict 列表"""
    typ, _ = M.select(f'"{folder}"', readonly=True)  # readonly：不改已读状态
    if typ != "OK":
        raise RuntimeError(f"无法打开文件夹：{folder}")

    typ, data = M.search(None, "SINCE", imap_date(since_date))
    if typ != "OK":
        return []
    nums = (data[0].split() if data and data[0] else [])
    nums = nums[-max_n:]  # 只取最近的

    out = []
    for num in nums:
        typ, raw = M.fetch(num, "(RFC822)")
        if typ != "OK" or not raw or not isinstance(raw[0], tuple):
            continue
        msg = email.message_from_bytes(raw[0][1])
        try:
            dt = parsedate_to_datetime(msg.get("Date"))
            date = dt.strftime("%Y-%m-%d")
        except Exception:
            date = ""

        out.append({
            "folder": folder,
            "uid": num.decode() if isinstance(num, bytes) else str(num),
            "message_id": (msg.get("Message-ID") or "").strip(),
            "date": date,
            "subject": dec(msg.get("Subject")),
            "from_name": dec(parseaddr(msg.get("From", ""))[0]),
            "from_addr": parseaddr(msg.get("From", ""))[1].lower(),
            "to": [dec(a) for a in (msg.get("To", "") or "").split(",") if a.strip()],
            "to_addrs": [parseaddr(a)[1].lower()
                         for a in (msg.get("To", "") or "").split(",") if a.strip()],
            "cc_addrs": [parseaddr(a)[1].lower()
                         for a in (msg.get("Cc", "") or "").split(",") if a.strip()],
            "body": body_text(msg),
            "attachments": attachments(msg),
        })
    return out


def load_config(path):
    if not os.path.exists(path):
        raise SystemExit(
            "找不到 config.json。\n"
            "请把同目录下的 config.example.json 复制一份、改名为 config.json，\n"
            "再用记事本填上你的 QQ 邮箱地址和 16 位授权码。")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    missing = [k for k in ("email", "auth_code") if not cfg.get(k)
               or "填" in str(cfg.get(k)) or "你的" in str(cfg.get(k))]
    if missing:
        raise SystemExit(
            "config.json 还没填好：" + "、".join(missing) +
            "\n请打开 邮箱同步/config.json 填写 QQ邮箱地址 和 授权码。")
    return cfg
