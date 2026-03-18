#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博抢购增量监控 V8.6 (集成Debug日志)
"""
import re
import os
import sys
import time
import json
import random
import logging
import requests
import hashlib
import base64
import pytz
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from dateutil import parser
from typing import Dict, List, Optional, Any, Union

try:
    from PIL import Image
except ImportError:
    Image = None

# ========== 微博扫码登录模块 ==========
class WeiboQRLogin:
    """微博扫码登录类 - 集成到主程序"""
    
    def __init__(self, feishu_app_id: str = None, feishu_app_secret: str = None, feishu_chat_id: str = None):
        self.session = requests.Session()
        # 使用完整的 headers（和 weibo_qr_login.py 一致）
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
            "Referer": "https://passport.weibo.com/"
        })
        self.qrcode_url = "https://passport.weibo.com/sso/v2/qrcode/image"
        self.check_url = "https://passport.weibo.com/sso/v2/qrcode/check"
        self.login_url = "https://passport.weibo.com/sso/v2/login"
        self.feishu_app_id = feishu_app_id
        self.feishu_app_secret = feishu_app_secret
        self.feishu_chat_id = feishu_chat_id
        self._feishu_token = None
        self._token_expire_time = 0
        self.status_file = "qrcode_status.json"
        self.qr_cool_down = 3600
    
    def get_feishu_token(self) -> Optional[str]:
        if not self.feishu_app_id or not self.feishu_app_secret:
            return None
        if self._feishu_token and time.time() < self._token_expire_time - 300:
            return self._feishu_token
        try:
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            data = {"app_id": self.feishu_app_id, "app_secret": self.feishu_app_secret}
            r = requests.post(url, json=data, timeout=10)
            result = r.json()
            if result.get('code') == 0:
                self._feishu_token = result.get('tenant_access_token')
                self._token_expire_time = time.time() + result.get('expire', 7200)
                return self._feishu_token
            return None
        except:
            return None
    
    def check_qrcode_status(self) -> bool:
        try:
            if not os.path.exists(self.status_file):
                return False
            with open(self.status_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            last_send_time = data.get('send_time', 0)
            if time.time() - last_send_time < self.qr_cool_down:
                return True
            return False
        except:
            return False
    
    def save_qrcode_status(self, success: bool = True):
        try:
            with open(self.status_file, 'w', encoding='utf-8') as f:
                json.dump({'send_time': time.time(), 'success': success}, f)
        except:
            pass
    
    def upload_qrcode_to_feishu(self, qrcode_url: str) -> Optional[str]:
        token = self.get_feishu_token()
        if not token:
            logger.error("❌ 无法获取飞书token")
            return None
        try:
            resp = requests.get(qrcode_url, timeout=15)
            if resp.status_code != 200:
                logger.error(f"❌ 二维码下载失败: HTTP {resp.status_code}")
                return None
            logger.info(f"📷 二维码下载成功: {len(resp.content)} bytes")
            
            url = "https://open.feishu.cn/open-apis/im/v1/images"
            files = {
                'image_type': (None, 'message'),
                'image': ('qrcode.jpg', resp.content, 'image/jpeg')
            }
            headers = {'Authorization': f'Bearer {token}'}
            
            r = requests.post(url, files=files, headers=headers, timeout=30)
            result = r.json()
            logger.info(f"📤 飞书上传响应: {result}")
            
            if result.get('code') == 0:
                image_key = result.get('data', {}).get('image_key')
                logger.info(f"✅ 飞书图片上传成功: {image_key}")
                return image_key
            else:
                logger.error(f"❌ 飞书图片上传失败: {result}")
                return None
        except Exception as e:
            logger.error(f"❌ 飞书图片上传异常: {e}")
            return None
    
    def send_feishu_notification(self, qrcode_url: str, image_key: str = None, trigger_only: bool = False) -> bool:
        """
        发送飞书二维码通知
        - trigger_only=False: 正常模式，显示轮询提示
        - trigger_only=True: 手动触发模式，不显示轮询（用户手动扫码）
        """
        if not self.feishu_app_id or not self.feishu_app_secret or not self.feishu_chat_id:
            return False
        token = self.get_feishu_token()
        if not token:
            return False
        
        elements = []
        if image_key:
            elements.append({"tag": "img", "img_key": image_key, "alt": {"tag": "plain_text", "content": "登录二维码"}})
        else:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"📷 [点击查看二维码]({qrcode_url})"}})
        
        if trigger_only:
            # 手动触发模式
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "📱 请使用微博扫描上方二维码"}})
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "✅ 扫描成功后，下次运行将自动获取新Cookie"}})
        else:
            # 正常模式
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "⏰ Cookie 已过期，请扫码更新"}})
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "� 程序将持续等待扫描（2分钟内）"}})
        
        card = {"header": {"title": {"tag": "plain_text", "content": "🔐 Cookie 已过期"}, "template": "orange"}, "elements": elements}
        
        try:
            url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
            payload = {"receive_id": self.feishu_chat_id, "msg_type": "interactive", "content": json.dumps(card)}
            r = requests.post(url, json=payload, headers={'Authorization': f'Bearer {token}'}, timeout=10)
            return r.json().get('code') == 0
        except:
            return False
    
    def get_qrcode(self) -> tuple:
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://passport.weibo.com/'}
        try:
            r = self.session.get(self.qrcode_url, params={'entry': 'miniblog', 'size': '180'}, headers=headers, timeout=15)
            data = r.json()
            if data.get('retcode') == 20000000:
                qrid = data.get('data', {}).get('qrid')
                image_url = data.get('data', {}).get('image')
                return qrid, image_url
            return None, None
        except:
            return None, None
    
    def check_status(self, qrid: str) -> tuple:
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://passport.weibo.com/'}
        url = f"{self.check_url}?entry=miniblog&qrid={qrid}&_={int(time.time()*1000)}"
        resp = self.session.get(url, headers=headers, timeout=15)
        resp_json = resp.json()
        return resp_json.get('retcode'), resp_json.get('data') or {}, resp_json
    
    def run_login_process(self, timeout: int = 120, trigger_only: bool = False) -> Optional[str]:
        """
        扫码登录流程
        - trigger_only=False: 正常模式，检查24h冷却，发送二维码+轮询，超时发送按钮
        - trigger_only=True: 手动触发模式，跳过冷却，发送二维码+轮询（超时不发送按钮）
        """
        logger.info(f"🚀 开始微博扫码登录流程 (trigger_only={trigger_only})")
        
        # 正常模式：检查24小时冷却
        if not trigger_only and self.check_qrcode_status():
            logger.warning("⚠️ 24小时内已发送过二维码，跳过")
            return None
        
        # 获取二维码
        qrid, image_url = self.get_qrcode()
        if not qrid:
            logger.error("❌ 获取二维码失败")
            return None
        
        # 上传并发送二维码到飞书
        image_key = self.upload_qrcode_to_feishu(image_url)
        if not image_key:
            logger.error("❌ 二维码上传飞书失败")
            return None
        
        # 发送通知
        if self.send_feishu_notification(image_url, image_key, trigger_only=trigger_only):
            if not trigger_only:
                self.save_qrcode_status(success=True)
        
        # 轮询等待扫描（两种模式都轮询）
        start_time = time.time()
        saved_alt = None  # 保存 alt 供 50114004 使用
        
        while time.time() - start_time < timeout:
            ret, data, full_resp = self.check_status(qrid)
            
            # 50114004 = 已确认登录
            if ret == 50114004:
                logger.info("✅ 用户已确认登录，正在获取 Cookie...")
                from urllib.parse import urlparse, parse_qs
                
                # 优先用保存的 alt，其次从 data 获取
                alt = saved_alt
                if not alt:
                    url = data.get('url', '') if isinstance(data, dict) else ''
                    query = parse_qs(urlparse(url).query)
                    alt = query.get('alt', [None])[0] or (data.get('alt') if isinstance(data, dict) else None)
                
                if alt:
                    logger.info(f"🎫 使用 alt: {alt[:30]}...")
                    # 跟随重定向获取 cookie
                    self.session.get(
                        f"https://passport.weibo.com/sso/v2/login?entry=miniblog&alt={alt}&type=3",
                        allow_redirects=True
                    )
                else:
                    logger.warning("⚠️ alt 为空，尝试直接访问登录页面...")
                    self.session.get("https://passport.weibo.com/sso/v2/login?entry=miniblog&type=3", allow_redirects=True)
                
                cookies = self.session.cookies.get_dict()
                sub_cookie = cookies.get('SUB')
                logger.info(f"🍪 获取到的 Cookie: {list(cookies.keys())}")
                
                if sub_cookie:
                    logger.info("✅ 扫码成功，获取到新Cookie")
                    self.save_qrcode_status(success=False)
                    github_output = os.environ.get('GITHUB_OUTPUT', '')
                    if github_output:
                        with open(github_output, 'a') as f:
                            f.write(f'NEW_SUB_COOKIE={sub_cookie}\n')
                    else:
                        print(f"::set-output name=NEW_SUB_COOKIE::{sub_cookie}")
                    return sub_cookie
                else:
                    logger.warning("⚠️ SUB Cookie 未获取到，继续等待...")
                time.sleep(3)
                continue
            
            # 50114001 = 已扫码，等待确认
            if ret == 50114001:
                logger.info("✅ 已扫码，请点击确认登录...")
                # 尝试获取并保存 alt
                from urllib.parse import urlparse, parse_qs
                url = data.get('url', '') if isinstance(data, dict) else ''
                query = parse_qs(urlparse(url).query)
                alt = query.get('alt', [None])[0]
                if alt:
                    saved_alt = alt
                    logger.info(f"🎫 保存 alt: {alt[:30]}...")
                time.sleep(3)
                continue
            
            # 20000000 = 扫码成功，获取 alt
            if ret == 20000000:
                logger.info("✅ 用户已扫码，等待确认...")
                from urllib.parse import urlparse, parse_qs
                url = data.get('url', '') if isinstance(data, dict) else ''
                query = parse_qs(urlparse(url).query)
                alt = query.get('alt', [None])[0]
                
                if alt:
                    logger.info(f"🎫 获取到 alt: {alt[:30]}...")
                    saved_alt = alt  # 保存 alt
                    self.session.get(
                        f"https://passport.weibo.com/sso/v2/login?entry=miniblog&alt={alt}&type=3",
                        allow_redirects=True
                    )
                    cookies = self.session.cookies.get_dict()
                    sub_cookie = cookies.get('SUB')
                    if sub_cookie:
                        logger.info("✅ 扫码成功，获取到新Cookie")
                        self.save_qrcode_status(success=False)
                        github_output = os.environ.get('GITHUB_OUTPUT', '')
                        if github_output:
                            with open(github_output, 'a') as f:
                                f.write(f'NEW_SUB_COOKIE={sub_cookie}\n')
                        else:
                            print(f"::set-output name=NEW_SUB_COOKIE::{sub_cookie}")
                        return sub_cookie
                time.sleep(3)
                continue
            
            # 20100000 = 确认成功
            if ret == 20100000:
                logger.info("✅ 确认成功，获取 Cookie...")
                alt = data.get('alt') if isinstance(data, dict) else None
                if alt:
                    saved_alt = alt
                    self.session.get(
                        f"https://passport.weibo.com/sso/v2/login?entry=miniblog&alt={alt}&type=3",
                        allow_redirects=True
                    )
                    sub_cookie = self.session.cookies.get('SUB')
                    if sub_cookie:
                        logger.info("✅ 扫码成功，获取到新Cookie")
                        self.save_qrcode_status(success=False)
                        github_output = os.environ.get('GITHUB_OUTPUT', '')
                        if github_output:
                            with open(github_output, 'a') as f:
                                f.write(f'NEW_SUB_COOKIE={sub_cookie}\n')
                        else:
                            print(f"::set-output name=NEW_SUB_COOKIE::{sub_cookie}")
                        return sub_cookie
                time.sleep(3)
                continue
            
            time.sleep(3)
        
        # 超时：正常模式发送按钮，手动触发模式不发送
        if not trigger_only:
            logger.warning("⏰ 扫码超时，发送触发按钮...")
            self.send_timeout_button()
        else:
            logger.warning("⏰ 扫码超时，请重新手动触发")
        return None
    
    def send_timeout_button(self):
        """发送超时按钮通知"""
        token = self.get_feishu_token()
        if not token:
            return
        
        github_url = f"https://github.com/{GITHUB_REPO}/actions/workflows/main.yml"
        
        elements = [
            {"tag": "div", "text": {"tag": "lark_md", "content": "⏰ 二维码已过期，未及时扫描"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": "🔐 请点击下方按钮获取新二维码"}},
            {
                "tag": "action",
                "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": "🔄 获取新二维码"}, "url": github_url, "type": "primary"}]
            },
            {"tag": "div", "text": {"tag": "lark_md", "content": "💡 点击按钮后在 GitHub Actions 页面点击【Run workflow】即可"}}
        ]
        
        card = {
            "header": {"title": {"tag": "plain_text", "content": "⏰ 扫码超时"}, "template": "orange"},
            "elements": elements
        }
        
        try:
            url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
            payload = {"receive_id": self.feishu_chat_id, "msg_type": "interactive", "content": json.dumps(card)}
            r = requests.post(url, json=payload, headers={'Authorization': f'Bearer {token}'}, timeout=10)
            logger.info(f"📤 超时按钮通知已发送: {r.json().get('code') == 0}")
        except Exception as e:
            logger.error(f"❌ 发送超时按钮失败: {e}")

# ---------- 配置 ----------
GROUP_ID = '5159683220312291'
MAX_WORKERS = 10
PAGE_LIMIT = 20
# 微博Cookie (从浏览器F12 Headers中提取)
DEFAULT_SUB_COOKIE = "_2A25EvlvaDeRhGeFJ7FoY8SfEyzuIHXVnstESrDV6PUJbktANLWHikW1NfwLa8WGEMJdHVbVkEaB4udpifyizasVP"
# 飞书应用配置（用于发送图片消息）
DEFAULT_FEISHU_APP_ID = "cli_a933badfd57bdbde"
DEFAULT_FEISHU_APP_SECRET = "zliAQFZ61YOVdhSz8vecahozbGz6Ym5j"
PROXIES_SETTING = {"http": None, "https": None}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== 分类器关键词库（基于人工审核224条误判案例优化）==========

KEYWORDS_RECALL = ['召回', '赔付', '补偿', '翻车', '致歉', '搞反了', '做错', '退货', '退款', '假店', '骗子', '避坑']
KEYWORDS_INVENTORY = ['余量', '微瑕', 'B品', '福袋', '孤品', '掉落', '库存', '断码', '捡漏']
KEYWORDS_DEPOSIT = ['意向金', '定金', '订金', '1元链接', '一元链接', '提前购', '预定']
KEYWORDS_LUCKYDRAW = ['抽奖', '转发抽奖', '关注转发', '抽', '开奖', '中奖', '福利抽奖', '免费送']

KEYWORDS_SALE_STRONG = ['补款', '尾款', '现货链接', '开售', '补货', '现货上架', '开启购买', '已上架', '发售', '提前购', '明日上架', '即将上架', '开启预售', '现货上新', '今晚6点', '压轴', '必冲', '开冲']
KEYWORDS_LAST_CHANCE = ['最后一次', '最后一批', '最后亿次']

KEYWORDS_SALE_ACTION = ['上架', '释放', '上新', '开拍', '出货', '不见不散', '上链接', '开链接', '来袭', '冲', '开冲']

KEYWORDS_LOGISTICS = ['发货', '发出', '发走']
KEYWORDS_TIME = ['今晚', '明晚', '后天', '20:00', '8点', '八点', '19:00', '7点', '七点', '今天', '明天', '周三', '周四', '周五', '周六', '周日', '周一', '周二', '明日', '今日', '6点', '7点', '6:', '7:', '8:', '19:', '20:']

KEYWORDS_EXCLUDE = [
    '进度', '打版', '产前', '确认样', '下周', '月底', '预览', '选款', '看下', '意见', '打样', '路透', '期待', 
    '预告', '放假', '复工', '通知', '瑕疵', '工人号', '大货', '买家秀', '瑕疵品', '有问题', '仓库', 
    '上身', '上效果图', '上强度', '试穿', '上图', '上身效果', '身图', '测评', '对比', 
    '讲解', '视频', '鉴赏', '细节', '介绍'
]

KEYWORDS_SHANG_CLEAN = ['上身', '上图', '上效果', '上身效果', '身图', '试穿', '上强度', '安排上', '上衣', '上装']

# 模糊时间词
KEYWORDS_VAGUE_TIME = [
    '年后', '年后上新', '年后出', '年后春天', '年后上架', '开春', '春天上新',
    '近期', '近日', '这两天', '过两天', '最近',
    '即将', '即将上架', '即将开启', '马上',
    '预计', '预计这', '预计下',
    '未来', '后续', '之后'
]

# 进度词
KEYWORDS_PROGRESS = [
    '质检中', '打包中', '后整中', '制作中', '准备中', '进行中', 
    '操作中', '生产中', '制作过程', '打版中', '备货中',
    '陆续出货', '陆续发', '正在', '忙着'
]

# 通知公告词
KEYWORDS_NOTICE = ['通知', '公告', '警示', '警告', '提醒', '声明', '改名', '变更']

def classify_post(text):
    """对单条帖子进行分类 - 工业级v2.0"""
    text_lower = text.lower()
    has_link = 'http' in text or 'https' in text or 't.cn' in text or '微店' in text
    
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    title = lines[0] if lines else ""
    
    # 文本清洗
    text_cleaned = text
    for kw in KEYWORDS_SHANG_CLEAN:
        text_cleaned = text_cleaned.replace(kw, '')
    
    # ========== 提前排除逻辑 ==========
    
    # 检查通知公告类
    if any(kw in text for kw in KEYWORDS_NOTICE):
        if not any(kw in text for kw in KEYWORDS_SALE_STRONG):
            return "[X] 垃圾桶", "通知公告类"
    
    # 检查进度更新类
    if any(kw in text for kw in KEYWORDS_PROGRESS):
        if not ('现货' in text and ('可拍' in text or has_link)):
            return "[X] 垃圾桶", "进度更新"
    
    # 检查模糊时间预告
    has_vague_time = any(kw in text for kw in KEYWORDS_VAGUE_TIME)
    if has_vague_time:
        has_specific_date = bool(re.search(r'\d{1,2}月\d{1,2}[号日]?|\d{1,2}[./]\d{1,2}[号日]?', text))
        if not has_specific_date:
            if not (has_link and any(kw in text for kw in ['上架', '释放', '开拍', '链接'])):
                return "[X] 垃圾桶", "模糊时间预告"
    
    # 极短文本严格处理
    if len(text) < 20:
        if not (has_link and any(kw in text for kw in ['上架', '释放', '开拍', '链接', '冲'])):
            return "[X] 垃圾桶", "极短文本信息不足"
    
    # ========== 原有判断逻辑 ==========
    
    # 1. 优先判断：重大售后/召回
    for kw in KEYWORDS_RECALL:
        if kw in text:
            return "[P] 售后/避坑", "命中: " + kw
    
    # 2. 判断：抽奖（需要在正式发售之前判断，避免抽奖被误判为发售）
    has_lottery = any(kw in text for kw in KEYWORDS_LUCKYDRAW)
    has_lottery_rule = '抽奖规则' in text or '规则如下' in text or '转发' in text
    if has_lottery and has_lottery_rule:
        return "[P] 抽奖", "命中: 抽奖规则"
    
    # 3. 判断：意向金/定金
    for kw in KEYWORDS_DEPOSIT:
        if kw in text:
            return "[P] 意向金/定金", "命中: " + kw
    
    # 3. 判断：库存/B品/捡漏
    has_inventory = any(kw in text for kw in KEYWORDS_INVENTORY)
    has_action = any(kw in text for kw in KEYWORDS_SALE_ACTION + ['拍', '链接', '秒发'])
    if has_inventory and (has_action or has_link):
        matched_kw = next((kw for kw in KEYWORDS_INVENTORY if kw in text), '库存类')
        return "[P] 捡漏/余量", "命中: " + matched_kw
    
    # 4. 判断：正式发售
    
    # A. 预告处理
    if '预告' in title or '预告' in text:
        has_real_signal = any(kw in text for kw in KEYWORDS_TIME + KEYWORDS_SALE_ACTION + ['开售', '上架', '释放', '补货', '提前购'])
        has_specific_date = bool(re.search(r'\d{1,2}月\d{1,2}[号日]?|\d{1,2}[./]\d{1,2}[号日]?', text))
        if not (has_real_signal and (has_specific_date or has_link)):
            return "[X] 垃圾桶", "纯预告无具体时间"
    
    # B. 强特征检查
    has_last_chance = any(kw in text for kw in KEYWORDS_LAST_CHANCE)
    is_strong_sale = any(kw in text for kw in KEYWORDS_SALE_STRONG)
    is_strong_sale_title = any(kw in title for kw in KEYWORDS_SALE_STRONG + KEYWORDS_SALE_ACTION)
    
    if is_strong_sale or is_strong_sale_title:
        matched_kw = next((kw for kw in KEYWORDS_SALE_STRONG if kw in text), '发售强关键词')
        return "[P] 正式发售", "命中: " + matched_kw
    
    if has_last_chance and (any(kw in text for kw in KEYWORDS_SALE_ACTION) or has_link):
        return "[P] 正式发售", "命中: 最后一次发售"
    
    # C. 链接权重逻辑
    if has_link:
        if any(kw in text for kw in KEYWORDS_TIME):
            return "[P] 正式发售", "命中: 链接+时间"
        if any(kw in text for kw in KEYWORDS_SALE_ACTION + ['拍', '秒发']):
            return "[P] 正式发售", "命中: 链接+动作"
        
        if len(text) < 30 and not any(kw in text for kw in ['买家秀', '参考', '对比']):
             return "[P] 正式发售", "命中: 短文本+链接"

        title_blacklist = ['买家秀', '通知', '放假', '参考', '测评', '选款', '视频分享', '进度', '对比', '详解', '欣赏', '分享', '选选', '选包包', '讲解', '介绍']
        if not any(kw in title for kw in title_blacklist):
             if any(kw in text for kw in ['现货', '发售', '上架', '开售', '补货', '尾款', '压轴', '福利', '限量', '最后', '链接']):
                 return "[P] 正式发售", "命中: 链接+弱发售词"
    
    # 准备弱逻辑变量
    has_date_sale = bool(re.search(r'\d{1,2}[.月]\d{1,2}[号日]?\s*.*(上架|开售|开拍|补货|链接|拍|释放)', text))
    has_time_trigger = any(kw in text for kw in KEYWORDS_TIME) and any(kw in text for kw in KEYWORDS_SALE_ACTION + ['开售'])
    is_excluded = any(kw in text for kw in KEYWORDS_EXCLUDE)
    
    # D. 弱逻辑组合
    has_time_trigger_title = any(kw in title for kw in KEYWORDS_TIME) and any(kw in title for kw in KEYWORDS_SALE_ACTION)
    if has_time_trigger_title:
        if not any(kw in title for kw in KEYWORDS_EXCLUDE):
            return "[P] 正式发售", "命中: 标题时间+动作"
    
    if has_date_sale and not is_excluded:
        return "[P] 正式发售", "命中: 日期+上架"
    
    # E. 终极清洗判断：单字"上"
    if has_time_trigger and not is_excluded:
        return "[P] 正式发售", "命中: 时间+动作"

    if any(kw in text for kw in KEYWORDS_TIME) and not is_excluded:
        if '上' in text_cleaned and len(text) < 200:
             if not any(kw in text[:100] for kw in KEYWORDS_VAGUE_TIME):
                return "[P] 正式发售", "命中: 时间+单字'上'(清洗后)"

    # F. 物流词过滤
    if any(kw in text for kw in KEYWORDS_LOGISTICS):
        if ('现货' in text or '可拍' in text or '链接' in text) and any(kw in text for kw in KEYWORDS_TIME):
            return "[P] 正式发售", "命中: 现货发售"
    
    return "[X] 垃圾桶", "未命中"

# ---------- 智能评分器 (保持原样，省略部分代码以节省篇幅，逻辑不变) ----------
# ... (这里把之前代码中的 SmartLaunchDetector 类原封不动放进来) ...
class SmartLaunchDetector:
    def __init__(self):
        self.ULTIMATE_LAUNCH_KEYWORDS = {'现货上架', '已上架', '已开售', '开启购买', '释放库存'}
        self.LAUNCH_PATTERNS = {
            r'(\d{1,2}([:：]|\.)\d{2}|[0-9一二三四五六七八九十]+点).*?(\S{0,20}).*?(上架|开售|发售|补款|释放|开拍|提前购|会员先购|预售|开启预售|售价|特惠|抢购|秒杀)': 85,
            r'(今晚|明晚|今天|明天|周[一二三四五六日天]).*?(\d{1,2}([:：]|\.)\d{2}|[0-9一二三四五六七八九十]+点)': 40, 
        }
        self.STRONG_TIME_KEYWORDS = {'今晚': 30, '明晚': 30, '今晚八点': 35, '今晚8点': 35, '明天': 25}
        self.TIME_PATTERNS = {r'\d{1,2}[:：]\d{2}': 35, r'[0-9一二三四五六七八九十]+点': 30}
        self.ACTION_KEYWORDS = {'现货上架': 40, '上架': 35, '发售': 25, '开售': 25, '补款': 45, '预售': 45, '抢购': 40}
        self.SCORE_THRESHOLD = 45

    def check(self, text: str) -> Union[bool, Dict[str, Any]]:
        if not text: return False
        # 使用更严格的条件，避免过度推送
        for w in self.ULTIMATE_LAUNCH_KEYWORDS:
            if w in text: return {'is_launch': True, 'type': '终极信号', 'time': '即时', 'action': w}
        
        # 只推送明确的开售/抢购信号，不推送普通的"上架"通知
        strict_keywords = {'已开售', '已上架', '开启购买', '释放库存', '补款', '开拍', '抢购', '秒杀', '特惠价', '售价', '会员先购', '提前购'}
        for kw in strict_keywords:
            if kw in text:
                # 同时要求有时间或数字，更精准
                if any(c in text for c in ['点', ':', '：', '晚', '今天', '明天', '号', '日']):
                    return {'is_launch': True, 'type': '开售信号', 'time': '待确认', 'action': kw}
        return False

# ---------- 核心解析类 ----------
class WeiboDataParser:
    def __init__(self, sub_cookie: str, webhook_url: Optional[str] = None, 
                 feishu_app_id: str = None, feishu_app_secret: str = None,
                 feishu_chat_id: str = None):
        self.sub_cookie = sub_cookie
        self.webhook_url = webhook_url
        self.detector = SmartLaunchDetector()
        # 飞书应用配置
        self.feishu_app_id = feishu_app_id
        self.feishu_app_secret = feishu_app_secret
        self.feishu_chat_id = feishu_chat_id
        self._feishu_token = None
        self._token_expire_time = 0

    def get_feishu_token(self) -> Optional[str]:
        """获取飞书access_token"""
        if not self.feishu_app_id or not self.feishu_app_secret:
            return None
        
        # 检查缓存是否有效（提前5分钟刷新）
        if self._feishu_token and time.time() < self._token_expire_time - 300:
            return self._feishu_token
        
        try:
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            data = {
                "app_id": self.feishu_app_id,
                "app_secret": self.feishu_app_secret
            }
            r = requests.post(url, json=data, timeout=10)
            result = r.json()
            
            if result.get('code') == 0:
                self._feishu_token = result.get('tenant_access_token')
                self._token_expire_time = time.time() + result.get('expire', 7200)
                logger.info("🔑 飞书Token获取成功")
                return self._feishu_token
            else:
                logger.error(f"飞书Token获取失败: {result}")
                return None
        except Exception as e:
            logger.error(f"飞书Token请求异常: {e}")
            return None

    def upload_image_to_feishu(self, image_url: str) -> Optional[str]:
        """下载微博图片并上传到飞书，返回image_key"""
        if not self.feishu_app_id or not self.feishu_app_secret:
            return None
        
        token = self.get_feishu_token()
        if not token:
            return None
        
        try:
            # 下载微博图片 - 使用完整请求头避免 403
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Referer': 'https://weibo.com/',
            }
            resp = requests.get(image_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"图片下载失败: HTTP {resp.status_code}")
                return None
            
            # 上传到飞书
            upload_url = "https://open.feishu.cn/open-apis/im/v1/images"
            files = {
                'image_type': (None, 'message'),
                'image': ('weibo.jpg', resp.content, 'image/jpeg')
            }
            headers = {
                'Authorization': f'Bearer {token}'
            }
            
            r = requests.post(upload_url, files=files, headers=headers, timeout=30)
            result = r.json()
            
            if result.get('code') == 0:
                image_key = result.get('data', {}).get('image_key')
                logger.info(f"📷 图片上传成功: {image_key}")
                return image_key
            else:
                logger.warning(f"图片上传失败: {result}")
                return None
        except Exception as e:
            logger.warning(f"图片上传异常: {e}")
            return None

    def send_feishu_card(self, msg_type: str, user_name: str, text: str, post_id: str, 
                          time_keyword: str, pic_urls: list, post_time: str = None) -> bool:
        """发送飞书富文本卡片消息 - 方案B：强调型"""
        if not self.feishu_app_id or not self.feishu_app_secret:
            logger.warning("未配置飞书应用，跳过消息发送")
            return False
        
        if not self.feishu_chat_id:
            logger.warning("未配置飞书 chat_id，跳过消息发送")
            return False
        
        token = self.get_feishu_token()
        if not token:
            logger.warning("获取飞书Token失败")
            return False
        
        try:
            # 构建卡片元素
            elements = []
            
            # 图片（支持多张，最多9张）
            if pic_urls:
                for i, pic_url in enumerate(pic_urls[:9]):  # 最多9张
                    image_key = self.upload_image_to_feishu(pic_url)
                    if image_key:
                        elements.append({
                            "tag": "img",
                            "img_key": image_key,
                            "alt": {"tag": "plain_text", "content": f"商品图片 {i+1}/{len(pic_urls)}"}
                        })
                    else:
                        elements.append({
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": f"📷 [图片{i+1}]({pic_url})"
                            }
                        })
            
            # 正文内容 - 保留更多字数，分行显示
            text_short = text[:150] + "..." if len(text) > 150 else text
            # 替换换行符为空格，避免格式混乱
            text_short = text_short.replace('\n', ' ')
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"💥 {text_short}"
                }
            })
            
            # 构建标题：🔥 【发售时间 · 发帖日期】用户 · 类型
            # 例如：🔥 【今晚8点 · 03-18 12:30】Luxe出品 · 正式发售
            if time_keyword and time_keyword != "未识别":
                if post_time:
                    title = f"🔥 【{time_keyword} · {post_time}】{user_name} · {msg_type}"
                else:
                    title = f"🔥 【{time_keyword}】{user_name} · {msg_type}"
            else:
                if post_time:
                    title = f"🔥 【{post_time}】{user_name} · {msg_type}"
                else:
                    title = f"🔥 {user_name} · {msg_type}"
            
            # 根据类型设置不同颜色
            color_map = {
                '正式发售': 'red',      # 红色 - 紧迫
                '捡漏/余量': 'orange',  # 橙色 - 稀缺
                '意向金/定金': 'purple', # 紫色 - 标记
                '售后/避坑': 'yellow',  # 黄色 - 提醒
                '抽奖': 'green',        # 绿色 - 福利
            }
            template_color = color_map.get(msg_type, 'red')
            
            # 飞书卡片消息格式
            card_msg = {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": title
                        },
                        "template": template_color
                    },
                    "elements": elements
                }
            }
            
            # 发送到群里
            url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            payload = {
                "receive_id": self.feishu_chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card_msg["card"])
            }
            
            r = requests.post(url, json=payload, headers=headers, timeout=10)
            result = r.json()
            
            if result.get('code') == 0:
                logger.info(f"✅ 飞书消息发送成功")
                return True
            else:
                logger.error(f"❌ 飞书消息发送失败: {result}")
                return False
            
        except Exception as e:
            logger.error(f"飞书消息发送失败: {e}")
            return False
    
    def extract_time_keyword(self, text: str) -> str:
        """提取时间关键词"""
        time_keywords = ['今晚', '明晚', '今天', '明天', '后天', '周三', '周四', '周五', 
                         '周六', '周日', '周一', '周二', '本周', '下周']
        time_patterns = [r'\d{1,2}[:：]\d{2}', r'\d{1,2}点', r'\d{1,2}月\d{1,2}[号日]']
        
        # 先检查关键词
        for kw in time_keywords:
            if kw in text:
                # 尝试找到更完整的时间表达
                idx = text.find(kw)
                # 取关键词前后10个字符
                start = max(0, idx - 5)
                end = min(len(text), idx + len(kw) + 10)
                return text[start:end].strip()
        
        # 再检查时间模式
        for pattern in time_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group()
        
        return "未识别"
    
    def format_post_time(self, created_at: str) -> str:
        """格式化发帖时间为 '03-18 12:30' 格式"""
        if not created_at:
            return None
        try:
            # 微博时间格式: "Wed Mar 18 12:30:00 +0800 2026"
            dt = datetime.strptime(created_at, '%a %b %d %H:%M:%S %z %Y')
            return dt.strftime('%m-%d %H:%M')
        except Exception:
            return None

    def download_weibo_image(self, status: Dict) -> Optional[str]:
        """下载微博图片并返回本地路径"""
        try:
            # 获取微博配图
            pics = status.get('pic_ids') or status.get('pics', [])
            if not pics:
                return None
            
            # 获取第一张图片
            pic_info = pics[0]
            if isinstance(pic_info, dict):
                pic_url = pic_info.get('large', {}).get('url') or pic_info.get('url', '')
            else:
                pic_url = str(pic_info)
            
            if not pic_url:
                return None
            
            # 如果是相对路径，补充域名
            if not pic_url.startswith('http'):
                pic_url = 'https:' + pic_url
            
            # 下载图片
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            resp = requests.get(pic_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return None
            
            # 保存到本地
            img_dir = 'images'
            os.makedirs(img_dir, exist_ok=True)
            filename = f"{status.get('idstr', 'unknown')}.jpg"
            filepath = os.path.join(img_dir, filename)
            
            with open(filepath, 'wb') as f:
                f.write(resp.content)
            
            logger.info(f"📷 已下载图片: {filename}")
            return filepath
        except Exception as e:
            logger.warning(f"图片下载失败: {e}")
            return None

    # ... (download_and_convert_image 等方法保持不变) ...

# ---------- 状态管理 ----------
STATUS_FILE = "last_processed_id.txt"

def load_status() -> dict:
    """从文件加载状态（包含 last_timestamp 和 cookie）"""
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content.startswith('{'):
                    # JSON 格式
                    data = json.loads(content)
                    # 兼容旧格式：只有 last_id
                    if 'last_id' in data and 'last_timestamp' not in data:
                        return {'last_timestamp': None, 'cookie': data.get('cookie')}
                    return data
                else:
                    # 兼容旧格式：只有 last_id
                    return {'last_timestamp': None, 'cookie': None}
        except Exception:
            pass
    return {'last_timestamp': None, 'cookie': None}

def save_status(timestamp: int = None, cookie: str = None):
    """保存状态到文件"""
    data = {'last_timestamp': timestamp, 'cookie': cookie}
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    if timestamp:
        from datetime import datetime
        dt = datetime.fromtimestamp(timestamp)
        logger.info(f"💾 状态已保存: timestamp={dt.strftime('%Y-%m-%d %H:%M:%S')}, cookie={'已保存' if cookie else '无'}")
    else:
        logger.info(f"💾 状态已保存: timestamp=None, cookie={'已保存' if cookie else '无'}")

# ---------- GitHub Actions 触发 ----------
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") or ""
GITHUB_REPO = os.getenv("GITHUB_REPO") or "wsxvg/-1"
GITHUB_WORKFLOW_ID = None  # 运行时获取

def get_default_branch():
    """获取仓库默认分支"""
    global GITHUB_REPO
    url = f"https://api.github.com/repos/{GITHUB_REPO}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json().get('default_branch', 'main')
    except:
        pass
    return 'main'

def get_workflow_id():
    """获取 workflow ID"""
    global GITHUB_WORKFLOW_ID
    if GITHUB_WORKFLOW_ID:
        return GITHUB_WORKFLOW_ID
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            for wf in data.get('workflows', []):
                if 'login' in wf['name'].lower():
                    GITHUB_WORKFLOW_ID = wf['id']
                    logger.info(f"🔗 找到登录 workflow: {wf['name']} (id={wf['id']})")
                    return GITHUB_WORKFLOW_ID
    except Exception as e:
        logger.error(f"获取 workflow 失败: {e}")
    return None

def trigger_github_workflow() -> bool:
    """触发 GitHub Actions 工作流扫码登录"""
    if not GITHUB_TOKEN:
        logger.warning("未配置 GITHUB_TOKEN，无法触发 Actions")
        return False
    
    workflow_id = get_workflow_id()
    if not workflow_id:
        logger.error("找不到登录 workflow")
        return False
    
    default_branch = get_default_branch()
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow_id}/dispatches"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }
    data = {"ref": default_branch}
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        if response.status_code == 204:
            logger.info("✅ 已触发 GitHub Actions 扫码登录")
            return True
        else:
            logger.error(f"触发失败: {response.status_code} {response.text}")
            return False
    except Exception as e:
        logger.error(f"触发异常: {e}")
        return False

# ---------- 外部 API ----------
def fetch_one_page(sub_cookie: str, max_id: Optional[str] = None) -> Dict[str, Any]:
    url = 'https://weibo.com/ajax/feed/groupstimeline'
    params = {'list_id': GROUP_ID, 'count': '50'}
    if max_id: params['max_id'] = max_id
    headers = {
        'accept': 'application/json',
        'referer': f'https://weibo.com/mygroups?gid={GROUP_ID}',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    cookies = {'SUB': sub_cookie}
    try:
        r = requests.get(url, params=params, headers=headers, cookies=cookies, timeout=15)
        # 显式打印状态，方便 debug
        if r.status_code != 200:
            logger.warning(f"⚠️ API返回状态码: {r.status_code}")
        return r.json()
    except Exception as e:
        logger.error(f'API 请求异常: {e}')
        return {}

def check_cookie_status(sub_cookie: str) -> bool:
    """验证 Cookie 是否有效"""
    logger.info('🔍 正在验证 Cookie 有效性...')
    url = 'https://weibo.com/ajax/feed/groupstimeline'
    params = {'list_id': GROUP_ID, 'count': '1'}
    headers = {'user-agent': 'Mozilla/5.0', 'referer': f'https://weibo.com/mygroups?gid={GROUP_ID}'}
    try:
        r = requests.get(url, params=params, headers=headers, cookies={'SUB': sub_cookie}, timeout=10, allow_redirects=False)
        
        # 如果遇到 302 跳转到 passport 或者 414/403，肯定失效
        if r.status_code in [302, 403, 414]:
            logger.error(f"🚨 Cookie 失效 (HTTP {r.status_code})")
            return False
            
        # 检查 JSON 内容
        try:
            data = r.json()
            if data.get('ok') == 1:
                logger.info("✅ Cookie 有效")
                return True
            else:
                logger.error(f"🚨 Cookie 失效 (API返回 ok!=1): {data}")
                return False
        except:
            logger.error("🚨 Cookie 失效 (无法解析JSON)")
            return False
            
    except Exception as e:
        logger.error(f"🚨 验证过程出错: {e}")
        return False

def execute_monitoring(sub_cookie: str, feishu_app_id: str = None, 
                        feishu_app_secret: str = None, feishu_chat_id: str = None):
    # 读取上次抓取的时间戳
    status = load_status()
    last_timestamp = status.get('last_timestamp')
    
    if last_timestamp:
        last_dt = datetime.fromtimestamp(last_timestamp)
        logger.info(f"📌 上次抓取时间: {last_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        logger.info("📌 首次运行，将抓取近12小时的数据")
        # 首次运行：抓取近12小时（避免一次太多）
        last_timestamp = (datetime.now() - timedelta(hours=12)).timestamp()
        logger.info(f"📌 起始时间: {datetime.fromtimestamp(last_timestamp).strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 先验证 Cookie，如果不通直接抛出异常，不浪费时间抓取
    if not check_cookie_status(sub_cookie):
        raise ConnectionRefusedError("COOKIE_EXPIRED")

    # 2. 增量抓取数据（只抓取新数据）
    all_stat = []
    max_id = None
    page = 0
    
    while True:
        data = fetch_one_page(sub_cookie, max_id)
        statuses = data.get('statuses', [])
        if not statuses:
            logger.info("⚠️ 没有更多数据了")
            break
        
        # 筛选新帖子：只保留时间戳 > last_timestamp 的
        new_statuses = []
        oldest_timestamp = None
        
        for s in statuses:
            created_at = s.get('created_at', '')
            if not created_at:
                continue
            
            try:
                post_dt = datetime.strptime(created_at, '%a %b %d %H:%M:%S %z %Y')
                post_timestamp = post_dt.timestamp()
            except Exception:
                continue
            
            # 记录这一页最旧的时间戳
            if oldest_timestamp is None or post_timestamp < oldest_timestamp:
                oldest_timestamp = post_timestamp
            
            # 只保留比 last_timestamp 新的帖子
            if post_timestamp > last_timestamp:
                new_statuses.append(s)
        
        if new_statuses:
            all_stat.extend(new_statuses)
            oldest_post = new_statuses[-1] if new_statuses else None
            oldest_time = oldest_post.get('created_at', '') if oldest_post else ''
            logger.info(f"� 第{page+1}页: 新增 {len(new_statuses)} 条，累计 {len(all_stat)} 条")
            if oldest_time:
                try:
                    dt = datetime.strptime(oldest_time, '%a %b %d %H:%M:%S %z %Y')
                    logger.info(f"   最旧帖子时间: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                except:
                    pass
        
        # 如果这一页最旧的时间戳 <= last_timestamp，说明已经抓完了，停止
        if oldest_timestamp is not None and oldest_timestamp <= last_timestamp:
            logger.info(f"✅ 已到达上次抓取位置，停止增量抓取")
            break
        
        max_id = data.get('max_id_str')
        if not max_id:
            logger.info("⚠️ 已到达数据尽头")
            break
        
        page += 1
        time.sleep(1)
        
        # 安全限制：最多抓10页（约500条）
        if page >= 10:
            logger.info(f"⚠️ 达到增量抓取最大页数限制 (共 {len(all_stat)} 条)")
            break

    if not all_stat:
        logger.info("ℹ️ 未发现新微博")
        return

    logger.info(f"📊 共抓取 {len(all_stat)} 条新微博")

    # 按时间倒序发送（最新的先发）
    all_stat.reverse()
    
    # 分类并推送有效帖子到飞书
    parser = WeiboDataParser(sub_cookie, None, feishu_app_id, feishu_app_secret, feishu_chat_id)
    
    stats = {'[X] 垃圾桶': 0, '[P] 正式发售': 0, '[P] 捡漏/余量': 0, '[P] 意向金/定金': 0, '[P] 售后/避坑': 0}
    
    for s in all_stat:
        text = s.get('text_raw', s.get('text', ''))
        text = re.sub(r'<[^>]+>', '', text).strip()
        
        # 过滤：正文太短（只有链接或几个字）的低质量帖子
        text_without_link = re.sub(r'https?://t\.cn/\w+', '', text).strip()
        if len(text_without_link) < 10:
            logger.info(f"🚫 过滤低质量帖子（正文太短）: {text[:30]}...")
            continue
        
        # 调用分类器
        category, reason = classify_post(text)
        stats[category] = stats.get(category, 0) + 1
        
        # 只推送有效帖子到飞书
        if category.startswith('[P]') and feishu_app_id and feishu_app_secret:
            user_name = s.get('user', {}).get('screen_name', '') if isinstance(s.get('user'), dict) else ''
            post_id = s.get('idstr', '')
            
            # 获取图片 - 优先使用 pic_infos，其次检查视频
            pic_infos = s.get('pic_infos', {})
            pic_urls = []
            
            # 1. 先尝试获取普通图片（最多9张）
            for pic_id, info in list(pic_infos.items())[:9]:
                if isinstance(info, dict):
                    large = info.get('large', {})
                    if isinstance(large, dict):
                        pic_url = large.get('url', '')
                    else:
                        pic_url = str(large)
                    if pic_url:
                        pic_urls.append(pic_url)
            
            # 2. 如果没有图片，检查是否有视频（page_info）
            if not pic_urls:
                page_info = s.get('page_info', {})
                if isinstance(page_info, dict):
                    # 视频封面图
                    video_thumbnail = page_info.get('page_pic', {}).get('url') if isinstance(page_info.get('page_pic'), dict) else page_info.get('page_pic', '')
                    if video_thumbnail:
                        pic_urls.append(video_thumbnail)
                        logger.info(f"🎬 获取视频封面: {video_thumbnail}")
            
            if pic_urls:
                logger.info(f"🔍 获取到 {len(pic_urls)} 张图片")
            
            try:
                # 提取时间关键词
                time_keyword = parser.extract_time_keyword(text)
                
                # 提取发帖时间
                created_at = s.get('created_at', '')
                post_time = parser.format_post_time(created_at)
                
                # 构建飞书消息
                msg_type = category.replace('[P] ', '')
                
                success = parser.send_feishu_card(
                    msg_type=msg_type,
                    user_name=user_name,
                    text=text,
                    post_id=post_id,
                    time_keyword=time_keyword,
                    pic_urls=pic_urls,
                    post_time=post_time
                )
                if success:
                    logger.info(f"📤 已推送: {msg_type} - {text[:30]}...")
                else:
                    logger.warning(f"⚠️ 推送失败: {msg_type}")
            except Exception as e:
                logger.error(f"❌ 推送异常: {e}")
    
    logger.info("📊 本次分类统计:")
    for cat, count in sorted(stats.items(), key=lambda x: -x[1]):
        if count > 0:
            logger.info(f"  {cat}: {count}")
    
    valid_count = sum(v for k, v in stats.items() if k.startswith('[P]'))
    if len(all_stat) > 0:
        logger.info(f"✅ 本次有效帖子: {valid_count} 条 ({valid_count/len(all_stat)*100:.1f}%)")
    
    # 更新last_timestamp（保存最新帖子的时间戳）
    if all_stat:
        # 找到最新帖子的时间戳
        latest_timestamp = None
        for s in all_stat:
            created_at = s.get('created_at', '')
            if created_at:
                try:
                    post_dt = datetime.strptime(created_at, '%a %b %d %H:%M:%S %z %Y')
                    post_timestamp = post_dt.timestamp()
                    if latest_timestamp is None or post_timestamp > latest_timestamp:
                        latest_timestamp = post_timestamp
                except:
                    pass
        
        if latest_timestamp:
            # 读取当前状态，保留 cookie
            current_status = load_status()
            save_status(int(latest_timestamp), current_status.get('cookie'))
            logger.info(f"📌 已更新抓取时间戳: {datetime.fromtimestamp(latest_timestamp).strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == '__main__':
    import argparse
    from urllib.parse import urlparse, parse_qs
    
    parser = argparse.ArgumentParser(description='微博监控')
    parser.add_argument('--test', action='store_true', help='发送测试消息')
    parser.add_argument('--trigger', action='store_true', help='手动触发获取二维码（跳过冷却）')
    args = parser.parse_args()
    
    # 加载状态
    status = load_status()
    last_id = status.get('last_id', '0')
    saved_cookie = status.get('cookie')
    
    # 优先从环境变量读取，其次从保存的状态，最后用默认值
    cookie = os.getenv('WEIBO_SUB_COOKIE') or saved_cookie or DEFAULT_SUB_COOKIE
    feishu_app_id = os.getenv('FEISHU_APP_ID') or DEFAULT_FEISHU_APP_ID
    feishu_app_secret = os.getenv('FEISHU_APP_SECRET') or DEFAULT_FEISHU_APP_SECRET
    feishu_chat_id = os.getenv('FEISHU_CHAT_ID') or "oc_727fbcc6d94e338a6520f0669c8e0bfe"
    
    # 测试模式
    if args.test:
        if not feishu_app_id or not feishu_app_secret:
            print("❌ 未配置 FEISHU_APP_ID 或 FEISHU_APP_SECRET")
            sys.exit(1)
        
        parser = WeiboDataParser("", None, feishu_app_id, feishu_app_secret, feishu_chat_id)
        
        # 上传测试图片
        import io
        from PIL import Image
        
        img = Image.new('RGB', (300, 300), color='red')
        buf = io.BytesIO()
        img.save(buf, format='JPEG')
        
        token = parser.get_feishu_token()
        upload_url = "https://open.feishu.cn/open-apis/im/v1/images"
        files = {'image_type': (None, 'message'), 'image': ('test.jpg', buf.getvalue(), 'image/jpeg')}
        headers = {'Authorization': f'Bearer {token}'}
        r = requests.post(upload_url, files=files, headers=headers, timeout=30)
        result = r.json()
        
        if result.get('code') != 0:
            print(f"❌ 图片上传失败: {result}")
            sys.exit(1)
        
        image_key = result['data']['image_key']
        print(f"✅ 图片上传成功: {image_key}")
        
        # 模拟 pic_urls（实际是从微博下载的图片URL）
        # 这里直接用 image_key 发送
        success = parser.send_feishu_card(
            msg_type="正式发售",
            user_name="测试店铺",
            text="这是一条测试消息，今晚8点准时开售，限量100件！冲冲冲！",
            post_id="1234567890",
            time_keyword="今晚8点",
            pic_urls=["https://example.com/test.jpg"],
            post_time="03-18 12:30"
        )
        
        if success:
            print("✅ 测试消息已发送成功！")
        else:
            print("❌ 消息发送失败")
        sys.exit(0)
    
    # 手动登录模式（带轮询）
    if '--login' in sys.argv:
        sys.argv.remove('--login')
        logger.info("🚀 手动触发扫码登录（带轮询）...")
        login_bot = WeiboQRLogin(feishu_app_id, feishu_app_secret, feishu_chat_id)
        new_sub = login_bot.run_login_process(trigger_only=False)
        if new_sub:
            current_status = load_status()
            save_status(current_status.get('last_timestamp'), new_sub)
            print(f"\n✅ 登录成功！状态已保存到 {STATUS_FILE}")
            print(f"SUB: {new_sub}")
        else:
            print("❌ 登录失败或超时")
        sys.exit(0)
    
    # 手动触发模式（跳过冷却，带轮询）
    if '--trigger' in sys.argv:
        sys.argv.remove('--trigger')
        logger.info("🚀 手动触发获取二维码（跳过冷却，带轮询）...")
        login_bot = WeiboQRLogin(feishu_app_id, feishu_app_secret, feishu_chat_id)
        new_cookie = login_bot.run_login_process(trigger_only=True)
        
        if new_cookie:
            # 扫码成功，保存到 TXT
            current_status = load_status()
            save_status(current_status.get('last_timestamp'), new_cookie)
            logger.info("✅ 新 Cookie 已保存到 TXT")
            print(f"\n✅ 登录成功！Cookie: {new_cookie[:20]}...")
            
            # 立即重新运行监控
            logger.info("🔄 立即重新运行监控...")
            execute_monitoring(new_cookie, feishu_app_id, feishu_app_secret, feishu_chat_id)
            sys.exit(0)
        else:
            print("\n❌ 登录失败或超时")
        sys.exit(0)
    
    # 正常监控模式
    if not cookie or "请替换" in cookie:
        logger.error("🚨 环境变量 WEIBO_SUB_COOKIE 未配置")
        sys.exit(1)

    try:
        execute_monitoring(cookie, feishu_app_id, feishu_app_secret, feishu_chat_id)
    except ConnectionRefusedError as e:
        if str(e) == "COOKIE_EXPIRED":
            logger.info("\n⚡ [AutoFix] 检测到 Cookie 失效，开始扫码登录...")
            try:
                login_bot = WeiboQRLogin(feishu_app_id, feishu_app_secret, feishu_chat_id)
                
                # 正常模式：发二维码 + 轮询 + 超时发按钮
                new_cookie = login_bot.run_login_process(trigger_only=False)
                
                if new_cookie:
                    # 扫码成功，保存到 TXT
                    current_status = load_status()
                    save_status(current_status.get('last_timestamp'), new_cookie)
                    logger.info("✅ 新 Cookie 已保存到 TXT")
                    print(f"\n✅ 登录成功！Cookie: {new_cookie[:20]}...")
                    
                    # 立即重新运行监控
                    logger.info("🔄 立即重新运行监控...")
                    execute_monitoring(new_cookie, feishu_app_id, feishu_app_secret, feishu_chat_id)
                    sys.exit(0)
                else:
                    # 超时或失败，已发送按钮
                    logger.info("💡 超时未扫描，请前往飞书点击按钮重新触发")
                
                sys.exit(0)
            except Exception as ex:
                logger.error(f"❌ 扫码登录失败: {ex}")
                sys.exit(1)
        else:
            sys.exit(1)

