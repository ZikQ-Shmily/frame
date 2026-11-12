"""SMTP notifications. Configuration is validated before any connection is opened."""
import html
import ipaddress
import re
import smtplib
import ssl
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate
from urllib.parse import urlsplit


class MailError(Exception):
    pass


DEFAULTS = dict(enabled=False, smtp_host='', smtp_port=465, security='ssl',
                smtp_username='', from_email='', to_email='', site_url='')


def email_address(value, label):
    if not isinstance(value, str) or len(value) > 254:
        raise ValueError(label + '格式无效')
    value = value.strip()
    if not value:
        return ''
    try:
        address = Address(addr_spec=value)
        value.encode('ascii')
        if address.addr_spec != value or not address.username or '.' not in address.domain:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError, IndexError):
        raise ValueError(label + '须为单个有效邮箱地址，不要填写显示名称或多个地址') from None
    return value


def validate_config(data, previous, encrypt):
    config = {**DEFAULTS, **previous}
    for field in ('smtp_host', 'smtp_username', 'site_url'):
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, str) or len(value) > (2000 if field == 'site_url' else 254) or any(ord(c) < 32 for c in value):
            raise ValueError('邮件设置格式无效')
        config[field] = value.strip()
    host = config['smtp_host']
    if host:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r'(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host):
                raise ValueError('SMTP 服务器只填写主机名，例如 smtp.qq.com，不要包含协议或端口') from None
    if 'smtp_port' in data:
        value = data['smtp_port']
        if isinstance(value, bool) or not re.fullmatch(r'\d{1,5}', str(value)) or not 1 <= int(value) <= 65535:
            raise ValueError('SMTP 端口须为 1 至 65535 的整数')
        config['smtp_port'] = int(value)
    if 'security' in data:
        if data['security'] not in ('ssl', 'starttls'):
            raise ValueError('请选择 SSL/TLS 或 STARTTLS 加密连接')
        config['security'] = data['security']
    for field, label in (('from_email', '发件邮箱'), ('to_email', '收件邮箱')):
        if field in data:
            config[field] = email_address(data[field], label)
    site = config['site_url']
    if site:
        parsed = urlsplit(site)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(c.isspace() for c in site):
            raise ValueError('网站地址须为不含账号、查询参数或锚点的 HTTP / HTTPS 地址')
        try:
            parsed.port
        except ValueError:
            raise ValueError('网站地址端口无效') from None
        config['site_url'] = site.rstrip('/')
    for field in ('enabled', 'clear_password'):
        if field in data and type(data[field]) is not bool:
            raise ValueError('邮件开关格式无效')
    password = data.get('smtp_password', '')
    if not isinstance(password, str) or len(password) > 4096 or any(ord(c) < 32 for c in password):
        raise ValueError('SMTP 密码或授权码格式无效')
    password = password.strip()
    identity_changed = any(config.get(key, '') != previous.get(key, '') for key in ('smtp_host', 'smtp_username'))
    if data.get('clear_password') or (identity_changed and not password):
        config.pop('smtp_password', None)
    if password:
        config['smtp_password'] = encrypt(password)
    if 'enabled' in data:
        config['enabled'] = data['enabled']
    if config['enabled']:
        require_ready(config)
    return config


def require_ready(config):
    if not all(config.get(key) for key in ('smtp_host', 'from_email', 'to_email')):
        raise ValueError('请先填写 SMTP 服务器、发件邮箱和收件邮箱')
    if config.get('smtp_username') and not config.get('smtp_password'):
        raise ValueError('请填写 SMTP 密码或授权码；更换服务器或账号后需重新填写')
    if config.get('smtp_password') and not config.get('smtp_username'):
        raise ValueError('使用 SMTP 授权码时请填写 SMTP 用户名')


def build_message(config, payload, recipient, message_id):
    test = payload.get('test') is True
    title = re.sub(r'[\r\n]+', ' ', str(payload.get('title', ''))).strip()
    username = re.sub(r'[\r\n]+', ' ', str(payload.get('username', ''))).strip()
    movie = payload.get('kind') == 'movie'
    work = title + ('' if movie else ' · 第 %s 季' % payload.get('season', 1))
    heading = '邮件通知测试成功' if test else '有用户提交了新的追更'
    lines = ['这是一封来自拾影的测试邮件，SMTP 发信配置已通过测试。'] if test else [
        '提交用户：' + username, '作品：' + work,
        '类型：' + ('电影' if movie else '剧集'), '年份：' + str(payload.get('year') or '待定'),
        '提交时间：' + str(payload.get('submitted_at', '')),
        '请登录拾影查看提交并选择资源来源。']
    site = config.get('site_url', '')
    tmdb = payload.get('tmdb') or {}
    tmdb_url = ('https://www.themoviedb.org/' + str(tmdb.get('media_type')) + '/' + str(tmdb.get('id'))
                if tmdb.get('media_type') in ('tv', 'movie') and str(tmdb.get('id', '')).isdigit() else '')
    links = [('打开拾影', site + '/#all')] if site else []
    if tmdb_url and not test:
        links.append(('TMDB 作品资料', tmdb_url))
    message = EmailMessage()
    message['Subject'] = '拾影 · 测试邮件' if test else '拾影 · 新追更：' + work
    message['From'] = Address(display_name='拾影', addr_spec=config['from_email'])
    message['To'] = recipient
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = '<%s@frame.local>' % message_id
    message.set_content(heading + '\n\n' + '\n'.join(lines) + '\n\n' + '\n'.join(label + '：' + url for label, url in links))
    escape = lambda value: html.escape(str(value), quote=True)
    intro = 'SMTP 发信配置已通过测试。' if test else '一部新的作品正在等待你整理。'
    if test:
        detail = '<p style="margin:0;color:#526b8c;font-size:15px;line-height:1.8">邮件通知已准备就绪，新的追更提交会发送到此邮箱。</p>'
    else:
        fields = [('提交用户', username or '未知用户'), ('作品类型', '电影' if movie else '剧集'),
                  ('年份', payload.get('year') or '待定'), ('提交时间', payload.get('submitted_at') or '未知')]
        rows = ''.join('<tr><td style="padding:9px 0;color:#8191a8;font-size:13px;white-space:nowrap;vertical-align:top">'
                       + escape(label) + '</td><td style="padding:9px 0 9px 20px;text-align:right;color:#344f72;'
                       'font-size:14px;word-break:break-word">' + escape(value) + '</td></tr>' for label, value in fields)
        detail = ('<p style="margin:0 0 8px;color:#778fad;font-size:11px;letter-spacing:2px">NEW REQUEST</p>'
                  '<h2 style="margin:0 0 20px;color:#203959;font-size:22px;line-height:1.45;word-break:break-word">'
                  + escape(work) + '</h2><table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
                  'style="border-top:1px solid #e5ecf6;padding-top:12px">' + rows + '</table>')
    actions = ''
    if site:
        actions += ('<table role="presentation" cellspacing="0" cellpadding="0" style="margin:26px 0 0"><tr><td '
                    'bgcolor="#176ad1" style="border-radius:22px"><a href="' + escape(site + '/#all')
                    + '" style="display:inline-block;padding:12px 24px;color:#ffffff;font-size:14px;'
                    'font-weight:bold;text-decoration:none">打开拾影 &rarr;</a></td></tr></table>')
    if tmdb_url and not test:
        actions += ('<p style="margin:20px 0 0"><a href="' + escape(tmdb_url)
                    + '" style="color:#5982b5;font-size:13px;text-decoration:underline">查看 TMDB 作品资料</a></p>')
    markup = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
              '<body style="margin:0;padding:0;background:#edf3fb;color:#203959;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif">'
              '<div style="display:none;max-height:0;overflow:hidden;opacity:0">' + escape(heading + ' · ' + intro) + '</div>'
              '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#edf3fb"><tr><td align="center" style="padding:32px 14px">'
              '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px">'
              '<tr><td style="padding:0 5px 22px;color:#25466c;font-size:21px;font-weight:bold;letter-spacing:2px">拾影 '
              '<span style="font-size:10px;font-weight:normal;letter-spacing:3px;color:#829bb9">FRAME</span></td></tr>'
              '<tr><td style="padding:32px 28px;background:#ffffff;border:1px solid #e3ecf8;border-radius:24px">'
              '<p style="margin:0 0 10px;color:#7b9ac0;font-size:11px;letter-spacing:2px">FRAME NOTIFICATIONS</p>'
              '<h1 style="margin:0 0 10px;font-size:25px;line-height:1.4;color:#203959">' + escape(heading) + '</h1>'
              '<p style="margin:0 0 24px;color:#7189a6;font-size:14px;line-height:1.7">' + escape(intro) + '</p>'
              '<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td style="padding:22px;'
              'background:#f2f7fe;border:1px solid #e3edf9;border-radius:18px">' + detail + '</td></tr></table>' + actions
              + '</td></tr><tr><td style="padding:22px 6px;color:#8a9bb1;font-size:12px;line-height:1.7">'
              '拾影 · 收好每一段故事<br>此邮件由拾影自动发送。</td></tr></table></td></tr></table></body></html>')
    message.add_alternative(markup, subtype='html')
    return message


def send_notification(config, password, payload, recipient, message_id):
    require_ready(config)
    message = build_message(config, payload, email_address(recipient, '收件邮箱'), message_id)
    context = ssl.create_default_context()
    client = None
    try:
        if config.get('security') == 'starttls':
            client = smtplib.SMTP(config['smtp_host'], config['smtp_port'], timeout=12)
        else:
            client = smtplib.SMTP_SSL(config['smtp_host'], config['smtp_port'], timeout=12, context=context)
        if config.get('security') == 'starttls':
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        if config.get('smtp_username'):
            client.login(config['smtp_username'], password)
        refused = client.send_message(message, from_addr=config['from_email'], to_addrs=[recipient])
        if refused:
            raise MailError('收件地址被发信服务器拒绝，请检查收件邮箱')
    except smtplib.SMTPAuthenticationError:
        raise MailError('SMTP 登录失败，请检查用户名、授权码及邮箱的 SMTP 开关') from None
    except smtplib.SMTPRecipientsRefused:
        raise MailError('收件地址被发信服务器拒绝，请检查收件邮箱') from None
    except smtplib.SMTPSenderRefused:
        raise MailError('发件地址被拒绝，请确认发件邮箱与 SMTP 账号一致') from None
    except ssl.SSLError:
        raise MailError('SMTP 加密连接失败，请检查服务器、端口和加密方式') from None
    except (OSError, smtplib.SMTPException):
        raise MailError('邮件未能发送，请检查 SMTP 服务、端口和服务器网络') from None
    finally:
        if client is not None:
            try:
                client.quit()
            except (OSError, smtplib.SMTPException):
                pass  # A QUIT failure must not retry a message already accepted by DATA.
            finally:
                client.close()
