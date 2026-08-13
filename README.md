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
# 下载并执行
curl -o vpsbot_install.sh https://raw.githubusercontent.com/alllike996/vps-bot-manager/main/install.sh
sudo bash vpsbot_install.sh

# 安装完成后
vps-bb  # 调出快捷面板
systemctl status vpsbot  # 查看后台服务状态


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

## 四个分支说明

main目前同test  都是次新版本  
tiga 属于未优化，属于早期版本  
fix/security-hardening为修复版本-目前最新，需要测试
---

## 🎉 最新更新：安全加固与流量告警模式

> 🌿 **更新分支：** `fix/security-hardening`  
> 🛡️ **更新重点：** 凭据保护、权限加固、私聊管理、流量超限仅告警 、修复ssh失败记录无法调取（扩展了匹配规则：不仅检查 Failed password，还增加了 Invalid user、Failed publickey、authentication failure、Connection closed、Disconnected from 以及尝试次数超限等 8 种失败场景。）
> 
> ⚠️ **重要变化：** 已移除“流量超限自动关机”功能

### 🚨 重要行为调整

为避免类似于 Oracle Cloud vps等热门区域实例在关机后可能因容量不足而无法恢复，本版本将原先的：

```text
流量超限 → 自动关机
```

调整为：

```text
流量超限 → Telegram 告警通知 → 手动处理
```

- ✅ 流量超过设置阈值后，Bot **仅发送 Telegram 告警**
- ✅ 默认每 6 小时最多提醒一次，避免频繁刷屏
- ✅ 保留手动重启、手动关机功能
- ✅ 手动重启和关机仍需要二次确认
- ❌ 不再因流量超限自动执行 `poweroff`

> 💡 对 OCI Always Free、ARM 热门区域或不希望实例停机的用户，建议保持流量告警模式。

### 🔐 安全加固

| 项目 | 更新内容 |
|---|---|
| 🤖 Bot Token | 安装和修改 Token 时使用静默输入，不会在终端回显 |
| 📁 配置文件 | `config.json` 固定使用 `600` 权限，仅 root 可读写 |
| 📂 安装目录 | `/opt/vpsbot` 固定使用 `700` 权限 |
| 💬 Telegram 权限 | 仅允许设置的 `admin_id` 在**私聊**中管理 VPS |
| 👥 群组保护 | 即使 Bot 被拉入群组，也无法在群内执行管理操作 |
| 🧩 配置写入 | 使用临时文件 + 原子替换，降低配置损坏风险 |
| 🖥️ 命令执行 | 移除 `shell=True` 与 `os.system()`，改用安全参数调用 |
| 🗑️ 卸载保护 | 仅允许删除 `/opt/vpsbot`，避免误删其他目录 |
| 📥 脚本下载 | 下载失败会立即终止安装，不继续执行异常文件 |

### 📡 流量告警说明

设置流量阈值后：

```text
例如：设置 200 GB
```

当本月总流量达到或超过 `200 GB` 时，Bot 会发送：

```text
🚨 流量阈值警告

已用流量: 200 GB
设定阈值: 200 GB

🛡 当前仅发送告警，不会自动关机。
```

> 🔔 如不需要告警，可在 Telegram 面板或 `sudo vps-bb` 中将流量阈值设置为 `0`。

### 🛠️ 管理面板变化

旧版本：

```text
⚙️ 设置流量阈值
⚡ 自动关机：开启 / 关闭
```

新版本：

```text
⚙️ 设置流量告警
🛡 超限行为：仅通知，不自动关机
```

本地管理命令：

```bash
sudo vps-bb
```

常用操作：

```text
1) 修改 Telegram Token
2) 修改 Admin ID
3) 修改流量告警阈值
4) 查看 VPS 状态
5) 查看流量统计
6) 重启后台 Bot 服务
7) 重启 VPS
8) 关机 VPS
```

### ⚠️ 升级提醒

- ❌ 请勿提交真实 `config.json`、`.env`、日志、私钥或部署备份。
- 🔄 如果 Bot Token 曾出现在 Git 历史、截图、聊天、日志或录屏中，请立刻通过 `@BotFather` 撤销并更换 Token。
- 🧪 更新后建议检查脚本语法：

```bash
bash -n install.sh
python3 -m py_compile vps_bot.py vps_bb.py
```

- 🔄 已部署旧版本时，更新文件后重启服务：

```bash
sudo systemctl restart vpsbot
sudo systemctl status vpsbot --no-pager
```

- 📜 查看 Bot 运行日志：

```bash
sudo journalctl -u vpsbot -n 100 --no-pager
```

### ✅ 配置示例

仓库中只应提交示例配置，例如 `config.example.json`：

```json
{
  "bot_token": "REPLACE_WITH_TELEGRAM_BOT_TOKEN",
  "admin_id": 0,
  "limit_gb": 200,
  "auto_shutdown": false,
  "vnstat_interface": "eth0"
}
```

> 🛡️ `auto_shutdown` 仅为兼容旧版配置保留；当前版本固定为 `false`，不会自动关闭 VPS。

---
