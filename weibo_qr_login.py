import requests
import time
import os
import json
from datetime import datetime

# 环境变量配置
FEISHU_WEBHOOK = os.getenv('FEISHU_WEBHOOK_URL')

class WeiboQRBot:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
            "Referer": "https://passport.weibo.com/"
        }
        self.session.headers.update(self.headers)

    def send_feishu(self, text, image_url=None):
        if not FEISHU_WEBHOOK: return
        data = {"msg_type": "text", "content": {"text": text}}
        if image_url:
            data = {"msg_type": "post", "content": {"post": {"zh": {"title": "微博登录", "content": [[{"tag": "text", "text": text}, {"tag": "img", "image_key": "img_v2_xxx"}]]}}}}
            # 这里简化为直接发文字，如果需要传图，飞书需要先上传图片获取 image_key
        requests.post(FEISHU_WEBHOOK, json=data)

    def get_qr(self):
        url = "https://passport.weibo.com/sso/v2/qrcode/image?entry=miniblog&size=180"
        resp = self.session.get(url).json()
        return resp['data']['qrid'], resp['data']['image']

    def check_status(self, qrid):
        url = f"https://passport.weibo.com/sso/v2/qrcode/check?entry=miniblog&qrid={qrid}&_={int(time.time()*1000)}"
        resp = self.session.get(url).json()
        return resp['retcode'], resp.get('data', {})

    def run(self):
        print("🚀 开始微博登录流程...")
        qrid, img_url = self.get_qr()
        msg = f"请扫码登录: {img_url}"
        print(msg)
        self.send_feishu(msg)

        start = time.time()
        while time.time() - start < 180: # 3分钟超时
            ret, data = self.check_status(qrid)
            if ret == 20000000:
                print("✅ 扫码成功，正在换取 Cookie...")
                # 触发登录换取 Ticket
                alt = data['alt']
                login_url = f"https://passport.weibo.com/sso/v2/login?entry=miniblog&alt={alt}&type=3"
                self.session.get(login_url)
                
                # 打印并返回 Cookie
                cookies = self.session.cookies.get_dict()
                print("✨ 登录成功！")
                print(f"SUB: {cookies.get('SUB')}")
                print(f"SUBP: {cookies.get('SUBP')}")
                return
            time.sleep(3)

if __name__ == "__main__":
    WeiboQRBot().run()
