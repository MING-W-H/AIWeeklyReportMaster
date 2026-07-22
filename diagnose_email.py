# -*- coding: utf-8 -*-
"""腾讯企业邮箱 SMTP 诊断脚本。

逐项检查 SMTP 连接、鉴权的可能失败原因，并打印详细错误信息。
用法：python diagnose_email.py
"""
import json
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

# 强制 UTF-8 输出（避免 PowerShell 中文乱码）
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

CONFIG_PATH = Path(__file__).parent / "config.json"


def main():
    if not CONFIG_PATH.exists():
        print(f"[ERROR] 找不到配置文件: {CONFIG_PATH}")
        return

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    email_cfg = config.get("email", {})
    sender = email_cfg.get("sender", "").strip()
    password = email_cfg.get("password", "").strip()
    smtp_host = email_cfg.get("smtp_host", "smtp.exmail.qq.com")
    smtp_port = email_cfg.get("smtp_port", 465)

    print("=" * 60)
    print("腾讯企业邮箱 SMTP 诊断")
    print("=" * 60)
    print(f"发件人    : {sender}")
    # 安全：仅打印密码长度和脱敏占位，不输出密码本身或 repr（避免日志/截图泄露）
    print(f"密码长度  : {len(password)} 字符")
    print(f"密码预览  : {'*' * min(len(password), 4)}（已脱敏）")
    print(f"SMTP 主机 : {smtp_host}")
    print(f"SMTP 端口 : {smtp_port}")
    print("=" * 60)

    # 1. 检查必填字段
    if not sender:
        print("[FAIL] email.sender 为空")
        return
    if not password:
        print("[FAIL] email.password 为空")
        return

    # 2. 检查发件人邮箱格式
    if "@" not in sender or "." not in sender.split("@")[-1]:
        print(f"[FAIL] 发件人邮箱格式异常: {sender}")
        return
    print(f"[OK] 发件人邮箱格式正常")

    # 3. 检查密码长度（腾讯企业邮箱客户端专用密码通常为 16 位）
    if len(password) != 16:
        print(f"[WARN] 密码长度 {len(password)} 位，腾讯企业邮箱客户端专用密码通常为 16 位")
        print("       请确认你生成的是「客户端专用密码」而非「登录密码」")
    else:
        print(f"[OK] 密码长度 16 位，符合客户端专用密码格式")

    # 4. 检查密码是否包含空格或特殊字符
    if " " in password or "\n" in password or "\r" in password:
        print(f"[FAIL] 密码中包含空格或换行符，请重新复制")
        return
    print(f"[OK] 密码无空格/换行符")

    # 5. 测试 SMTP 连接 + 登录
    print("\n" + "-" * 60)
    print("测试 1: 使用 SSL 端口 465 连接")
    print("-" * 60)
    try:
        print(f"[..] 正在连接 {smtp_host}:465 ...")
        server = smtplib.SMTP_SSL(smtp_host, 465, timeout=15)
        print(f"[OK] SSL 连接成功，服务器响应: {server.noop()[1]}")

        print(f"[..] 正在登录 (login)...")
        server.login(sender, password)
        print(f"[OK] 登录成功！鉴权通过！")

        # 尝试发送一封测试邮件给自己
        print(f"\n[..] 尝试发送测试邮件给 {sender} ...")
        msg = MIMEText("这是一封来自 AI 周报系统的 SMTP 诊断测试邮件。", "plain", "utf-8")
        msg["From"] = sender
        msg["To"] = sender
        msg["Subject"] = "AI 周报系统 - 邮件测试"
        server.sendmail(sender, [sender], msg.as_string())
        print(f"[OK] 测试邮件发送成功！请检查 {sender} 收件箱")
        server.quit()
        print("\n" + "=" * 60)
        print("诊断结论：邮箱配置完全正常，可正常运行 weekly_report.py")
        print("=" * 60)
        return
    except smtplib.SMTPAuthenticationError as e:
        print(f"[FAIL] 登录失败 (SMTPAuthenticationError)")
        print(f"       错误码: {e.smtp_code}")
        print(f"       错误信息: {e.smtp_error.decode('utf-8', errors='replace') if isinstance(e.smtp_error, bytes) else e.smtp_error}")
    except smtplib.SMTPConnectError as e:
        print(f"[FAIL] 连接失败 (SMTPConnectError): {e}")
    except smtplib.SMTPException as e:
        print(f"[FAIL] SMTP 异常: {e}")
    except Exception as e:
        print(f"[FAIL] 未知异常: {type(e).__name__}: {e}")

    # 6. 如果 465 失败，尝试 587 STARTTLS
    print("\n" + "-" * 60)
    print("测试 2: 使用 STARTTLS 端口 587 连接")
    print("-" * 60)
    try:
        print(f"[..] 正在连接 {smtp_host}:587 ...")
        server = smtplib.SMTP(smtp_host, 587, timeout=15)
        server.ehlo()
        print(f"[..] 启动 TLS...")
        server.starttls()
        server.ehlo()
        print(f"[OK] STARTTLS 连接成功")

        print(f"[..] 正在登录 (login)...")
        server.login(sender, password)
        print(f"[OK] 登录成功！鉴权通过！")
        server.quit()
        print("\n[提示] 465 失败但 587 成功，请将 config.json 中 smtp_port 改为 587")
        return
    except smtplib.SMTPAuthenticationError as e:
        print(f"[FAIL] 587 登录也失败: {e.smtp_error}")
    except Exception as e:
        print(f"[FAIL] 587 连接失败: {type(e).__name__}: {e}")

    # 7. 诊断结论
    print("\n" + "=" * 60)
    print("诊断结论：鉴权失败，可能原因如下：")
    print("=" * 60)
    print("""
1. 【最常见】客户端专用密码未真正生成成功
   - 登录 https://exmail.qq.com
   - 设置 → 客户端 → 客户端专用密码 → 点击"生成"
   - 生成后会显示 16 位密码（只显示一次！）
   - 确认已复制完整的 16 位字符

2. 【可能】未开启 SMTP 服务
   - 设置 → 客户端
   - 检查"IMAP/SMTP 服务"和"POP/SMTP 服务"是否都已开启
   - 开启后才能使用客户端专用密码登录

3. 【可能】密码复制错误
   - 重新生成一个新的客户端专用密码
   - 注意不要多复制空格或换行符
   - 替换 config.json 中 email.password 字段

4. 【可能】账号被风控
   - 频繁失败尝试可能触发腾讯风控
   - 等待 30 分钟后再试
   - 或在 Web 端登录确认账号状态正常

5. 【可能】使用的是登录密码而非客户端专用密码
   - 腾讯企业邮箱强制使用客户端专用密码
   - 登录密码无法通过 SMTP 鉴权

排查步骤：
  ① 登录 Web 邮箱，检查 SMTP 服务是否开启
  ② 重新生成客户端专用密码，确保 16 位完整复制
  ③ 替换 config.json 中 password 字段（注意 JSON 格式）
  ④ 重新运行 python diagnose_email.py
""")


if __name__ == "__main__":
    main()
