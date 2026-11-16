# -*- coding: utf-8 -*-
"""本地投递邮件助手：粘贴 JD → DeepSeek 生成主题和正文 → 预览确认 → QQ 邮箱发送。

只在本机 127.0.0.1 运行，API Key 和邮箱授权码都只从本地 config.json 读取。
"""
import imaplib
import json
import os
import re
import smtplib
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "config.json")
INDEX = os.path.join(BASE, "index.html")
HOST, PORT = "127.0.0.1", 8766


class AppError(Exception):
    pass


def origin_allowed(origin):
    """只允许本机看板和 GitHub Pages 调用，防止别的网站偷偷用你的邮箱发信。"""
    if not origin or origin == "null":          # file:// 打开
        return True
    if origin in (
        "http://127.0.0.1:8766", "http://localhost:8766",
        "http://127.0.0.1:8765", "http://localhost:8765",
        "https://milkyway668.github.io",
    ):
        return True
    return False


def load_json(path, default):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_config():
    return load_json(CONFIG, {})


def deepseek_generate(jd, company="", position=""):
    cfg = get_config()
    ds = cfg.get("deepseek", {})
    key = (ds.get("api_key") or "").strip()
    if not key:
        raise AppError("还没有填 DeepSeek API Key。请打开 邮件助手/config.json，把 deepseek.api_key 填上后重试。")
    if not jd.strip():
        raise AppError("JD 不能为空。")

    profile = cfg.get("profile", {})
    system = (
        "你是一名严谨的中文求职邮件助手。根据候选人资料和 JD，写一封可以直接发送的求职邮件。\n"
        "硬性要求：\n"
        "1. 只能使用候选人资料里的事实，绝对不要编造经历、数字、证书、联系方式。\n"
        "2. 根据 JD 的关键要求调整经历顺序和措辞，最相关的放前面，但不要改变事实。\n"
        "3. 只输出严格 JSON，不要 markdown、不要解释，格式：\n"
        '{"company":"","position":"","email":"","subject":"","resume_filename":"","body_middle":""}\n'
        "4. company/position 优先逐字使用用户提供的 jd_company / jd_position，不要改写；"
        "如果为空，再从 JD 提取。email 从 JD 里提取投递邮箱，找不到就留空字符串。\n"
        "4.1 先仔细扫描 JD 里有没有明确的命名规则，关键词包括：简历命名、附件命名、文件命名、"
        "邮件主题、邮件命名、命名为、命名格式、格式为。\n"
        "4.2 如果 JD 明确规定了邮件主题或简历文件名的格式（例如「姓名-学校-专业-岗位」），"
        "必须严格按 JD 给出的字段顺序、字段数量和分隔符生成，只把占位词替换成候选人的真实信息，"
        "不得自创顺序、增删字段或换分隔符。\n"
        "4.3 占位词映射：姓名→name，学校→school，专业→major，学历/年级→degree 或 year，"
        "毕业时间→grad，岗位→position，公司→company，实习时长/可实习时间→availability，"
        "每周天数/到岗时间→availability 中对应部分，地点/城市→location。\n"
        "4.4 如果 JD 没有写命名规则：subject 以 position 原文开头，可参考「岗位-姓名-学校专业-毕业时间-"
        "实习时长-每周天数-到岗时间-地点」；resume_filename 与 subject 保持一致。\n"
        "4.5 resume_filename 不要带 .pdf 后缀，不要包含 / \\ : * ? \" < > | 这些字符。\n"
        "5. subject 不超过 60 个字符，突出岗位和最匹配的 1-2 个点。\n"
        "6. body_middle 只写中间的经历段落，用纯文本，段落之间空一行；按 JD 相关性排列经历。"
        "不要写「您好」、自我介绍、「看到…招聘信息」、简历见附件、感谢等开头/结尾，"
        "首尾由程序用固定模板拼接。不要写「此致」。\n"
        "7. 不要使用夸张形容词，不要写候选人没有提供的信息。"
    )
    user = json.dumps({
        "candidate": profile,
        "jd": jd[:12000],
        "jd_company": (company or "").strip(),
        "jd_position": (position or "").strip(),
    }, ensure_ascii=False)

    payload = {
        "model": ds.get("model") or "deepseek-flash",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 6000,
        "response_format": {"type": "json_object"},
    }
    url = (ds.get("base_url") or "https://api.deepseek.com").rstrip("/") + "/chat/completions"

    def call(body):
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            # 部分兼容接口不支持 response_format，退回普通模式再试一次
            if e.code == 400 and "response_format" in body:
                body.pop("response_format", None)
                return call(body)
            raise AppError(f"DeepSeek 接口返回 {e.code}：{detail}")
        except urllib.error.URLError as e:
            raise AppError(f"连不上 DeepSeek：{e.reason}")

    data = call(payload)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AppError("DeepSeek 返回格式异常：" + json.dumps(data, ensure_ascii=False)[:300])

    if not (content or "").strip():
        msg = data["choices"][0].get("message", {})
        raise AppError(
            "模型没有返回正文（finish_reason=%s，推理长度=%s）。请重试一次。"
            % (data["choices"][0].get("finish_reason"), len(msg.get("reasoning_content") or ""))
        )
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        raise AppError("模型没有返回 JSON：" + content[:300])
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        raise AppError("模型返回的 JSON 解析失败：" + content[:300])

    for k in ("company", "position", "email", "subject", "resume_filename", "body_middle"):
        out.setdefault(k, "")
    out["email"] = (out.get("email") or "").strip()

    # 首尾用 config 里的固定模板，模型只负责中间经历
    tpl = cfg.get("email_template", {}) or {}
    vals = {
        "company":  out.get("company") or "贵公司",
        "position": out.get("position") or "该岗位",
        "name":     profile.get("name", ""),
        "school":   profile.get("school", ""),
        "degree":   profile.get("degree", ""),
        "undergrad": profile.get("undergrad", ""),
        "grad":     profile.get("grad", ""),
        "base":     profile.get("location") or profile.get("base", ""),
        "availability": profile.get("availability", ""),
    }

    def fill(t):
        for k, v in vals.items():
            t = t.replace("{" + k + "}", str(v))
        return t.strip()

    opening = fill(tpl.get("opening", ""))
    closing = fill(tpl.get("closing", ""))
    if not opening:
        opening = "您好！\n\n我是%s%s的同学%s，希望申请%s%s。\n\n以下是我与该职位相关的经历介绍：" % (
            vals["school"], vals["degree"], vals["name"], vals["company"], vals["position"])
    if not closing:
        closing = "简历见附件，期待有机会进一步交流。感谢您的时间，祝您生活愉快！"
    middle = (out.get("body_middle") or "").strip()
    if not middle:
        middle = (out.get("body") or "").strip()
    out["body"] = "\n\n".join(x for x in (opening, middle, closing) if x)
    return out


def attachment_filename(name, subject):
    """优先用模型按 JD 命名规则生成的文件名；没有才退回邮件主题。
       去掉 Windows/邮箱不允许的字符并限长。"""
    raw = (name or "").strip()
    if raw.lower().endswith(".pdf"):
        raw = raw[:-4]
    if not raw:
        raw = subject or ""
    raw = re.sub(r'[\\/:*?"<>|\r\n\t]+', ' ', raw)
    raw = re.sub(r'\s+', ' ', raw).strip(' .')
    if not raw:
        raw = '简历'
    return raw[:80].rstrip(' .') + '.pdf'


def append_to_sent(sender, auth_code, raw):
    """SMTP 发信后不会自动进 QQ「已发送」，用 IMAP 把同一封追加进去。"""
    try:
        import mail_core
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(BASE), "邮箱同步"))
        import mail_core

    M = None
    try:
        M = mail_core.connect(sender, auth_code)
        folders = mail_core.list_folders(M)
        sent = mail_core.pick_folder(folders, "sent")
        if not sent:
            return False, "没找到「已发送」文件夹"
        typ, resp = M.append(
            f'"{sent}"', "\\Seen",
            imaplib.Time2Internaldate(time.time()), raw,
        )
        if typ != "OK":
            return False, str(resp)
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        if M:
            try:
                M.logout()
            except Exception:
                pass


def send_mail(to, subject, body, confirm, filename=""):
    if confirm is not True:
        raise AppError("发送前必须勾选「我已核对」。")
    to = (to or "").strip()
    if not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[A-Za-z]{2,}", to):
        raise AppError("收件邮箱格式不对，或一次填了多个地址。")
    if not subject.strip():
        raise AppError("主题不能为空。")
    if not body.strip():
        raise AppError("正文不能为空。")
    if len(subject) > 200 or len(body) > 20000:
        raise AppError("主题或正文过长。")

    cfg = get_config()
    mail_ref = cfg.get("mail", {}).get("config_path", "../邮箱同步/config.json")
    mail_path = mail_ref if os.path.isabs(mail_ref) else os.path.normpath(os.path.join(BASE, mail_ref))
    mail_cfg = load_json(mail_path, {})
    sender = (mail_cfg.get("email") or "").strip()
    auth_code = (mail_cfg.get("auth_code") or "").strip()
    if not sender or not auth_code:
        raise AppError("读取不到发件邮箱或授权码，请检查 " + mail_path)

    resume = os.path.expanduser(cfg.get("resume_path", ""))
    if not os.path.isfile(resume):
        raise AppError("简历附件不存在：" + resume)

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject.strip()
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(body.strip())
    with open(resume, "rb") as f:
        msg.add_attachment(
            f.read(), maintype="application", subtype="pdf",
            filename=attachment_filename(filename, subject),
        )

    host = cfg.get("mail", {}).get("smtp_host", "smtp.qq.com")
    port = int(cfg.get("mail", {}).get("smtp_port", 465))
    try:
        # local_hostname 必须是 ASCII：中文 Windows 电脑名会让 SMTP 握手报 UnicodeEncodeError
        with smtplib.SMTP_SSL(host, port, timeout=30, local_hostname="localhost",
                              context=ssl.create_default_context()) as s:
            s.login(sender, auth_code)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise AppError("SMTP 登录失败：授权码可能过期，请到 QQ 邮箱重新生成。")
    except Exception as e:
        raise AppError(f"发送失败：{e}")

    saved, save_err = append_to_sent(sender, auth_code, msg.as_bytes())
    return {
        "to": to,
        "subject": msg["Subject"],
        "saved_to_sent": saved,
        "save_error": "" if saved else save_err,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, obj=None, html=None, ctype="application/json; charset=utf-8"):
        body = html.encode("utf-8") if html is not None else json.dumps(obj or {}, ensure_ascii=False).encode("utf-8")
        origin = self.headers.get("Origin")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if origin and origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        origin = self.headers.get("Origin")
        if origin and origin_allowed(origin):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()
        else:
            self.send_response(403)
            self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            with open(INDEX, "r", encoding="utf-8") as f:
                self._send(200, html=f.read(), ctype="text/html; charset=utf-8")
            return
        if path == "/dashboard":
            try:
                cfg = get_config()
                rel = cfg.get("dashboard_path", "../一切顺利（投递看板）.html")
                dash = rel if os.path.isabs(rel) else os.path.normpath(os.path.join(BASE, rel))
                with open(dash, "r", encoding="utf-8") as f:
                    self._send(200, html=f.read(), ctype="text/html; charset=utf-8")
            except Exception as e:
                self._send(500, html=f"<h3>找不到看板文件</h3><p>{e}</p><p>请检查 邮件助手/config.json 的 dashboard_path。</p>", ctype="text/html; charset=utf-8")
            return
        if self.path == "/api/info":
            try:
                cfg = get_config()
                mail_ref = cfg.get("mail", {}).get("config_path", "../邮箱同步/config.json")
                mail_path = mail_ref if os.path.isabs(mail_ref) else os.path.normpath(os.path.join(BASE, mail_ref))
                mail_cfg = load_json(mail_path, {})
                self._send(200, {
                    "sender": mail_cfg.get("email", ""),
                    "resume": os.path.basename(cfg.get("resume_path", "")),
                    "has_key": bool((cfg.get("deepseek", {}).get("api_key") or "").strip()),
                    "model": cfg.get("deepseek", {}).get("model", "deepseek-flash"),
                })
            except Exception as e:
                self._send(500, {"error": str(e)})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin and not origin_allowed(origin):
            self._send(403, {"error": "来源不允许"})
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            self._send(400, {"error": "请求格式不对"})
            return

        try:
            if self.path == "/api/generate":
                self._send(200, deepseek_generate(
                    data.get("jd", ""), data.get("company", ""), data.get("position", ""),
                ))
            elif self.path == "/api/send":
                self._send(200, send_mail(
                    data.get("to", ""), data.get("subject", ""),
                    data.get("body", ""), data.get("confirm") is True,
                    data.get("filename", ""),
                ))
            else:
                self._send(404, {"error": "not found"})
        except AppError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": f"内部错误：{e}"})


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/dashboard"
    print(f"看板与投递邮件助手已启动：{url}")
    print("关闭这个窗口即可停止。")
    threading.Thread(target=lambda: (time.sleep(0.6), webbrowser.open(url)), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
