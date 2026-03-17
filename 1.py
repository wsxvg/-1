from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage.common import By
import time
import json
import os
import random
import base64
import io

# --- 配置 ---
FRIEND_LIST = ["徐雨栋", "刘洋", "小康", "老婆", "gqq", "初生", "申佳星", "还是瞌睡吧"]
MSG_CONTENT = "测试信息"
COOKIE_PATH = 'cookies.json'
FEISHU_WEBHOOK_URL = "YOUR_FEISHU_WEBHOOK_URL"  # 飞书 webhook 地址

def save_cookies(page, path):
    """保存 cookies"""
    cookies = page.cookies()
    # DrissionPage 返回的是 CookiesList，直接转 list
    cookie_list = list(cookies)
    # 清理不需要的字段
    clean_cookies = []
    for ck in cookie_list:
        clean_ck = {k: v for k, v in ck.items() if k in ['name', 'value', 'domain', 'path', 'expires', 'secure', 'httpOnly']}
        clean_cookies.append(clean_ck)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(clean_cookies, f, ensure_ascii=False, indent=2)
    print(f"💾 Cookie 已保存到 {path}")

def load_cookies(page, path):
    """加载 cookies"""
    if not os.path.exists(path):
        return False
    try:
        with open(path, 'r', encoding='utf-8') as f:
            cookies = json.load(f)
            for ck in cookies:
                if 'domain' not in ck:
                    ck['domain'] = '.douyin.com'
                page.set.cookies(ck)
        return True
    except Exception as e:
        print(f"❌ Cookie 加载失败: {e}")
        return False

def send_qrcode_to_feishu(qrcode_base64):
    """发送二维码到飞书"""
    try:
        import requests
        payload = {
            "msg_type": "image",
            "content": {
                "image_key": qrcode_base64
            }
        }
        # 飞书图片上传需要先上传图片获取 image_key，这里简化处理
        # 实际使用时需要调用飞书上传图片 API
        print("📱 请扫描二维码登录抖音")
        return True
    except Exception as e:
        print(f"❌ 飞书推送失败: {e}")
        return False

def login_with_qrcode():
    """二维码登录流程"""
    co = ChromiumOptions()
    co.set_argument('--mute-audio')
    co.set_argument('--incognito')
    co.set_argument('--headless=new')  # GitHub Actions 用无头模式
    
    page = ChromiumPage(co)
    page.get('https://www.douyin.com')
    
    # 等待登录按钮出现
    try:
        # 尝试找到二维码登录入口
        login_btn = page.ele('xpath://a[contains(@href, "/passport/web/login")]', timeout=5)
        if login_btn:
            login_btn.click()
            time.sleep(2)
        
        # 等待二维码容器
        qr_container = page.ele('xpath://div[contains(@class, "qrcode")]', timeout=10)
        if qr_container:
            # 截图二维码
            qr_image = page.screenshot(qr_container)
            
            # 保存二维码
            qr_path = 'qrcode.png'
            with open(qr_path, 'wb') as f:
                f.write(qr_image)
            
            # 转 base64
            with open(qr_path, 'rb') as f:
                qr_base64 = base64.b64encode(f.read()).decode()
            
            # 发送到飞书
            send_qrcode_to_feishu(qr_base64)
            
            # 等待扫码成功（检测 URL 变化）
            print("⏳ 等待扫码登录...")
            page.wait.url_change('www.douyin.com', timeout=120)
            
            # 保存新 cookie
            save_cookies(page, COOKIE_PATH)
            print("✅ 登录成功，Cookie 已保存")
            return True
            
    except Exception as e:
        print(f"❌ 二维码登录失败: {e}")
        return False
    
    return False

def get_search_input(page):
    """搜索框全能定位"""
    locators = [
        'xpath://div[@id="imSaasContainerId"]//input',
        '.semi-input-default',
        '@placeholder=搜索'
    ]
    for loc in locators:
        el = page.ele(loc, timeout=1)
        if el:
            return el
    return None

def get_editor(page):
    """输入框全能定位"""
    locators = [
        'xpath://div[@id="imSaasContainerId"]//div[@contenteditable="true"]',
        'xpath://*[@id="imSaasContainerId"]/div[2]/div[2]/div[3]/div[2]/div/div[1]/div/div',
        '.public-DraftEditor-content'
    ]
    for loc in locators:
        el = page.ele(loc, timeout=1)
        if el:
            return el
    return None

def fast_send(page, name):
    print(f"\n🔎 目标: {name}")
    
    search_input = get_search_input(page)
    if not search_input:
        print("❌ 搜索框没出来，尝试刷新")
        page.refresh()
        time.sleep(3)
        search_input = get_search_input(page)
        if not search_input:
            return False

    search_input.click()
    search_input.input(name, clear=True)
    
    chat_btn = page.wait.ele_displayed('.SearchPanelitemchat_btn', timeout=4)
    if chat_btn:
        chat_btn.click()
        time.sleep(0.5)
        editor = get_editor(page)
        
        if editor:
            editor.click()
            editor.input(MSG_CONTENT)
            time.sleep(0.3)
            page.actions.key_down('ENTER').key_up('ENTER')
            print(f"✅ {name} 发送成功")
            return True
        else:
            print(f"❌ 找到人了，但是输入框死活定位不到")
    else:
        print(f"❌ 没搜到 {name}，或者没出现发私信按钮")
        
    return False

def check_login_status(page):
    """检查登录状态"""
    try:
        # 尝试访问需要登录的页面
        page.get('https://www.douyin.com/chat')
        time.sleep(2)
        
        # 检查是否跳转到登录页
        if 'passport' in page.url:
            return False
        
        # 检查是否存在登录相关的元素
        login_ele = page.ele('xpath://a[contains(@href, "/passport")]', timeout=2)
        if login_ele:
            return False
            
        return True
    except:
        return False

def main():
    co = ChromiumOptions()
    co.set_argument('--mute-audio')
    co.set_argument('--incognito')
    
    # GitHub Actions 环境检测
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        co.set_argument('--headless=new')
        co.set_argument('--no-sandbox')
    
    page = ChromiumPage(co)
    
    # 1. 尝试加载 cookie
    page.get('https://www.douyin.com')
    if os.path.exists(COOKIE_PATH):
        print("📂 尝试加载本地 Cookie...")
        if load_cookies(page, COOKIE_PATH):
            page.refresh()
            time.sleep(2)
            
        # 检查登录状态
        if not check_login_status(page):
            print("⚠️ Cookie 已过期，需要重新登录")
            page.quit()
            login_with_qrcode()
            return
    
    # 2. 如果没有 cookie 或已过期，执行二维码登录
    if not check_login_status(page):
        print("⚠️ 未登录，开始二维码登录流程")
        login_with_qrcode()
    
    # 3. 访问聊天页面
    page.get('https://www.douyin.com/chat')
    page.wait.ele_displayed('xpath://div[@id="imSaasContainerId"]', timeout=10)
    
    # 4. 处理密码验证
    pwd_input = page.ele('@type=password', timeout=1)
    if pwd_input:
        pwd_input.input("Wan1314520.")
        page.actions.key_down('ENTER').key_up('ENTER')
        time.sleep(2)
    
    # 5. 保存登录后的 cookie
    save_cookies(page, COOKIE_PATH)
    
    # 6. 开始发消息
    for friend in FRIEND_LIST:
        if page.ele('.chatDark', timeout=0.2):
            page.refresh()
            time.sleep(2)
            
        fast_send(page, friend)
        time.sleep(random.uniform(1.0, 2.0))
    
    print("\n✅ 所有流程执行完毕")
    page.quit()

if __name__ == '__main__':
    main()
