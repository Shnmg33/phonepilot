# PhonePilot · 自托管 AI 手机智能体

把任务交给云端 AI，通过手机原生桥接直接控制 Android 手机，无需常开电脑；执行过程留日志，任务结束做复盘，经验沉淀到独立的技能区，供以后检索复用。原电脑 ADB 方案保留为备用。

当前为单用户 MVP：服务器、网页和 ADB 桥接已实现并通过模拟测试；原生 Android 桥接已成功编译为 0.2.0 debug APK，并通过 Android lint 与安装包签名检查。完整交付包的 releases/ 包含安装包；尚未在 iQOO 真机验证。手机安装与重新构建步骤见 [android/README.md](android/README.md)，验证范围见 [VALIDATION.md](VALIDATION.md)。

## 架构

```text
浏览器 ── HTTPS + 管理员令牌 ── 云服务器
                              ├─ FastAPI + 中文网页
                              ├─ 任务队列 / 定时调度 / SQLite
                              ├─ 模型规划 / 操作复盘 / 技能记忆
                              └─ DeepSeek / OpenAI 兼容 API
                                  ⇅ HTTPS（手机主动长轮询）
                              Android 原生桥接 APK
                              └─ 无障碍读取 / 手势 / 文字输入 / 按需截图
```

推荐手机方案不需要常开电脑、USB 连接或 Root。云端承担 AI 与管理功能，手机只负责操作与回传。备用电脑方案仍支持 `Python bridge → ADB → 手机`。

## 已实现

| 部分 | 功能 |
| --- | --- |
| 手机控制 | 截图、UIAutomator 界面树、点击元素/坐标、滑动、文字输入、返回/主屏/回车等按键、按包名启动应用 |
| 自主执行 | 观察 → 检索相关技能 → 模型规划下一步 → 校验动作 → 执行 → 再观察；支持跨应用步骤 |
| 任务中心 | 创建任务、步数限制、停止、操作时间线、结果与复盘；重启将运行中的任务标为中断 |
| 定时计划 | 每日指定时间与时区、固定间隔、暂停/恢复、删除；关闭网页仍执行 |
| 技能记忆 | 自动提炼草稿、证据步骤、来源任务、人工编辑/启用/停用、版本历史、任务使用结果统计 |
| 模型配置 | DeepSeek 预设、OpenAI 预设、自定义兼容 API 地址/模型/密钥环境变量、视觉开关、连通性测试 |
| 管理网页 | 中文响应式布局、设备在线状态、截图预览、点击/拖动截图手动控制、输入文字 |
| 部署 | Python 启动器、Docker Compose、Caddy HTTPS 示例、systemd 示例、集成测试 |
| 手机原生桥接 | Android 11+ 测试版 APK、HTTPS 长轮询、锁屏/息屏上报、按需截图；构建和签名已验证，真机待验收 |

## 1. 云服务器快速启动

需要 Python 3.11+（推荐 3.12）。服务器不需要安装 ADB。

```bash
cd phonepilot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py init
```

`init` 创建权限为 `0600` 的 `.env`，生成两个不同的随机令牌；已有文件不会被覆盖。编辑 `.env`：

```dotenv
ADMIN_TOKEN=自动生成，网页登录使用
BRIDGE_TOKEN=自动生成，本地桥接程序使用
DEEPSEEK_API_KEY=你的DeepSeek密钥
OPENAI_API_KEY=
AUTO_ACTIVATE_SKILLS=false
```

保留生成的令牌，仅填写需要的 API Key。`.env` 使用字面量 `KEY=value`，不展开 shell 变量，不支持行末注释；系统已有同名环境变量优先。

```bash
python manage.py doctor
python manage.py run
```

默认监听 `127.0.0.1:8000`。本机访问 `http://127.0.0.1:8000`，使用 `.env` 中的 `ADMIN_TOKEN` 登录。浏览器只保存管理员令牌到当前标签页会话，模型密钥始终由服务器环境变量提供。

### 云端 HTTPS

把域名解析到服务器，在宿主机 Caddy 配置中加入 `Caddyfile.example` 的内容并替换域名。Caddy 转发到 `127.0.0.1:8000`，申请 TLS 证书。打开云安全组的 80/443 端口，然后通过 `https://你的域名` 访问。桥接程序默认要求 HTTPS。

持续运行可以参考 `phonepilot.service.example`，先创建专用用户并将项目安装到 `/opt/phonepilot`，调整服务路径后启用 systemd。必须只运行 **一个** Web worker / 服务实例：当前队列、设备连接和调度由单进程管理。

### Docker 方式（二选一）

先用 `python manage.py init` 生成并填写 `.env`，再运行：

```bash
docker compose up -d --build
docker compose logs -f
```

Compose 将服务端口绑定到宿主机 `127.0.0.1:8000`，同样用宿主机 Caddy 反向代理。SQLite 存在 `phonepilot-data` 命名卷中。修改密钥后执行 `docker compose up -d --force-recreate`。

Docker 配置已提供，本次开发环境未实际构建容器。

## 2A. 推荐：手机原生桥接，无需常开电脑

iQOO Z3 方案详见 [android/README.md](android/README.md)。先在“关于手机”确认 Android 11 及以上；APK 可在你的 Linux 云服务器构建，或使用附带的 GitHub Actions。完整交付包已提供可安装的测试版 APK，源码也可重新构建。

APK 安装后，在手机填写服务器 HTTPS 地址、稳定桥接 ID 和 `BRIDGE_TOKEN`，开启无障碍服务并启动。模型密钥仍只在服务器。原生中文输入无需 ADBKeyboard，会替换整个聚焦输入框。

手机锁屏/息屏时，服务器让新任务排队等待；不能绕过密码锁。iQOO 需按系统实际提供的选项设置后台运行、自启动与电池限制，仍需实测长期稳定性。

## 2B. 备用：在手机旁的电脑启动 ADB 桥接程序

支持 Linux / macOS / Windows，安装 Python 3.11+ 与 [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools)，确认 `adb` 在 PATH 中。

将本项目复制到这台电脑（不需要复制云端 `.env` 或数据库）：

```bash
python -m pip install -r requirements.txt
adb version
```

### USB

1. Android 开发者选项中开启“USB 调试”。
2. 数据线连接电脑，在手机上允许这台电脑的调试授权。
3. 执行 `adb devices -l`，状态应为 `device`。`unauthorized` 需要重新确认手机授权。

Linux / macOS：

```bash
export BRIDGE_TOKEN='复制云端 .env 中的 BRIDGE_TOKEN'
python -m bridge.agent --server https://你的域名 --id home
```

Windows PowerShell：

```powershell
$env:BRIDGE_TOKEN = '复制云端 .env 中的 BRIDGE_TOKEN'
python -m bridge.agent --server https://你的域名 --id home
```

桥接进程只需要 `BRIDGE_TOKEN`，无需管理员令牌或模型密钥。每台桥接电脑使用稳定且唯一的 `--id`。可用 `--adb /绝对路径/adb` 指定可执行文件。

仅本机联调或可信 VPN 内的 HTTP 地址，可显式添加 `--allow-http`。云端部署使用 HTTPS。

### Android 11+ 无线调试

手机与桥接电脑处于同一局域网。在手机开发者选项启用无线调试，选择“使用配对码配对设备”：

```bash
adb pair 手机IP:配对端口
# 按提示输入手机上的配对码
adb connect 手机IP:调试端口
adb devices -l
```

配对端口与调试端口通常不同。无线调试页面里的 IP/端口可能在重连后变化，需要重新 `adb connect`。桥接程序自动发现已连接设备；手机无需直连云服务器。

### 中文与特殊文本输入

普通 ASCII 文本用系统 `adb shell input text`。中文、换行等需要手机上安装并启用兼容的 [ADBKeyboard](https://github.com/senzhk/ADBKeyBoard) 输入法，本项目不附带 APK。

从你信任的来源获取 APK 后：

```bash
adb -s 设备序列号 install /路径/ADBKeyboard.apk
adb -s 设备序列号 shell ime enable com.android.adbkeyboard/.AdbIME
adb -s 设备序列号 shell ime set com.android.adbkeyboard/.AdbIME
```

桥接程序检查当前输入法后，以 Base64 广播输入 Unicode 文本。不满足条件会明确停止该操作；不会把不支持的中文输入伪装为成功。用完可在手机设置里切回原输入法。

## 3. 接入 DeepSeek 与其他模型

网页“模型配置”预置：

| 配置 | API 基础地址 | 默认模型 | 密钥环境变量 | 默认界面输入 |
| --- | --- | --- | --- | --- |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` | `DEEPSEEK_API_KEY` | 界面结构 JSON |
| OpenAI | `https://api.openai.com/v1` | `gpt-4.1-mini` | `OPENAI_API_KEY` | 截图 + 界面结构 |

模型 ID 是可编辑的预设值，实际以你的账号和服务商当前支持的模型为准。

支持 **OpenAI Chat Completions 兼容协议**：程序向基础地址追加 `/chat/completions`，使用 Bearer API Key、JSON mode、`messages` 和 `max_tokens`。其他厂商如提供该协议，可直接添加；非兼容原生协议需要网关或扩展 `server/runtime.py` 的 `ModelClient`，尚未实现所有厂商的原生 SDK。

不要把 `/chat/completions` 填入基础地址。新增密钥环境变量后需重启服务；Docker 自定义环境变量需放入 `.env` 并重建容器实例。点击“测试连接”会发送一次小型 API 请求，可能产生少量费用。

文本模型不能直接理解截图。DeepSeek 预设使用界面结构中的文字、控件 ID 与位置；Canvas、游戏、图片按钮或无法导出节点的页面，通常需要支持图片输入的模型。仅对支持该能力的模型开启“发送截图”。

## 4. 从第一个任务到技能记忆

建议先安排一个容易核验的任务：

> 打开系统设置，查看手机的 Android 版本，并告诉我结果。

任务详情会依次显示观察、规划、执行和模型给出的完成证据。默认最多 25 步，可调整为 1–100。执行器每次只允许一个经过校验的结构化动作，没有“任意 shell 命令”动作。

任务结束后，AI 额外生成复盘与可复用技能：

```text
任务实际轨迹 + 最后界面 + 成功/失败结果
   ↓
操作复盘 + 适用场景 + 具体步骤 + 注意事项
   ↓
校验证据步骤确实执行过 → 写入技能草稿
   ↓
审核启用，或按配置自动启用成功经验
   ↓
后续任务按目标和当前应用检索最多 6 条相关技能
```

默认 `AUTO_ACTIVATE_SKILLS=false`：在技能区检查经验并选择“已启用”。如果希望自动积累并使用成功经验，将其设为 `true` 并重启服务；失败/受阻任务的经验仍是草稿。

每条技能包含标题、应用、适用条件、步骤、注意事项、来源任务、证据步骤、版本以及使用统计。编辑会保存历史快照；停用后不再检索。统计反映“检索到该技能的任务”的整体结果，不代表某条技能单独导致成功。

这里的“越用越聪明”是**持久化经验记忆 + 检索增强**，不是更新模型权重。当前检索使用中文双字片段与英文词匹配，尚未引入向量数据库、自动合并同类技能或可靠性评估模型。界面改版后可以编辑/停用旧经验。

## 5. 执行、调度与恢复规则

- 当前任务队列串行执行；离线、锁屏、息屏或仍有未确认命令的设备保持排队，其他可操作设备的任务可继续被领取。同一设备的手动控制与 AI 任务互斥。AI 执行期间可查看已缓存的最近截图；文字模型的原生桥接观察不请求截图，可能没有可用缓存。
- 点击“停止”取消后续规划和命令，已经送达手机的单次动作可能仍完成。等待其结果后才能继续；不会尝试回滚手机上的实际变化。
- 已领取的操作不会自动重发。超时、断线时停止任务，并显示“待确认命令”；检查手机和桥接程序后可在设备页手动清除该状态。
- 模型/API/ADB 错误、无效元素、越界坐标、连续三次相同动作、超过步数都会停止；不会自动绕过登录、验证码或系统授权。
- 定时计划按指定时区计算；服务器停机期间错过的计划只补触发一次，同一计划尚有排队/运行任务时跳过该次触发。
- 服务重启会把运行任务标为“已中断”，排队任务继续保留。不会自动恢复一段执行到一半的手机流程。
- 任务、事件、技能和计划在 SQLite 持久化。设备在线状态、进行中的命令和最近截图只在内存中保存。
- 手机需保持可操作，锁屏、安全窗口、厂商限制、权限弹窗及 ADB 不可读的界面可能需要人工处理。本版没有 iOS 支持；已包含原生 Android 桥接源码和测试版 APK，实际手机兼容性尚待验收。

## 数据与访问

这是单用户控制台。管理员令牌可以控制全部设备，桥接令牌用于信任的桥接电脑；多个桥接进程共用一个桥接密钥，尚未实现多租户隔离与逐设备密钥。

UI 结构与任务上下文会发送给所选模型；开启视觉时截图也会发送。两种桥接端在界面树中都遮蔽标记为 password 的控件文字，但截图和应用显示内容仍可能包含私人信息。日志与技能保存在自己的数据库中，请根据任务内容选择模型服务和保留策略。

备份数据库时使用 SQLite backup API，或停止服务后复制 `data/`（Docker 为命名卷）。本版没有自动日志清理；需要长期运行时，可进一步增加备份、保留期限和审计功能。

## 测试

```bash
python -m unittest discover -s tests -v
node --check web/app.js
```

测试包含模拟云端 API、桥接轮询、节点定位、动作执行、模型总结、技能审核/版本/再次检索、任务停止、超时不重发、角色鉴权、调度去重、时区与重启恢复。模拟设备测试不等同于真实手机/API 实测。

实机验收顺序：

1. 模型配置页测试连接成功。
2. 原生方案先完成 Android 编译/安装验收，并在设备页确认手机在线；备用 ADB 方案确认 `adb devices -l` 正常。
3. 刷新手机截图，手动返回/主屏、点击和滑动可用。
4. 执行“查看 Android 版本”，观察动作和最终证据。
5. 在技能区审核生成的技能，再次执行相似任务，检查“技能检索”事件。
6. 创建一个短间隔计划，验证关闭网页后仍触发，再暂停计划。

## 项目文件

```text
server/app.py       HTTP 接口、鉴权与网页入口
server/runtime.py   桥接命令、模型规划、调度、复盘和技能检索
server/store.py     SQLite 持久化与技能版本
server/models.py    输入/动作校验
bridge/agent.py     备用电脑 ADB 桥接程序
android/           原生 Android 手机桥接源码、构建脚本与 iQOO 指南
.github/workflows/ Android 云端构建工作流
web/               中文管理控制台，无前端构建依赖
tests/             模拟设备端到端与边界测试
manage.py          初始化配置、诊断与启动
compose.yaml       云端容器部署
```

下一阶段可扩展：多设备并行执行、真正的应用版本绑定技能、向量检索与经验合并、计划编辑、任务全量分页搜索、OCR、敏感动作确认策略、原生 Android bridge 的实机验证、工具调用协议及更完整的故障恢复。目前没有自动声称模型生成的结论一定正确；界面结果与实际业务结果仍需要对应任务的验证标准。
