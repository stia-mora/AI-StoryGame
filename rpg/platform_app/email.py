"""platform_app.email — Resend API email client with branded HTML templates."""
from __future__ import annotations

import os
from html import escape

import httpx

RESEND_API_KEY: str = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM: str = os.environ.get("RESEND_FROM", "")


class EmailSendError(Exception):
    """Email delivery failed."""


def _public_base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "http://localhost:7860").rstrip("/")


def _preheader(text: str) -> str:
    return (
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;'
        'mso-hide:all;font-size:1px;line-height:1px;">'
        f"{escape(text)}"
        "</div>"
    )


def _email_css() -> str:
    return """
    <style>
      :root { color-scheme: light dark; supported-color-schemes: light dark; }
      body, table, td, a { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
      table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
      img { -ms-interpolation-mode: bicubic; border: 0; outline: none; text-decoration: none; }
      body { margin: 0 !important; padding: 0 !important; width: 100% !important; background: #f5f5f3; }
      .sr-body {
        margin: 0; padding: 0; background: #f5f5f3; color: #282824;
        font-family: "Microsoft YaHei UI", "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      }
      .sr-shell { width: 100%; background: #f5f5f3; padding: 40px 16px; }
      .sr-card {
        width: 100%; max-width: 560px; background: #fcfcfb; border-radius: 8px;
      }
      .sr-brand {
        color: #282824; font-size: 24px; line-height: 1.4;
        letter-spacing: .12em; font-weight: 600;
      }
      .sr-eyebrow {
        color: #805c20; font-size: 12px; line-height: 1.4; font-weight: 600;
        text-transform: uppercase; letter-spacing: .08em;
      }
      .sr-title {
        color: #282824;
        font-size: 22px; line-height: 1.32; font-weight: 600; letter-spacing: 0;
      }
      .sr-text { color: #50514d; font-size: 15px; line-height: 1.72; letter-spacing: 0; }
      .sr-muted { color: #6b6d66; font-size: 13px; line-height: 1.65; letter-spacing: 0; }
      .sr-panel { background: #f2eee4; border-radius: 8px; }
      .sr-code {
        color: #302719; font-family: SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 40px; line-height: 1.3; font-weight: 600; letter-spacing: .22em;
        white-space: nowrap; text-align: center; font-variant-numeric: tabular-nums;
      }
      .sr-button {
        display: inline-block; background: #e9be62; color: #302719 !important; border-radius: 6px;
        padding: 12px 18px; font-size: 14px; line-height: 1; font-weight: 700; text-decoration: none;
      }
      .sr-link { color: #805c20 !important; text-decoration: underline; font-weight: 600; }
      .sr-rule { height: 1px; line-height: 1px; background: #deded8; }
      @media screen and (max-width: 600px) {
        .sr-shell { padding: 16px 8px !important; }
        .sr-card { border-radius: 8px !important; }
        .sr-pad { padding: 28px 22px !important; }
        .sr-brand { font-size: 22px !important; }
        .sr-title { font-size: 20px !important; }
        .sr-code { font-size: 34px !important; letter-spacing: .18em !important; }
      }
      @media (prefers-color-scheme: dark) {
        body, .sr-body, .sr-shell { background: #0b0b0a !important; color: #e9e9e3 !important; }
        .sr-card { background: #151515 !important; }
        .sr-brand, .sr-title, .sr-text strong { color: #e9e9e3 !important; }
        .sr-text { color: #d0d0c8 !important; }
        .sr-muted { color: #aaa99f !important; }
        .sr-panel { background: #20201e !important; border-color: #383833 !important; }
        .sr-code, .sr-eyebrow, .sr-link { color: #edc46d !important; }
        .sr-rule { background: #383833 !important; }
      }
    </style>
    """


def _render_email(
    *,
    preheader: str,
    eyebrow: str,
    title: str,
    lead_html: str,
    main_html: str,
    secondary_html: str = "",
    footer_html: str = "",
    lang: str = "zh-CN",
) -> str:
    support_url = escape(f"{_public_base_url()}/play", quote=True)
    is_zh = lang.lower().startswith("zh")
    default_footer = (
        "如果这不是你本人的操作，请忽略此邮件。"
        if is_zh else "If you did not request this email, you can safely ignore it."
    )
    return f"""<!doctype html>
<html lang="{escape(lang, quote=True)}">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light dark">
  <meta name="supported-color-schemes" content="light dark">
  {_email_css()}
</head>
<body class="sr-body" style="margin:0;padding:0;background:#f5f5f3;color:#282824;font-family:'Microsoft YaHei UI','PingFang SC',Arial,sans-serif;">
{_preheader(preheader)}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="sr-shell" style="width:100%;background:#f5f5f3;padding:40px 16px;">
  <tr>
    <td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" class="sr-card" style="width:100%;max-width:560px;background:#fcfcfb;border-radius:8px;">
        <tr>
          <td class="sr-pad" style="padding:36px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td valign="top">
                  <div class="sr-brand" style="color:#282824;font-size:24px;line-height:1.4;font-weight:600;letter-spacing:.12em;">故事之间</div>
                  <div class="sr-muted" style="color:#6b6d66;font-size:11px;line-height:1.8;letter-spacing:.16em;">STORY BETWEEN</div>
                </td>
              </tr>
            </table>

            <div style="height:32px;line-height:32px;">&nbsp;</div>
            <div class="sr-eyebrow" style="color:#805c20;font-size:12px;line-height:1.4;font-weight:600;text-transform:uppercase;letter-spacing:.08em;">{escape(eyebrow)}</div>
            <div style="height:7px;line-height:7px;">&nbsp;</div>
            <div class="sr-title" style="color:#282824;font-size:22px;line-height:1.4;font-weight:600;">{escape(title)}</div>
            <div style="height:12px;line-height:12px;">&nbsp;</div>
            <div class="sr-text" style="color:#50514d;font-size:15px;line-height:1.72;">{lead_html}</div>
            <div style="height:20px;line-height:20px;">&nbsp;</div>
            {main_html}
            {secondary_html}
            <div style="height:24px;line-height:24px;">&nbsp;</div>
            <div class="sr-rule" style="height:1px;line-height:1px;background:#deded8;">&nbsp;</div>
            <div style="height:14px;line-height:14px;">&nbsp;</div>
            <div class="sr-muted" style="color:#6b6d66;font-size:13px;line-height:1.65;">
              {footer_html or default_footer}
              <br><a class="sr-link" style="color:#805c20;text-decoration:underline;font-weight:600;" href="{support_url}">{'打开故事之间' if is_zh else 'Open Story Between'}</a>
            </div>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def _send_resend(to: str, subject: str, text: str, html: str) -> None:
    if not RESEND_API_KEY:
        raise EmailSendError("RESEND_API_KEY not configured — email cannot be sent")

    resp = httpx.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": RESEND_FROM,
            "to": [to],
            "subject": subject,
            "text": text,
            "html": html,
        },
        timeout=10,
    )
    if resp.status_code >= 400:
        raise EmailSendError(f"Resend API {resp.status_code}: {resp.text[:300]}")


def build_verification_email(code: str, lang: str = "zh-CN") -> tuple[str, str, str]:
    is_zh = lang.lower().startswith("zh")
    subject = "故事之间 · 注册验证码" if is_zh else "Your Story Between verification code"
    text = (
        f"你的故事之间注册验证码是：{code}\n\n10 分钟内有效，请勿向他人透露。\n"
        "如果这不是你本人的操作，请忽略此邮件。"
        if is_zh else
        f"Your Story Between verification code: {code}\n\n"
        "Valid for 10 minutes. Never share this code. Ignore if you did not request this."
    )
    lead = (
        "在注册页面输入以下 6 位验证码，完成邮箱验证。"
        if is_zh
        else "Enter this 6-digit code on the registration page to verify your email."
    )
    main = f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="sr-panel" style="width:100%;background:#f2eee4;border-radius:8px;">
        <tr><td style="padding:24px 12px;">
          <div class="sr-code" style="color:#302719;font-family:SFMono-Regular,Menlo,Consolas,monospace;font-size:40px;line-height:1.3;font-weight:600;letter-spacing:.22em;white-space:nowrap;text-align:center;">{escape(code)}</div>
        </td></tr>
      </table>
    """
    secondary = f"""
      <div style="height:18px;line-height:18px;">&nbsp;</div>
      <div class="sr-muted" style="color:#6b6d66;font-size:13px;line-height:1.65;">
        {'10 分钟内有效，仅可使用一次。请勿向他人透露。' if is_zh else 'Valid for 10 minutes and one use only. Never share this code.'}
      </div>
    """
    html = _render_email(
        preheader="故事之间注册验证码，10 分钟内有效" if is_zh else "Verify your Story Between email within 10 minutes",
        eyebrow="邮箱验证" if is_zh else "Email verification",
        title="完成注册" if is_zh else "Verify your email",
        lead_html=lead,
        main_html=main,
        secondary_html=secondary,
        lang=lang,
    )
    return subject, text, html


def send_verification_email(to: str, code: str, lang: str = "zh-CN") -> None:
    """Send a registration verification code."""
    subject, text, html = build_verification_email(code, lang)
    _send_resend(to, subject, text, html)


def build_login_code_email(code: str, lang: str = "zh-CN") -> tuple[str, str, str]:
    is_zh = lang.lower().startswith("zh")
    subject = "故事之间 · 登录验证码" if is_zh else "Your Story Between login code"
    text = (
        f"你的故事之间登录验证码是：{code}\n\n10 分钟内有效，请勿向他人透露。\n"
        "如果这不是你本人的操作，请忽略此邮件。"
        if is_zh else
        f"Your Story Between login code: {code}\n\n"
        "Valid for 10 minutes. Never share this code. Ignore if you did not request this."
    )
    lead = (
        "在登录页面输入以下 6 位验证码，继续你的故事。"
        if is_zh
        else "Enter this 6-digit code on the sign-in page to continue your story."
    )
    main = f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="sr-panel" style="width:100%;background:#f2eee4;border-radius:8px;">
        <tr><td style="padding:24px 12px;">
          <div class="sr-code" style="color:#302719;font-family:SFMono-Regular,Menlo,Consolas,monospace;font-size:40px;line-height:1.3;font-weight:600;letter-spacing:.22em;white-space:nowrap;text-align:center;">{escape(code)}</div>
        </td></tr>
      </table>
    """
    secondary = f"""
      <div style="height:18px;line-height:18px;">&nbsp;</div>
      <div class="sr-muted" style="color:#6b6d66;font-size:13px;line-height:1.65;">
        {'10 分钟内有效，仅可使用一次。请勿向他人透露。' if is_zh else 'Valid for 10 minutes and one use only. Never share this code.'}
      </div>
    """
    html = _render_email(
        preheader="故事之间登录验证码，10 分钟内有效" if is_zh else "Your Story Between sign-in code, valid for 10 minutes",
        eyebrow="身份验证" if is_zh else "Account verification",
        title="登录故事之间" if is_zh else "Sign in to Story Between",
        lead_html=lead,
        main_html=main,
        secondary_html=secondary,
        lang=lang,
    )
    return subject, text, html


def send_login_code_email(to: str, code: str, lang: str = "zh-CN") -> None:
    """Send a one-time login code."""
    subject, text, html = build_login_code_email(code, lang)
    _send_resend(to, subject, text, html)


def send_recovery_code_email(to: str, code: str) -> None:
    subject = "撤销账户删除申请"
    text = f"你的账户恢复验证码：{code}，10 分钟内有效。此验证码仅用于撤销删除申请。非本人操作请忽略。"
    html = f"<p>你的账户恢复验证码：<strong>{escape(code)}</strong></p><p>10 分钟内有效，仅用于撤销删除申请。非本人操作请忽略。</p>"
    _send_resend(to, subject, text, html)


def build_password_reset_email(to: str, token: str, lang: str = "zh-CN") -> tuple[str, str, str]:
    is_zh = lang.lower().startswith("zh")
    link = f"{_public_base_url()}/Login.html#reset?token={token}"
    subject = "故事之间 · 重置密码" if is_zh else "Reset your Story Between password"
    text = (
        f"点击以下链接重置你的故事之间密码（30 分钟内有效）：\n{link}\n\n"
        "如果这不是你本人的操作，请忽略此邮件。你的密码不会被更改。\n\n"
        "---\n"
        f"Click the link below to reset your Story Between password (valid for 30 minutes):\n{link}\n\n"
        "If you did not request this, ignore this email. Your password will not be changed."
    )
    lead = (
        "我们收到了重置密码请求。这个链接会在 <strong style=\"color:#282824;\">30 分钟</strong>后失效。"
        if is_zh
        else "We received a password reset request. This link expires in <strong style=\"color:#282824;\">30 minutes</strong>."
    )
    main = f"""
      <table role="presentation" cellpadding="0" cellspacing="0">
        <tr><td>
          <a class="sr-button" style="display:inline-block;background:#e9be62;color:#302719;border-radius:6px;padding:12px 18px;font-size:14px;line-height:1;font-weight:700;text-decoration:none;" href="{escape(link)}">
            {'重置密码' if is_zh else 'Reset password'}
          </a>
        </td></tr>
      </table>
      <div style="height:16px;line-height:16px;">&nbsp;</div>
      <div class="sr-muted" style="color:#6b6d66;font-size:13px;line-height:1.65;word-break:break-all;">
        {escape(link)}
      </div>
    """
    html = _render_email(
        preheader="故事之间密码重置链接" if is_zh else "Story Between password reset link",
        eyebrow="Password Reset",
        title="重置你的密码" if is_zh else "Reset your password",
        lead_html=lead,
        main_html=main,
        lang=lang,
    )
    return subject, text, html


def send_password_reset_email(to: str, token: str, lang: str = "zh-CN") -> None:
    """Send a password reset link."""
    subject, text, html = build_password_reset_email(to, token, lang)
    _send_resend(to, subject, text, html)


def build_policy_notice_email(
    *,
    name_zh: str,
    name_en: str,
    new_version: str,
    summary: str,
    effective_display: str,
    url: str,
    is_zh: bool,
) -> tuple[str, str, str]:
    subject = (
        f"[故事之间] {name_zh}变更通知（{new_version}）"
        if is_zh
        else f"[Story Between] {name_en} Update ({new_version})"
    )
    if is_zh:
        text = (
            f"你好,\n\n"
            f"故事之间即将更新{name_zh}({new_version})。\n\n"
            f"变更摘要:\n{summary}\n\n"
            f"生效时间: {effective_display}\n\n"
            f"查看完整政策: {url}\n\n"
            f"如需帮助,请访问 {_public_base_url()}/play\n\n"
            f"---\n"
            f"[EN] Story Between is updating its {name_en} ({new_version}).\n"
            f"Summary: {summary}\n"
            f"Effective: {effective_display}\n"
            f"Full policy: {url}"
        )
        title = f"{name_zh}变更通知"
        lead = f"故事之间即将更新 <strong style=\"color:#282824;\">{escape(name_zh)}</strong>。"
    else:
        text = (
            f"Hello,\n\n"
            f"Story Between is updating its {name_en} ({new_version}).\n\n"
            f"Summary of changes:\n{summary}\n\n"
            f"Effective date: {effective_display}\n\n"
            f"Read the full policy: {url}\n\n"
            f"For help, visit {_public_base_url()}/play\n\n"
            f"---\n"
            f"[ZH] 故事之间即将更新{name_zh}({new_version})。\n"
            f"变更摘要: {summary}\n"
            f"生效时间: {effective_display}\n"
            f"完整政策: {url}"
        )
        title = f"{name_en} Update"
        lead = f"Story Between is updating its <strong style=\"color:#282824;\">{escape(name_en)}</strong>."

    main = f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="sr-panel" style="width:100%;background:#f2eee4;border:1px solid #deded8;border-radius:8px;">
        <tr><td style="padding:18px;">
          <div class="sr-eyebrow" style="color:#805c20;font-size:12px;line-height:1.4;font-weight:700;text-transform:uppercase;letter-spacing:.08em;">Version {escape(new_version)}</div>
          <div style="height:8px;line-height:8px;">&nbsp;</div>
          <div class="sr-text" style="color:#50514d;font-size:15px;line-height:1.72;">{escape(summary).replace(chr(10), '<br>')}</div>
          <div style="height:12px;line-height:12px;">&nbsp;</div>
          <div class="sr-muted" style="color:#6b6d66;font-size:13px;line-height:1.65;">Effective: {escape(effective_display)}</div>
        </td></tr>
      </table>
      <div style="height:18px;line-height:18px;">&nbsp;</div>
      <a class="sr-button" style="display:inline-block;background:#e9be62;color:#302719;border-radius:6px;padding:12px 18px;font-size:14px;line-height:1;font-weight:700;text-decoration:none;" href="{escape(url)}">
        {'查看完整政策' if is_zh else 'Read full policy'}
      </a>
    """
    html = _render_email(
        preheader=f"{title} · {new_version}",
        eyebrow="Policy Notice",
        title=title,
        lead_html=lead,
        main_html=main,
        footer_html="请在网站查看完整政策。" if is_zh else "Visit the website to read the full policy.",
        lang="zh-CN" if is_zh else "en",
    )
    return subject, text, html


def build_feedback_reply_email(
    reply_text: str, feedback_preview: str = "", lang: str = "zh-CN"
) -> tuple[str, str, str]:
    """反馈回执邮件:把管理员对某条反馈的回复发给提交者(或留邮箱的本地版用户)。"""
    is_zh = lang.lower().startswith("zh")
    subject = (
        "你的反馈有回复了 / We replied to your feedback"
        if is_zh
        else "Story Between replied to your feedback"
    )
    preview = (feedback_preview or "").strip()
    preview_short = preview[:160] + ("…" if len(preview) > 160 else "")
    if is_zh:
        text = (
            "你好,\n\n你之前提交的反馈,我们处理后回复如下:\n\n"
            f"{reply_text}\n\n"
            + (f"——\n你的反馈:{preview_short}\n\n" if preview_short else "")
            + "感谢你的反馈。\n\n---\n[EN] We replied to your feedback:\n" + reply_text
        )
        lead = "你之前提交的反馈,我们处理后回复如下。"
    else:
        text = (
            "Hello,\n\nWe've reviewed your feedback and replied:\n\n"
            f"{reply_text}\n\n"
            + (f"--\nYour feedback: {preview_short}\n\n" if preview_short else "")
            + "Thank you for the feedback."
        )
        lead = "We've reviewed the feedback you submitted and replied below."
    main = f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="sr-panel" style="width:100%;background:#f2eee4;border:1px solid #deded8;border-radius:8px;">
        <tr><td style="padding:18px;">
          <div class="sr-text" style="color:#50514d;font-size:15px;line-height:1.72;">{escape(reply_text).replace(chr(10), '<br>')}</div>
        </td></tr>
      </table>
    """
    secondary = (
        f"""
      <div style="height:16px;line-height:16px;">&nbsp;</div>
      <div class="sr-muted" style="color:#6b6d66;font-size:13px;line-height:1.65;">
        你的反馈:{escape(preview_short)}
      </div>
    """
        if preview_short
        else ""
    )
    html = _render_email(
        preheader="你的反馈有回复了" if is_zh else "We replied to your feedback",
        eyebrow="Feedback Reply",
        title="你的反馈有回复了" if is_zh else "We replied to your feedback",
        lead_html=lead,
        main_html=main,
        secondary_html=secondary,
        footer_html="这封邮件因你在反馈时留下了邮箱而发送。<br>You received this because you left an email with your feedback.",
        lang=lang,
    )
    return subject, text, html


def send_feedback_reply_email(
    to: str, reply_text: str, feedback_preview: str = "", lang: str = "zh-CN"
) -> None:
    """发送反馈回执邮件。失败抛 EmailSendError,由调用方 catch+warn(同 auth.py 模式)。"""
    subject, text, html = build_feedback_reply_email(reply_text, feedback_preview, lang)
    _send_resend(to, subject, text, html)
