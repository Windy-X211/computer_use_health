<p align="center"><img src="assets/icon.png" width="96" alt="HealthGuard"></p>

<h1 align="center">电脑使用健康管家 · HealthGuard</h1>

<p align="center">一个本地运行的 Windows 电脑使用时长管家：限制使用时段、强制休息、应用拦截、紧急放行。</p>

<p align="center">版本 1.0.0 · Windows 10/11 · Python 3.10+ · 纯本地运行</p>

---

## 简介

HealthGuard 常驻托盘，按 **1 秒一次的检测周期**统计真实使用时间：只有「屏幕亮着 + 有键鼠活动」才计入用量，锁屏、息屏、长时间挂机都不会被算进使用时长。

到达你设定的上限（每日总量 / 单次连续使用 / 禁止时段）后，先弹出倒计时警告，倒计时结束再执行你选定的动作：全屏遮罩、强制休息屏保、锁定屏幕，或（高级配置）注销、关机。休息屏保期间可以自动播放洛雪音乐并显示歌词，用「紧急密码 / 恢复码 / 快捷键」随时放行，避免把自己锁在外面。

> 只在本机运行。除启用「AI 门卫」时会把你的**理由和用量数字**发给你自己配置的 OpenAI 兼容接口外，不向外发送任何数据。

## 功能特性

| 功能 | 说明 |
| --- | --- |
| 时长限制 | 每日使用上限、单次连续使用上限、强制休息时长，均可在控制面板直接调节 |
| 时段限制 | 支持「只允许在这些时段使用」与「这些时段禁止使用」两种窗口，可跨零点，按星期生效 |
| 警告倒计时 | 达到上限先显示 Toast 倒计时（默认 30 秒），期间可提前解锁，不打断正在进行的工作 |
| 达到上限后 | 全屏拦截遮罩 / 自定义休息屏保（带倒计时）/ 锁定屏幕；配置层面还支持注销、关机（需显式确认风险） |
| 应用拦截 | 按进程名（exe）隐藏指定应用的窗口，每 2 秒复查一次，放行后自动恢复显示 |
| 连续使用浮层 | 桌面悬浮小窗实时显示本次连续使用时长，可调透明度、缩放、预设位置或自定义坐标 |
| 休息屏保 | 全屏休息倒计时、紧急解锁入口、音乐播放器与滚动歌词，休息结束后自动关闭并重置会话 |
| 紧急解锁 | 密码 / 备用恢复码 / 全局快捷键（默认 `Ctrl+Alt+Shift+U`），每次放行有固定时长与冷却期 |
| 紧急中止 | 默认 `Ctrl+Alt+Shift+X`：立即取消关机倒计时、释放所有限制并弹出紧急面板 |
| AI 门卫 | 可选：把放行理由交给 OpenAI 兼容模型判断，返回是否放行及放行分钟数（有上限） |
| 休息音乐 | 对接洛雪音乐（lx-music）Open API，支持「不播放 / 手动播放 / 自动播放」，休息结束自动暂停 |
| 开机自启 | 写入当前用户注册表 `Run` 项（`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`），设置里一键开关 |
| 托盘常驻 | 控制面板、设置、暂停限制、恢复限制、重新设置、退出 |
| 单实例 + 看门狗 | 全局互斥量防止重复启动；子进程看门狗监视心跳，主进程异常退出时自动清理并重启（fail-open） |

## 运行原理

```
engine 线程（每 1 秒）
  ├─ 读取 Win32 空闲时间、显示器开关状态
  ├─ 显示关闭 → 暂停会话计时；空闲超过阈值 → 不计入用量
  ├─ rules.evaluate(cfg, state)  计算本次判定（放行 / 受限 / 原因 / 下次可用时间）
  ├─ state.add_usage(1)         放行且活跃时累加用量，每 10 秒落盘
  └─ enforcer.update(decision)  受限后：Toast 倒计时 → 执行动作 → 屏保/遮罩
```

判定优先级：**紧急放行 → 时段限制 → 时长限制**。休息生命周期独立管理，休息结束后必须清理 `break_started_at`，否则屏保不会关闭，因此 `rules.py` 里把 break 的开始/结束与每日上限、时段阻塞解耦处理。

## 环境要求

- Windows 10 / 11（依赖 `user32`、`kernel32`、`powrprof` 等 Win32 接口）
- Python 3.10 及以上（开发与测试使用 3.13）
- 需要 Tkinter（官方安装包默认自带）
- 可选：洛雪音乐桌面版（仅休息音乐功能需要）

## 安装与运行

```bash
git clone https://github.com/Windy-X211/computer_use_health.git
cd computer_use_health

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python run.py
```

也可以直接作为模块启动：

```bash
python -m health_guard
```

首次启动会进入**设置向导**：确认使用须知 → 设置紧急密码 → 保存你的紧急恢复码 → 完成。设置完成后程序驻留托盘，限制默认处于**关闭**状态，需要你在控制面板或设置里主动开启。

## 首次使用建议

1. 设置紧急密码，并把恢复码抄在本机以外的地方（比如手机备忘录）。
2. 在「时长」页设一个宽松的值试跑一周（如每日 240 分钟、单次 60 分钟、休息 10 分钟）。
3. 在「策略」页先选「全屏拦截界面」，确认自己能接受打断强度，再考虑「锁定屏幕」。
4. 确认快捷键 `Ctrl+Alt+Shift+X` 可用——这是最后的保险。
5. 需要更强约束时再启用「应用拦截」与「AI 门卫」。

## 配置说明

配置文件为 JSON，位于 `%LOCALAPPDATA%\HealthGuard\config.json`，可手工编辑，界面保存时会自动校验并写回。主要字段：

| 字段 | 含义 | 默认值 |
| --- | --- | --- |
| `enabled` | 限制总开关 | `false` |
| `mode` | 限制模式：`duration` / `schedule` / `both` | `duration` |
| `duration.daily_limit_minutes` | 每日使用上限（分钟） | `240` |
| `duration.session_limit_minutes` | 单次连续使用上限（分钟） | `60` |
| `duration.break_minutes` | 强制休息时长（分钟） | `10` |
| `schedule.allowed_windows` | 允许使用的时间窗口 | `[]` |
| `schedule.blocked_windows` | 禁止使用的时间窗口 | `[]` |
| `strategy.primary_action` | 到点动作：`none` / `overlay` / `screensaver` / `lock`（另支持 `logoff` / `shutdown`） | `screensaver` |
| `strategy.warning_seconds` | 到点前的警告倒计时（秒） | `30` |
| `strategy.block_apps` | 是否启用应用拦截 | `false` |
| `strategy.blocked_apps` | 被拦截的进程名列表（如 `["steam.exe"]`） | `[]` |
| `strategy.shutdown_ack` | 注销/关机的风险确认开关 | `false` |
| `emergency.password_grant_minutes` | 每次解锁放行的分钟数 | `15` |
| `emergency.grant_cooldown_minutes` | 两次放行之间的冷却（分钟） | `15` |
| `emergency.hotkey_unlock` | 紧急解锁快捷键 | `["ctrl","alt","shift","u"]` |
| `emergency.hotkey_panic` | 紧急中止快捷键 | `["ctrl","alt","shift","x"]` |
| `gatekeeper.enabled` | 是否启用 AI 门卫 | `false` |
| `gatekeeper.base_url` | OpenAI 兼容接口地址 | `https://api.openai.com/v1` |
| `gatekeeper.model` | 模型名 | `gpt-4o-mini` |
| `gatekeeper.api_key` | 接口密钥（仅存本地，界面中以掩码显示） | `""` |
| `gatekeeper.max_grant_minutes` | AI 门卫可批准的最大时长 | `60` |
| `safety.fail_open` | 配置损坏且无备份时是否放行（不锁死用户） | `true` |
| `safety.idle_threshold_seconds` | 超过该空闲时长不计入用量 | `120` |
| `safety.shutdown_requires_ack` | 注销/关机是否强制要求风险确认 | `true` |
| `music.mode` | `disabled` / `manual` / `auto` | `auto` |
| `music.player_path` | 洛雪音乐可执行文件路径 | 见文件内注释 |
| `music.api_base` | 洛雪 Open API 地址（默认端口 23330） | `http://127.0.0.1:23330` |
| `music.stop_on_break_end` | 休息结束时暂停播放 | `true` |
| `session_overlay.enabled` | 是否显示连续使用浮层 | `true` |
| `session_overlay.opacity` / `scale` / `position` | 浮层可见度、缩放、位置 | `85` / `100` / `top-right` |

时间窗口格式（`days` 使用 `0=周一 … 6=周日`），`end` 小于 `start` 时自动视为跨零点：

```json
{
  "days": [0, 1, 2, 3, 4],
  "start": "23:00",
  "end": "06:30"
}
```

## 命令行参数

| 参数 | 作用 |
| --- | --- |
| `--status` | 打印当前限制状态与用量，不启动界面 |
| `--reset` / `--disable-all` | 关闭总开关、清空时段与策略、清零用量计数，不启动界面 |
| `--safe-mode` / `--disable` | 本次启动强制关闭限制（不写配置），用于自救；同时不启动看门狗 |
| `--no-watchdog` | 不启动看门狗子进程 |
| `--allow-multiple` | 跳过单实例互斥检查 |

示例（被屏保挡住但插不上手时，在任务管理器新建任务运行）：

```bash
python run.py --safe-mode
python run.py --reset
```

已有实例在运行时，普通启动会直接退出并返回码 `2`。

## 数据文件位置

默认目录：`%LOCALAPPDATA%\HealthGuard\`（可用环境变量 `HEALTHGUARD_HOME` 指向别的目录，测试脚本正是这样隔离数据的）。

| 文件 | 内容 |
| --- | --- |
| `config.json` | 全部配置（密码只以 PBKDF2-SHA256 哈希 + 盐存储） |
| `state.json` | 当日用量、会话与休息起点、放行记录、暂停标记 |
| `heartbeat.json` | 主进程 PID 与心跳时间戳，供看门狗判断 |
| `logs/healthguard.log` | 运行日志（滚动备份） |
| `backups/` | 配置历史备份，保留最近 10 份；配置损坏时自动回滚最近可用版本 |

## 紧急解锁

三种方式，任一即可放行固定分钟数（默认 15 分钟），之后进入冷却期（默认 15 分钟）：

- **紧急密码**：屏保/遮罩上的「紧急解锁」按钮，或托盘「暂停限制」也需验证密码。
- **恢复码**：首次设置时生成的备用码（形如 `HG-XXXXXXXX-XXXXXXXX`），务必保存在本机以外。
- **快捷键**：`Ctrl+Alt+Shift+U` 直接唤起解锁面板；`Ctrl+Alt+Shift+X` 立即中止一切限制并取消关机倒计时。

紧急面板有三个页签：密码解锁、AI 门卫（需在设置中启用并配置密钥）、恢复码解锁。恢复码与密码都支持「重置密码」流程（需旧密码或恢复码验证）。

## 休息音乐（洛雪音乐）

仅支持 [洛雪音乐桌面版](https://github.com/lyswhut/lx-music-desktop) 的 Open API：

1. 在洛雪音乐的「设置 → 开放 API」中开启服务（默认端口 `23330`）。
2. 在本程序「休息音乐」页填写播放器路径与 API 地址，点「测试洛雪音乐连接」确认。
3. 选择模式：`disabled` 完全不启动；`manual` 启动后由你在屏保里点播放；`auto` 进入休息即自动播放。

程序不会重复拉起已在运行的洛雪（会先探测端口），休息结束时按配置自动暂停。

## 项目结构

```
computer_use_health/
├─ run.py                     # 启动入口
├─ requirements.txt           # pystray + Pillow
├─ assets/                    # 图标
├─ health_guard/
│  ├─ controller.py           # 主控：engine 循环、设置向导、托盘联动、命令行
│  ├─ rules.py                # 纯函数判定：时段/时长/放行 → Decision
│  ├─ state.py                # 用量状态持久化（10 秒落盘、跨天重置）
│  ├─ enforcer.py             # 受限后的动作编排：Toast → 屏保/遮罩/锁屏/关机
│  ├─ app_blocker.py          # 应用窗口拦截线程
│  ├─ emergency.py            # PBKDF2 密码、恢复码、放行与冷却
│  ├─ gatekeeper.py           # AI 门卫（OpenAI 兼容 /chat/completions）
│  ├─ music.py                # 洛雪音乐客户端、LRC 解析、播放器控制
│  ├─ ui.py                   # 遮罩、屏保、Toast、紧急面板、密码框
│  ├─ ui_dashboard.py         # 控制面板（用量卡片、限值步进器、暂停/主动休息）
│  ├─ ui_settings.py          # 设置页（基本/时长/时段/策略/紧急/AI/安全/音乐）
│  ├─ ui_setup.py             # 首次设置向导
│  ├─ ui_session_overlay.py   # 连续使用浮层
│  ├─ tray.py                 # 托盘图标与菜单
│  ├─ hotkeys.py              # 全局快捷键（RegisterHotKey + 消息循环）
│  ├─ winapi.py               # 空闲时间、显示器状态、锁屏、注销、关机
│  ├─ watchdog.py             # 看门狗：心跳过期则清理并重启主进程
│  ├─ autostart.py            # 开机自启（启动项）
│  ├─ config.py               # 配置加载、校验、备份轮换、掩码
│  └─ logging_setup.py / util.py / constants.py
└─ _*_test.py                 # 自检与会话内联调脚本
```

## 自检脚本

仓库里的 `_*.py` 是开发期使用的手动自检脚本，会通过 `HEALTHGUARD_HOME` 指向临时目录，不会污染你的真实配置：

| 脚本 | 内容 |
| --- | --- |
| `python _smoke_test.py` | 配置读写、备份回滚、默认值隔离、fail-open |
| `python _engine_test.py` | 判定引擎、Enforcer 动作流转、应用拦截 |
| `python _int_test.py` | AI 门卫：本地假 HTTP 服务验证请求与 JSON 解析 |
| `python _check_controller_calls.py` | 静态检查 `controller` 调用的 `UIApp` 方法是否都存在 |
| `python _hotkeys_test.py` / `_diag_hotkey.py` | 快捷键注册与冲突诊断 |
| `python _dashboard_test.py` / `_dashboard_live_test.py` | 控制面板数据绑定 |
| `python _screensaver_live_test.py` / `_emergency_live_test.py` / `_wizard_live_test.py` | 屏保刷新、紧急面板、设置向导的界面联调（会真的弹窗，跑完会自动关闭） |

## 安全设计与取舍

- **fail-open**：配置损坏且无可用备份时，宁可暂时不限制，也不把你锁在屏保里。
- **密码不进配置明文**：PBKDF2-HMAC-SHA256，20 万次迭代加随机盐。
- **危险动作需二次确认**：注销/关机默认被 `shutdown_requires_ack` 拦住，必须在设置里显式勾选风险确认。
- **看门狗只做恢复**：心跳超过 20 秒不新鲜时取消关机、结束残留进程并重启主程序，不做额外限制。
- **无密码时的提醒**：限制开启但未设密码会在托盘提示，因为此时没有任何自救手段。

## 已知限制

- 仅支持 Windows；未做 macOS/Linux 适配。
- 应用拦截是「隐藏窗口」级别，不结束进程，任务管理器强杀本程序即可绕过——定位是自律工具，不是防作弊系统。
- 休息音乐只对接洛雪音乐，不支持其它播放器。
- AI 门卫依赖外部接口，模型输出需为 JSON；接口异常时会报错并退回人工解锁，不会自动放行。

## 许可

本仓库暂未附带开源许可证文件。如需转载、复用或二次分发，请先与作者确认。
