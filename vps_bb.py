#!/usr/bin/env python3
import os
import sys
import json
import psutil
import subprocess
from datetime import datetime
import shutil

VERSION = "v2.1.1"

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))
SHORTCUT_CMD = '/usr/local/bin/vps-bb'
SYSTEMD_SERVICE = '/etc/systemd/system/vpsbot.service'

# ===================== 颜色定义 =====================
RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"

# ===================== 工具函数 =====================
def clear_screen():
    os.system("clear")

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        print(f"{RED}❌ 保存配置失败: {e}{RESET}")

def safe_int_input(prompt):
    value = input(prompt).strip()
    if not value.isdigit():
        print(f"{RED}❌ 请输入有效数字！{RESET}")
        return None
    return int(value)

def progress_bar(percent, width=30):
    filled = int(width * percent / 100)
    bar = "█" * filled + "-" * (width - filled)
    if percent < 60:
        color = GREEN
    elif percent < 85:
        color = YELLOW
    else:
        color = RED
    return f"{color}[{bar}] {percent}%{RESET}"

# ===================== 设置功能 =====================
def set_token():
    cfg = load_config()
    token = input("请输入新的 Telegram Bot Token: ").strip()
    if not token:
        print(f"{RED}❌ Token 不能为空{RESET}")
        return
    cfg['bot_token'] = token
    save_config(cfg)
    print(f"{GREEN}✅ Bot Token 已更新！{RESET}")

def set_admin():
    cfg = load_config()
    admin_id = safe_int_input("请输入新的 Admin ID: ")
    if admin_id is None:
        return
    cfg['admin_id'] = admin_id
    save_config(cfg)
    print(f"{GREEN}✅ Admin ID 已更新！{RESET}")

def set_limit():
    cfg = load_config()
    limit = safe_int_input("请输入流量阈值(GB, 0为不限制): ")
    if limit is None:
        return
    cfg['limit_gb'] = limit
    cfg['auto_shutdown'] = True if limit > 0 else False
    save_config(cfg)
    print(f"{GREEN}✅ 流量阈值已更新为 {limit} GB{RESET}")

def toggle_auto_shutdown():
    cfg = load_config()
    cfg['auto_shutdown'] = not cfg.get('auto_shutdown', False)
    save_config(cfg)
    state = "开启" if cfg['auto_shutdown'] else "关闭"
    print(f"{GREEN if state=='开启' else RED}✅ 自动关机已{state}{RESET}")

# ===================== 状态显示 =====================
def show_status():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    uptime = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n{CYAN}{BOLD}🖥 VPS 状态{RESET}")
    print(f"⏱ 开机时间: {uptime}\n")

    print(f"🧠 CPU 使用率:")
    print(progress_bar(cpu))

    print(f"\n🐏 内存使用率:")
    print(progress_bar(mem.percent))

    print(f"\n💾 磁盘使用率:")
    print(progress_bar(disk.percent))
    print()

def show_traffic():
    cfg = load_config()
    iface = cfg.get('vnstat_interface')

    try:
        result = subprocess.check_output(["vnstat", "--json"])
        data = json.loads(result.decode())

        interface = None
        for i in data['interfaces']:
            if iface and i['name'] == iface:
                interface = i
                break

        if not interface:
            interface = data['interfaces'][0]

        rx = round(interface['traffic']['month'][-1]['rx']/1024**3, 2)
        tx = round(interface['traffic']['month'][-1]['tx']/1024**3, 2)
        total = round(rx + tx, 2)

        print(f"\n{CYAN}{BOLD}📡 流量统计 ({interface['name']}){RESET}")
        print(f"⬇️ 下载: {rx} GB")
        print(f"⬆️ 上传: {tx} GB")
        print(f"📊 总计: {total} GB\n")

    except FileNotFoundError:
        print(f"{RED}⚠️ 未安装 vnstat{RESET}")
    except Exception as e:
        print(f"{RED}⚠️ 无法获取流量: {e}{RESET}")

# ===================== 系统操作 =====================
def reboot_vps():
    confirm = input(f"{RED}⚠️ 确定要重启 VPS 吗? (y/n): {RESET}").lower()
    if confirm == 'y':
        subprocess.run(["reboot"])

def shutdown_vps():
    confirm = input(f"{RED}⚠️ 确定要关机 VPS 吗? (y/n): {RESET}").lower()
    if confirm == 'y':
        subprocess.run(["shutdown", "-h", "now"])

def restart_script():
    python = sys.executable
    os.execl(python, python, *sys.argv)

def stop_script():
    sys.exit(0)

def uninstall_script():
    confirm = input(
        f"{RED}⚠️ 确定要卸载管理脚本吗? "
        "这将删除整个安装目录、快捷命令和 systemd 服务! (y/n): {RESET}"
    ).lower()

    if confirm != 'y':
        print(f"{RED}❌ 已取消卸载{RESET}")
        return

    try:
        # 停止 systemd 服务并删除
        if os.path.exists(SYSTEMD_SERVICE):
            subprocess.run(["systemctl", "stop", "vpsbot"])
            subprocess.run(["systemctl", "disable", "vpsbot"])
            os.remove(SYSTEMD_SERVICE)
            subprocess.run(["systemctl", "daemon-reload"])
            print(f"{GREEN}✅ 已删除 systemd 服务: {SYSTEMD_SERVICE}{RESET}")

        # 删除安装目录
        if os.path.exists(INSTALL_DIR):
            shutil.rmtree(INSTALL_DIR)
            print(f"{GREEN}✅ 已删除安装目录: {INSTALL_DIR}{RESET}")

        # 删除快捷命令
        if os.path.exists(SHORTCUT_CMD):
            os.remove(SHORTCUT_CMD)
            print(f"{GREEN}✅ 已删除快捷命令: {SHORTCUT_CMD}{RESET}")

        print(f"{RED}🛑 管理脚本和后台 Bot 已卸载，退出程序{RESET}")

    except Exception as e:
        print(f"{RED}⚠️ 卸载失败: {e}{RESET}")

    sys.exit(0)

# ===================== 菜单 =====================
def menu():
    while True:
        clear_screen()
        cfg = load_config()

        auto_status = "开启" if cfg.get("auto_shutdown") else "关闭"
        limit = cfg.get("limit_gb", 0)

        print(f"""
========================
{CYAN}{BOLD}   VPS 快捷管理面板
   Version {VERSION}{RESET}
========================
自动关机状态: {GREEN if auto_status=='开启' else RED}{auto_status}{RESET}
流量阈值: {limit} GB
========================
{YELLOW}1) 修改 Telegram Token{RESET}
{YELLOW}2) 修改 Admin ID{RESET}
{YELLOW}3) 修改流量阈值{RESET}
{YELLOW}4) 开/关自动关机{RESET}
{GREEN}5) 查看 VPS 状态{RESET}
{GREEN}6) 查看流量统计{RESET}
{RED}7) 重启 VPS{RESET}
{RED}8) 关机 VPS{RESET}
{YELLOW}9) 重启管理脚本{RESET}
{YELLOW}10) 停止管理脚本{RESET}
{RED}11) 卸载管理脚本{RESET}
{YELLOW}0) 退出{RESET}
========================
""")

        choice = input("请输入选项: ").strip()

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
        elif choice == '9':
            restart_script()
        elif choice == '10':
            stop_script()
        elif choice == '11':
            uninstall_script()
        elif choice == '0':
            print(f"{YELLOW}退出管理面板{RESET}")
            break
        else:
            print(f"{RED}❌ 无效选项{RESET}")

        input("\n按回车返回菜单...")

# ===================== 主程序入口 =====================
if __name__ == "__main__":
    menu()
