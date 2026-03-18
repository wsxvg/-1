#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博扫码登录测试 - 集成飞书通知
"""
import requests
import time
import os
import json
from datetime import datetime

# 环境变量配置（可手动修改）
FEISHU_APP_ID = "cli_a933badfd57bdbde"
FEISHU_APP_SECRET = "zliAQFZ61YOVdhSz8vecahozbGz6Ym5j"
FEISHU_CHAT_ID = "oc_727fbcc6d94e338a6520f0669c8e0bfe"


class WeiboQRBot:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
            "Referer": "https://passport.weibo.com/"
        }
        self.session.headers.update(self.headers)
        self._feishu_token = None
        self._token_expire_time = 0

    def get_feishu_token(self):
        """获取飞书 access_token"""
        if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
            print("⚠️ FEISHU_APP_ID 或 FEISHU_APP_SECRET 未配置")
            return None
        
        if self._feishu_token and time.time() < self._token_expire_time - 300:
            return self._feishu_token
        
        try:
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            data = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
            r = requests.post(url, json=data, timeout=10)
            result = r.json()
            
            if result.get('code') == 0:
                self._feishu_token = result.get('tenant_access_token')
                self._token_expire_time = time.time() + result.get('expire', 7200)
                print("✅ 飞书 Token 获取成功")
                return self._feishu_token
            else:
                print(f"❌ 飞书 Token 获取失败: {result}")
                return None
        except Exception as e:
            print(f"❌ 飞书 Token 请求异常: {e}")
            return None

    def upload_image_to_feishu(self, image_url):
        """下载图片并上传到飞书"""
        token = self.get_feishu_token()
        if not token:
            return None
        
        try:
            # 下载图片
            resp = requests.get(image_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if resp.status_code != 200:
                print(f"❌ 二维码图片下载失败: {resp.status_code}")
                return None
            
            # 上传到飞书
            url = "https://open.feishu.cn/open-apis/im/v1/images"
            files = {'image_type': (None, 'message'), 'image': ('qrcode.jpg', resp.content, 'image/jpeg')}
            headers = {'Authorization': f'Bearer {token}'}
            r = requests.post(url, files=files, headers=headers, timeout=30)
            result = r.json()
            
            if result.get('code') == 0:
                image_key = result.get('data', {}).get('image_key')
                print(f"✅ 二维码图片上传成功: {image_key}")
                return image_key
            else:
                print(f"❌ 图片上传失败: {result}")
                return None
        except Exception as e:
            print(f"❌ 图片上传异常: {e}")
            return None

    def send_feishu_card(self, qrcode_url, image_key=None):
        """发送飞书卡片消息"""
        if not FEISHU_APP_ID or not FEISHU_APP_SECRET or not FEISHU_CHAT_ID:
            print("⚠️ 飞书配置不完整，跳过通知")
            return
        
        token = self.get_feishu_token()
        if not token:
            print("❌ 无法获取飞书 Token，跳过通知")
            return
        
        # 构建卡片元素
        elements = []
        
        # 二维码图片
        if image_key:
            elements.append({
                "tag": "img",
                "img_key": image_key,
                "alt": {"tag": "plain_text", "content": "登录二维码"}
            })
        else:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"📷 [点击查看二维码]({qrcode_url})"
                }
            })
        
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "⏰ 请在 3 分钟内扫码登录\n✅ 扫码后请点击确认登录"
            }
        })
        
        card_msg = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": "🔐 微博登录验证"},
                    "template": "orange"
                },
                "elements": elements
            }
        }
        
        try:
            url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            payload = {
                "receive_id": FEISHU_CHAT_ID,
                "msg_type": "interactive",
                "content": json.dumps(card_msg["card"])
            }
            
            r = requests.post(url, json=payload, headers=headers, timeout=10)
            result = r.json()
            
            if result.get('code') == 0:
                print("✅ 飞书通知已发送")
            else:
                print(f"⚠️ 飞书通知失败: {result}")
        except Exception as e:
            print(f"⚠️ 飞书通知异常: {e}")

    def get_qr(self):
        url = "https://passport.weibo.com/sso/v2/qrcode/image?entry=miniblog&size=180"
        resp = self.session.get(url).json()
        return resp['data']['qrid'], resp['data']['image']

    def check_status(self, qrid):
        url = f"https://passport.weibo.com/sso/v2/qrcode/check?entry=miniblog&qrid={qrid}&_={int(time.time()*1000)}"
        resp = self.session.get(url)
        resp_json = resp.json()
        print(f"🔍 check_status 原始响应: {resp_json}")
        data = resp_json.get('data') or {}
        return resp_json.get('retcode'), data, resp_json

    def run(self):
        print("🚀 开始微博登录流程...")
        
        # 测试飞书 API 是否可访问
        print("🔍 测试飞书 API 连接...")
        try:
            test_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            test_data = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
            r = requests.post(test_url, json=test_data, timeout=10)
            print(f"📡 飞书 API 响应: {r.status_code} - {r.text[:200]}")
        except Exception as e:
            print(f"❌ 飞书 API 连接失败: {e}")
        
        # 获取二维码
        qrid, img_url = self.get_qr()
        print(f"✅ 二维码获取成功: {img_url}")
        
        # 上传二维码图片到飞书
        image_key = self.upload_image_to_feishu(img_url)
        
        # 发送飞书通知
        self.send_feishu_card(img_url, image_key)
        
        start = time.time()
        timeout = 180  # 3分钟
        
        print(f"⏳ 开始轮询，等待扫码... (超时 {timeout} 秒)")
        
        while time.time() - start < timeout:
            ret, data, full_resp = self.check_status(qrid)
            
            # 调试打印
            if ret == 50114004:
                print(f"🔍 50114004 完整响应: {full_resp}")
            
            if ret == 20000000:
                # 扫码成功，获取 alt
                elapsed = int(time.time() - start)
                print(f"✅ 扫码成功 ({elapsed}s)，正在换取 Cookie...")
                
                # 从 data.url 中提取 alt
                url = data.get('url', '')
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(url)
                query = parse_qs(parsed.query)
                alt = query.get('alt', [None])[0]
                
                if alt:
                    print(f"🎫 获取到 alt: {alt[:30]}...")
                    login_url = f"https://passport.weibo.com/sso/v2/login?entry=miniblog&alt={alt}&type=3"
                    self.session.get(login_url)
                    
                    cookies = self.session.cookies.get_dict()
                    sub_cookie = cookies.get('SUB')
                    print(f"🍪 获取到的 Cookie: {list(cookies.keys())}")
                    
                    if sub_cookie:
                        print("=" * 50)
                        print("✨ 登录成功！")
                        print(f"SUB: {sub_cookie}")
                        print("=" * 50)
                        
                        # 发送成功通知
                        self.send_success_notification(sub_cookie)
                        
                        return sub_cookie
                
                print("⚠️ 未能获取 Cookie，继续等待...")
                time.sleep(3)
                continue
            
            elif ret == 20100000:
                print("✅ 已扫码，请点击确认登录...")
                time.sleep(3)
                continue
            
            elif ret == 20000001:
                # 确认成功，换取 Cookie
                print("✅ 扫码确认成功，正在换取 Cookie...")
                alt = data.get('alt')
                if alt:
                    login_url = f"https://passport.weibo.com/sso/v2/login?entry=miniblog&alt={alt}&type=3"
                    self.session.get(login_url)
                
                cookies = self.session.cookies.get_dict()
                sub_cookie = cookies.get('SUB')
                
                print("=" * 50)
                print("✨ 登录成功！")
                print(f"SUB: {sub_cookie}")
                print("=" * 50)
                
                # 发送成功通知
                self.send_success_notification(sub_cookie)
                
                return sub_cookie
            
            elif ret == 50114001:
                # 二维码已扫描，等待确认
                elapsed = int(time.time() - start)
                print(f"✅ 已扫码 ({elapsed}s)，请在手机上确认登录...")
                time.sleep(3)
                continue
            
            elif ret == 50114004:
                # 已确认登录
                print("✅ 用户已确认，正在换取 Cookie...")
                print(f"📊 返回数据: {data}")
                print(f"📊 完整响应: {full_resp}")
                alt = data.get('alt') if data else None
                if alt:
                    login_url = f"https://passport.weibo.com/sso/v2/login?entry=miniblog&alt={alt}&type=3"
                    self.session.get(login_url)
                else:
                    print("⚠️ alt 为空，尝试直接访问登录页面...")
                    self.session.get("https://passport.weibo.com/sso/v2/login?entry=miniblog&type=3")
                
                cookies = self.session.cookies.get_dict()
                sub_cookie = cookies.get('SUB')
                print(f"🍪 获取到的 Cookie: {list(cookies.keys())}")
                
                if sub_cookie:
                    print("=" * 50)
                    print("✨ 登录成功！")
                    print(f"SUB: {sub_cookie}")
                    print("=" * 50)
                    
                    # 发送成功通知
                    self.send_success_notification(sub_cookie)
                    
                    return sub_cookie
                else:
                    print("⚠️ SUB Cookie 未获取到，继续等待...")
                    time.sleep(3)
                    continue
            
            else:
                print(f"⚠️ 未知状态: ret={ret}, data={data}")
                time.sleep(3)
                continue
        
        print("❌ 超时未完成扫码")
        return None

    def send_success_notification(self, sub_cookie):
        """发送登录成功通知"""
        if not FEISHU_APP_ID or not FEISHU_APP_SECRET or not FEISHU_CHAT_ID:
            return
        
        token = self.get_feishu_token()
        if not token:
            return
        
        card_msg = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": "✅ 微博登录成功"},
                    "template": "green"
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"🎉 新的 SUB Cookie 已获取\n\n`{sub_cookie[:30]}...`"
                        }
                    }
                ]
            }
        }
        
        try:
            url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            payload = {
                "receive_id": FEISHU_CHAT_ID,
                "msg_type": "interactive",
                "content": json.dumps(card_msg["card"])
            }
            requests.post(url, json=payload, headers=headers, timeout=10)
        except Exception:
            pass


if __name__ == "__main__":
    result = WeiboQRBot().run()
    
    if result:
        # 写入 GitHub Output
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"NEW_SUB_COOKIE={result}\n")
        print(f"\n🎉 新的 SUB Cookie: {result}")
    else:
        print("\n❌ 获取 Cookie 失败")
        exit(1)
