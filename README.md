# VPS Bot Manager

Telegram VPS 管理机器人，支持流量监控、流量超标自动关机、系统状态查询等功能。

## ✨ 功能特点
- 📊 **状态监控**：实时查看 CPU、内存、硬盘、开机时间。
- 📡 **流量统计**：基于 vnstat，精准统计当月流量（上传/下载/总计）。
- ⚡️ **自动关机**：支持设置流量阈值（如 1TB），超标自动关机，防止流量超支扣费。
- 🛠 **便捷管理**：提供重启、关机按钮（带二次确认）。
- 🐳 **独立环境**：使用 Python 虚拟环境，不污染系统库。

## 🚀 一键安装

使用 root 用户 SSH 登录你的 VPS，执行以下命令即可：

```bash
curl -o vpsbot_install.sh https://raw.githubusercontent.com/alllike996/vps-bot-manager/main/install.sh  
sudo bash vpsbot_install.sh  

```
## ⚙️ 配置说明

安装过程中会提示输入以下信息：  
Bot Token: 从 @BotFather 获取。  
Admin ID: 你的 Telegram 用户 ID（从 @userinfobot 获取），防止他人操作。  
流量阈值: 设置为 0 代表不限制，设置为具体数字（如 1024）代表 1TB 关机。  

## 📂 文件结构

安装路径: /opt/vpsbot  
配置文件: /opt/vpsbot/config.json  
日志查看: journalctl -u vpsbot -f  

## 📝 手动管理命令

启动: systemctl start vpsbot  
停止: systemctl stop vpsbot  
重启: systemctl restart vpsbot  
