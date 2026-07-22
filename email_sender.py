# -*- coding: utf-8 -*-
"""邮件发送模块。

负责通过腾讯企业邮箱（SMTP SSL）发送周报邮件：
- 邮件正文为周报内容（Markdown 转 HTML）
- 可选附带周报文件作为附件
- 支持收件人、抄送列表
"""
import os
import smtplib
from datetime import datetime
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from email.header import Header
from email.utils import formatdate
from pathlib import Path
from typing import Any, Dict

from output_resolver import calc_last_week_range
from text_utils import markdown_to_html


def send_report_email(
    report_text: str,
    report_path: Path,
    config: Dict[str, Any],
    excel_path: "Path | None" = None,
) -> None:
    """通过腾讯企业邮箱发送周报邮件。

    邮件正文为周报内容（Markdown 转 HTML），可选附带周报文件作为附件。
    若提供 excel_path，则同时附上 CRM 下载的工时 Excel 文件。

    Args:
        report_text: 周报 Markdown 文本
        report_path: 周报 .md 文件路径
        config: 全局配置
        excel_path: CRM 下载的工时 Excel 文件路径（可选）
    """
    email_cfg = config.get("email", {})
    if not email_cfg.get("enabled"):
        return

    # 环境变量优先级高于 config.json（便于安全部署，避免明文密码）
    # EMAIL_SENDER / EMAIL_PASSWORD 由 .env 或系统环境变量提供
    sender = (os.getenv("EMAIL_SENDER") or email_cfg.get("sender", "")).strip()
    password = (os.getenv("EMAIL_PASSWORD") or email_cfg.get("password", "")).strip()
    recipients = email_cfg.get("recipients", [])
    cc = email_cfg.get("cc", [])

    # 参数校验
    if not sender:
        raise ValueError("发件人邮箱未配置，请在 .env 中设置 EMAIL_SENDER 或在 config.json 中设置 email.sender")
    if not password:
        raise ValueError("邮箱密码未配置，请在 .env 中设置 EMAIL_PASSWORD 或在 config.json 中设置 email.password")
    if not recipients:
        raise ValueError("email.recipients 为空，请至少填入一个收件人邮箱")

    smtp_host = email_cfg.get("smtp_host", "smtp.exmail.qq.com")
    smtp_port = email_cfg.get("smtp_port", 465)
    subject_template = email_cfg.get("subject_template", "Vue 周报 {last_week_range}")

    # 计算上一周日期范围（复用 output_resolver 的逻辑）
    date_info = calc_last_week_range(datetime.now())
    subject = subject_template
    for placeholder, value in date_info.items():
        subject = subject.replace("{" + placeholder + "}", value)

    # 构建邮件
    msg = MIMEMultipart("mixed")
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = Header(subject, "utf-8")
    msg["Date"] = formatdate(localtime=True)

    # 邮件正文：HTML 格式（Markdown 转 HTML）
    html_body = markdown_to_html(report_text)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # 附件 1：周报文件
    if email_cfg.get("attach_report", True) and report_path.exists():
        with open(report_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        # 使用 Base64 编码中文文件名，兼容所有邮件客户端（含手机端）
        # RFC 2231 (utf-8'') 编码在部分手机客户端不兼容，会显示为 utf-8''xxx.md
        filename_encoded = Header(report_path.name, "utf-8").encode()
        part.add_header(
            "Content-Disposition", "attachment",
            filename=filename_encoded,
        )
        msg.attach(part)

    # 附件 2：CRM 下载的工时 Excel 文件
    if excel_path is not None and Path(excel_path).exists():
        with open(excel_path, "rb") as f:
            part = MIMEBase(
                "application",
                "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            part.set_payload(f.read())
        encoders.encode_base64(part)
        filename_encoded = Header(Path(excel_path).name, "utf-8").encode()
        part.add_header(
            "Content-Disposition", "attachment",
            filename=filename_encoded,
        )
        msg.attach(part)

    # 发送邮件（腾讯企业邮箱使用 SSL）
    all_recipients = list(recipients) + list(cc)
    print(f"[INFO] 正在通过 {smtp_host}:{smtp_port} 发送周报邮件...")
    print(f"       发件人: {sender}")
    print(f"       收件人: {', '.join(recipients)}")
    if cc:
        print(f"       抄  送: {', '.join(cc)}")
    print(f"       主  题: {subject}")
    if email_cfg.get("attach_report", True) and report_path.exists():
        print(f"       附件 1: {report_path.name}")
    if excel_path is not None and Path(excel_path).exists():
        print(f"       附件 2: {Path(excel_path).name}")

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
            server.login(sender, password)
            server.sendmail(sender, all_recipients, msg.as_string())
        print("[INFO] 周报邮件发送成功!")
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError(
            f"邮箱鉴权失败：请检查 email.sender='{sender}' 和 email.password 是否正确。"
            f"\n提示：腾讯企业邮箱需使用「客户端专用密码」，而非登录密码。"
            f"\n获取方式：企业邮箱 → 设置 → 客户端专用密码 → 生成"
        )
    except smtplib.SMTPRecipientsRefused:
        raise RuntimeError(
            f"收件人被拒绝，请检查 recipients 列表中的邮箱地址是否有效: {recipients}"
        )
    except smtplib.SMTPException as e:
        raise RuntimeError(f"邮件发送失败 (SMTP): {e}")
    except ConnectionRefusedError:
        raise RuntimeError(
            f"无法连接 {smtp_host}:{smtp_port}，请检查网络连接或防火墙设置"
        )
