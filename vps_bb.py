#!/usr/bin/env python3
import os
import sys
import json
import psutil
import subprocess
from datetime import datetime

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=4)

def set_token():
    cfg = load_config()
    token = input("请输入新的 Telegram Bot Token: ")
    cfg['bot_token'] = token
    save_config(cfg)
    print("✅ Bot Token 已更新！")

def set_admin():
    cfg = load_config()
    admin_id = input("请输入新的 Admin ID: ")
    cfg['admin_id'] = int(admin_id)
    save_config(cfg)
    print("✅ Admin ID 已更新！")

def set_limit():
    cfg = load_config()
    limit = input("请输入流量阈值(GB, 0为不限制): ")
    cfg['limit_gb'] = int(limit)
    cfg['auto_shutdown'] = True if int(limit) > 0 else False
    save_config(cfg)
    print(f"✅ 流量阈值已更新为 {limit} GB")

def toggle_auto_shutdown():
    cfg = load_config()
    cfg['auto_shutdown'] = not cfg['auto_shutdown']
    save_config(cfg)
    print(f"✅ 自动关机已{'开启' if cfg['auto_shutdown'] else '关闭'}")

def show_status():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    uptime = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
    print("\n🖥 VPS 状态:")
    print(f"⏱ 开机时间: {uptime}")
    print(f"🧠 CPU 使用率: {cpu}%")
    print(f"🐏 内存: {mem.percent}% ({round(mem.used/1024**3,2)}G/{round(mem.total/1024**3,2)}G)")
    print(f"💾 硬盘: {disk.percent}% ({round(disk.used/1024**3,2)}G/{round(disk.total/1024**3,2)}G)\n")

def show_traffic():
    cfg = load_config()
    iface = cfg.get('vnstat_interface')
    try:
        result = subprocess.check_output("vnstat --json", shell=True).decode()
        data = json.loads(result)
        interface = None
        for i in data['interfaces']:
            if i['name'] == iface:
                interface = i
                break
        if not interface:
            interface = data['interfaces'][0]
        rx = round(interface['traffic']['month'][-1]['rx']/1024**3,2)
        tx = round(interface['traffic']['month'][-1]['tx']/1024**3,2)
        total = round(rx + tx, 2)
        print(f"\n📡 流量统计 ({interface['name']}):")
        print(f"⬇️ 下载: {rx} GB")
        print(f"⬆️ 上传: {tx} GB")
        print(f"📊 总计: {total} GB\n")
    except Exception as e:
        print(f"⚠️ 无法获取流量: {e}")

def reboot_vps():
    confirm = input("⚠️ 确定要重启 VPS 吗? (y/n): ")
    if confirm.lower() == 'y':
        print("🔄 正在重启...")
        os.system("reboot")

def shutdown_vps():
    confirm = input("⚠️ 确定要关机 VPS 吗? (y/n): ")
    if confirm.lower() == 'y':
        print("🛑 正在关机...")
        os.system("shutdown -h now")

def menu():
    while True:
        print("""
========================
   VPS 快捷管理面板
========================
1) 修改 Telegram Token
2) 修改 Admin ID
3) 修改流量阈值
4) 开/关自动关机
5) 查看 VPS 状态
6) 查看流量统计
7) 重启 VPS
8) 关机 VPS
0) 退出
========================
""")
        choice = input("请输入选项: ")
        if choice == '1':
            set_token()
        elif choice == '2':
            set_admin()
        elif choice == '3':
            set_limit()
        elif choice == '4':
            toggle_auto_shutdown()
        elif choice == '5':
            show_status()
        elif choice == '6':
            show_traffic()
        elif choice == '7':
            reboot_vps()
        elif choice == '8':
            shutdown_vps()
        elif choice == '0':
            print("退出...")
            break
        else:
            print("❌ 无效选项，请重新输入！")

if __name__ == "__main__":
    menu()
