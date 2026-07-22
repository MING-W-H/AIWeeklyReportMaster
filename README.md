# AI 周报生成器 (AIWeeklyReportMaster)

一个基于 Python 的 AI 周报自动生成系统，支持通过 CRM 接口自动下载工时 Excel（或手动放置本地 Excel），去重汇总后调用大模型（MiniMax / DeepSeek / OpenCode / Qwen）生成结构化周报，并支持通过腾讯企业邮箱自动发送给指定人员。

---

## 目录

- [功能特性](#功能特性)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [配置文件说明](#配置文件说明)
- [AI Provider 配置](#ai-provider-配置)
- [CRM 工时接口配置](#crm-工时接口配置)
- [腾讯企业邮箱配置](#腾讯企业邮箱配置)
- [定时任务与节假日检查](#定时任务与节假日检查)
- [命令行参数](#命令行参数)
- [输出文件命名](#输出文件命名)
- [使用示例](#使用示例)
- [邮件发送失败排查](#邮件发送失败排查)
- [常见问题](#常见问题)
- [模块说明](#模块说明)

---

## 功能特性

- **CRM 接口自动下载**：调用 CRM `exportWorkHourItems` 接口自动下载上一周工时 Excel，无需手动放置
- **本地 Excel 兼容**：未启用 CRM 接口时仍支持手动放置 Excel 文件到 `excel_files/` 目录
- **智能列识别**：自动识别 Excel 中的任务列（任务名称 / 项目/需求任务 / 第一列），适配 CRM 与手工两种格式
- **智能去重**：提取任务列内容，跨文件自动去重
- **多 AI Provider 支持**：内置 4 家大模型 API（MiniMax / DeepSeek / OpenCode / Qwen），可自由切换
- **多种输出格式**：支持 Markdown / 纯文本 / 结构化 / 项目符号 / 自定义提示词
- **智能输出清理**：自动移除 AI 输出中的对话式前缀、思考过程泄露、重复输出
- **灵活的文件命名**：支持日期占位符（当前日期、上一周日期范围）
- **腾讯企业邮箱**：生成周报后自动通过 SMTP SSL 发送邮件，支持收件人、抄送、附件
- **完善的错误处理**：HTTP 状态码细分（401/403/404/429/5xx）、超时分类、provider 切换建议
- **Token 统计**：终端打印每次调用的 token 使用情况
- **环境变量支持**：API Key、邮箱密码、CRM Token 均可通过环境变量注入，便于 CI/CD
- **定时任务**：支持注册 Windows 计划任务，每周一自动执行
- **节假日检查**：自动跳过法定节假日和周末，支持调休上班日判断

---

## 项目结构

```
AIWeeklyReportMaster/
├── weekly_report.py             # 主入口（命令行参数 + 流程编排）
├── config_manager.py            # 配置管理（默认配置 + 加载 + 合并）
├── crm_downloader.py            # CRM 工时 Excel 接口下载模块
├── excel_aggregator.py          # Excel 读取与汇总（扫描 + 列识别 + 去重）
├── llm_client.py                # LLM API 调用（prompt 构建 + HTTP 请求 + 错误处理）
├── text_utils.py                # 文本处理（前缀清理 + Markdown 转 HTML）
├── output_resolver.py           # 输出路径解析（日期范围计算 + 占位符替换）
├── email_sender.py              # 邮件发送（腾讯企业邮箱 SMTP）
├── holiday_checker.py           # 节假日检查（法定假日 + 调休 + 在线 API）
├── diagnose_email.py            # 邮件配置诊断脚本
├── register_weekly.ps1          # 定时任务注册脚本（每周一 10:00，PowerShell）
├── run_weekly_report.bat        # 定时任务启动脚本（批处理）
├── config.json                  # 用户配置文件（首次运行自动生成，已被 .gitignore 忽略）
├── config.example.json          # 配置模板（提交到 git 供参考）
├── .env.example                 # 环境变量模板（提交到 git 供参考）
├── requirements.txt             # Python 依赖
├── excel_files/                 # Excel 文件存放目录（CRM 下载目录 / 手工放置目录）
├── reports/                     # 周报输出目录（自动生成）
├── logs/                        # 执行日志目录（自动生成）
└── README.md                    # 本文档
```

---

## 快速开始

### 1. 环境准备

- Python 3.8+
- 安装依赖：

```bash
pip install pandas openpyxl requests python-dotenv
```

### 2. 首次运行

```bash
python weekly_report.py
```

首次运行会自动在项目根目录生成 `config.json` 配置模板，然后退出。

### 3. 编辑配置文件

打开 [config.json](config.json)，填入以下必要信息：

- `provider` 选择的 AI 服务商的 `api_key`
- 选择 Excel 数据来源：
  - **方式 A（推荐）**：启用 CRM 接口自动下载（填写 `crm` 段并设 `crm.enabled=true`）
  - **方式 B**：手动放置 Excel 到 `excel_folder` 目录
- （可选）`email` 段配置腾讯企业邮箱

### 4. 配置 Excel 数据来源

#### 方式 A：启用 CRM 接口自动下载（推荐）

1. 登录你的 CRM 系统（如 `https://crm.example.com`）
2. 打开浏览器开发者工具（F12）→ Network 标签
3. 触发一次工时明细导出操作，找到 `exportWorkHourItems` 请求
4. 复制请求头中以下字段：
   - `authorization`: `Bearer:xxxxx` 中 `Bearer:` 后面的完整 token
   - `userid`: 用户 ID
   - `tyinjectparams`: 注入参数（可选）
   - 请求体中 `orgOidList`: 组织 OID 列表
5. 填入 `config.json` 的 `crm` 段（详见 [CRM 工时接口配置](#crm-工时接口配置)）

启用后将自动按上一周周一至周五的日期范围下载工时 Excel，无需手动放置。

#### 方式 B：手动放置 Excel

将工时表 Excel 文件放入 `excel_files/` 文件夹（或其他你配置的路径）。

Excel 文件应包含「任务名称」或「项目/需求任务」列（自动识别）

### 5. 生成周报

```bash
python weekly_report.py
```

周报会自动保存为 `Vue{上一周日期范围}周报.md`，例如 `Vue2026.7.13-7.19周报.md`。

---

## 配置文件说明

`config.json` 是项目的核心配置文件，首次运行 `weekly_report.py` 时自动生成。

### 完整配置示例

```json
{
  "provider": "minimax",
  "providers": {
    "minimax":   { "api_key": "", "base_url": "...", "model": "...", "thinking_param": {...}, "max_tokens_field": "..." },
    "deepseek":  { "api_key": "", "base_url": "...", "model": "...", "thinking_param": {...}, "max_tokens_field": "..." },
    "opencode":  { "api_key": "", "base_url": "...", "model": "...", "thinking_param": null,  "max_tokens_field": "..." },
    "qwen":      { "api_key": "", "base_url": "...", "model": "...", "thinking_param": null,  "max_tokens_field": "..." }
  },
  "excel_folder": "./excel_files",
  "excel_extensions": [".xlsx", ".xls", ".xlsm"],
  "output_format": "markdown",
  "output_file_template": "Vue{last_week_range}周报",
  "output_file": "",
  "tokens_to_generate": 4096,
  "temperature": 0.3,
  "max_chars_per_sheet": 30000,
  "custom_prompt": "",
  "thinking_enabled": false,
  "timeout": 180,
  "crm": {
    "enabled": false,
    "url": "https://crm.example.com/ipd/rest/v1/workHourReport/integration/exportWorkHourItems",
    "token": "",
    "userid": "",
    "tyinjectparams": "",
    "org_oid_list": ["YOUR_ORG_OID"],
    "user_oid_list": [],
    "project_oid_list": [],
    "download_dir": "excel_files",
    "timeout": 60
  },
  "email": {
    "enabled": false,
    "smtp_host": "smtp.exmail.qq.com",
    "smtp_port": 465,
    "sender": "",
    "password": "",
    "recipients": [],
    "cc": [],
    "subject_template": "Vue 周报 {last_week_range}",
    "attach_report": true
  }
}
```

### 字段说明

| 字段                     | 说明                                                                          | 默认值                         |
| ------------------------ | ----------------------------------------------------------------------------- | ------------------------------ |
| `provider`             | 当前使用的 AI 服务商                                                          | `minimax`                    |
| `providers`            | 各 AI 服务商的配置（详见下节）                                                | -                              |
| `excel_folder`         | Excel 文件夹路径（绝对或相对路径）                                            | `./excel_files`              |
| `excel_extensions`     | 支持的 Excel 扩展名                                                           | `[".xlsx", ".xls", ".xlsm"]` |
| `excel_task_column`    | 指定任务列名（留空则自动识别：任务名称 / 项目/需求任务 / 第一列）             | `""`                         |
| `output_format`        | 输出格式：`markdown` / `plain` / `structured` / `bullet` / `custom` | `markdown`                   |
| `output_file_template` | 输出文件名模板，支持日期占位符                                                | `Vue{last_week_range}周报`   |
| `output_file`          | 若设置则直接使用该路径，覆盖 template                                         | `""`                         |
| `tokens_to_generate`   | LLM 最大生成 token 数                                                         | `4096`                       |
| `temperature`          | LLM 生成温度（0-1）                                                           | `0.3`                        |
| `max_chars_per_sheet`  | 单个 sheet 文本最大字符数                                                     | `30000`                      |
| `custom_prompt`        | `output_format=custom` 时使用的提示词                                       | `""`                         |
| `thinking_enabled`     | 是否开启思考模式（DeepSeek/MiniMax 生效）                                     | `false`                      |
| `timeout`              | API 请求超时时间（秒）                                                        | `180`                        |
| `crm`                  | CRM 工时接口配置（详见下节）                                                  | -                              |
| `email`                | 邮件发送配置（详见下节）                                                      | -                              |

---

## AI Provider 配置

项目内置 4 家 AI 服务商，均使用 OpenAI 兼容协议，可自由切换。

### 支持的 Provider

| Provider     | 默认模型                | API 地址                                                       | 思考模式         | 获取 API Key                                             |
| ------------ | ----------------------- | -------------------------------------------------------------- | ---------------- | -------------------------------------------------------- |
| `minimax`  | `MiniMax-M3`          | `api.minimaxi.com/v1/chat/completions`                       | 支持（adaptive） | [MiniMax 开放平台](https://platform.minimaxi.com/)        |
| `deepseek` | `deepseek-v4-flash`   | `api.deepseek.com/chat/completions`                          | 支持（enabled）  | [DeepSeek 开放平台](https://platform.deepseek.com/)       |
| `opencode` | `glm-5.2`             | `opencode.ai/zen/v1/chat/completions`                        | 不支持           | [OpenCode Zen](https://opencode.ai/)                      |
| `qwen`     | `qwen3.8-max-preview` | `dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` | 不支持           | [阿里云 DashScope](https://dashscope.console.aliyun.com/) |

### 切换 Provider

**方式 1：修改 config.json**

将 `provider` 字段改为目标 provider 名称：

```json
{
  "provider": "deepseek"
}
```

**方式 2：命令行参数（临时切换）**

```bash
python weekly_report.py --provider deepseek
python weekly_report.py --provider opencode
python weekly_report.py --provider qwen
```

### 环境变量（推荐用于 CI/CD）

为避免在配置文件中暴露 API Key，可使用环境变量：

```powershell
# Windows PowerShell
$env:MINIMAX_API_KEY="sk-xxx"
$env:DEEPSEEK_API_KEY="sk-xxx"
$env:OPENCODE_API_KEY="sk-xxx"
$env:QWEN_API_KEY="sk-xxx"

python weekly_report.py
```

```bash
# Linux / macOS
export MINIMAX_API_KEY="sk-xxx"
python weekly_report.py
```

环境变量会自动覆盖 `config.json` 中对应 provider 的 `api_key` 字段。

### 临时覆盖模型名

```bash
python weekly_report.py --provider opencode --model gpt-5.5
```

---

## CRM 工时接口配置

启用后系统会自动调用 CRM `exportWorkHourItems` 接口，按上一周周一至周五的日期范围下载工时 Excel，无需手动放置文件。

### 配置步骤

#### 1. 获取 CRM 接口 Token

1. 登录你的 CRM 系统（如 `https://crm.example.com`）
2. 打开浏览器开发者工具（F12）→ Network 标签
3. 在 CRM 中执行一次工时明细导出操作
4. 在 Network 列表中找到 `exportWorkHourItems` 请求
5. 从请求头复制以下字段：
   - `authorization`: `Bearer:xxxxx` 中 `Bearer:` **后面**的完整字符串（不含 `Bearer:` 前缀）
   - `userid`: 用户 ID（如 `123456789012345678`）
   - `tyinjectparams`: CRM 注入参数（可选）
6. 从请求体复制 `orgOidList`: 组织 OID 列表（如 `["YOUR_ORG_OID"]`）

> ⚠️ **注意**：authorization 头的格式为 `Bearer:xxxxx`（注意是冒号 `:` 不是空格），配置文件中只需填入 `xxxxx` 部分。

#### 2. 填写 config.json 中的 crm 段

```json
{
  "crm": {
    "enabled": true,
    "url": "https://your-crm-host/ipd/rest/v1/workHourReport/integration/exportWorkHourItems",
    "token": "eyJhbGciOiJIUzUxMiJ9...(你的完整 JWT token)",
    "userid": "YOUR_USER_ID",
    "tyinjectparams": "YOUR_INJECT_PARAMS_OR_EMPTY",
    "org_oid_list": ["YOUR_ORG_OID"],
    "user_oid_list": [],
    "project_oid_list": [],
    "download_dir": "excel_files",
    "timeout": 60
  }
}
```

### CRM 配置字段说明

| 字段                 | 说明                                             | 示例                                              |
| -------------------- | ------------------------------------------------ | ------------------------------------------------- |
| `enabled`          | 是否启用 CRM 接口下载                            | `true` / `false`                              |
| `url`              | CRM 工时导出接口地址                             | `https://your-crm-host/.../exportWorkHourItems` |
| `token`            | authorization 头中`Bearer:` 后面的 JWT token   | `eyJhbGciOiJIUzUxMiJ9...`                       |
| `userid`           | 请求头 userid 字段（CRM 用户 ID）                | `YOUR_USER_ID`                                  |
| `tyinjectparams`   | 请求头 tyinjectparams 字段（CRM 注入参数，可选） | `YOUR_INJECT_PARAMS_OR_EMPTY`                   |
| `org_oid_list`     | 组织 OID 列表                                    | `["YOUR_ORG_OID"]`                              |
| `user_oid_list`    | 用户 OID 列表（可选，留空表示查整个组织）        | `[]`                                            |
| `project_oid_list` | 项目 OID 列表（可选，留空表示不限定项目）        | `[]`                                            |
| `download_dir`     | 下载保存目录（相对脚本目录或绝对路径）           | `excel_files`                                   |
| `timeout`          | CRM 接口请求超时（秒）                           | `60`                                            |

### 日期范围计算

启用 CRM 接口后，系统自动计算**上一周周一至周五**的日期范围：

| 执行日             | 起始日期（周一） | 结束日期（周五） |
| ------------------ | ---------------- | ---------------- |
| 2026-07-22（周三） | 2026-07-13       | 2026-07-17       |
| 2026-07-27（周一） | 2026-07-20       | 2026-07-24       |

如需手动指定日期范围（如生成更早周期的周报）：

```bash
python weekly_report.py --crm-start 2026-07-06 --crm-finish 2026-07-10
```

### CRM Token 环境变量（推荐）

为避免在配置文件中暴露 CRM Token，可使用环境变量：

```powershell
# Windows PowerShell
$env:CRM_TOKEN="eyJhbGciOiJIUzUxMiJ9..."
python weekly_report.py
```

```bash
# Linux / macOS
export CRM_TOKEN="eyJhbGciOiJIUzUxMiJ9..."
python weekly_report.py
```

环境变量会自动覆盖 `config.json` 中的 `crm.token` 字段。

### 跳过 CRM 接口下载

如果本次只想使用本地 Excel 文件（不调用 CRM 接口）：

```bash
python weekly_report.py --no-crm
```

### CRM 接口常见问题

#### 问题 1：`CRM 鉴权失败 (HTTP 401)`

**原因**：token 无效或已过期

**解决方案**：

1. 重新登录 CRM 系统
2. 重新抓取 `exportWorkHourItems` 请求中的最新 token
3. 更新 `config.json` 中的 `crm.token` 或环境变量 `CRM_TOKEN`

> ⚠️ CRM token 通常有效期为 3 小时左右，定时任务运行时可能已过期。建议：
>
> - 短期方案：每周一执行前手动更新 token
> - 长期方案：联系 CRM 管理员申请长期有效的 API token

#### 问题 2：`CRM 接口返回 JSON 但未识别到 Excel 文件数据`

**原因**：接口返回格式异常或权限不足

**解决方案**：检查 `org_oid_list` 是否正确，确认当前账号有权限查看该组织的工时

#### 问题 3：下载的 Excel 文件名为乱码

**原因**：CRM 服务器返回的文件名 URL 编码未正确解码

**解决方案**：脚本已内置 URL 解码逻辑，若仍有问题请检查 CRM 接口返回的 `Content-Disposition` 头格式

---

## 腾讯企业邮箱配置

生成周报后可自动通过腾讯企业邮箱发送邮件给指定人员。

### 配置步骤

#### 1. 开启 SMTP 服务（关键！）

登录腾讯企业邮箱 Web 版 `https://exmail.qq.com`：

1. 点击右上角 **设置**
2. 进入 **客户端**
3. **开启以下两项服务**：
   - `IMAP/SMTP 服务`
   - `POP/SMTP 服务`

> 如果未开启 SMTP 服务，即使密码正确也会返回 `system busy` 错误。

#### 2. 生成客户端专用密码

腾讯企业邮箱**不能使用登录密码**通过 SMTP 发送邮件，必须生成专用密码：

1. 在 **设置 → 客户端** 页面
2. 找到 **"客户端专用密码"** 区域
3. 点击 **"生成"** 或 **"新增专用密码"**
4. 输入一个便于识别的名称（如 `AI周报`）
5. 系统会生成一个 **16 位字母数字** 的密码
6. **立即复制保存**（只显示一次！）

#### 3. 填写 config.json 中的 email 段

```json
{
  "email": {
    "enabled": true,
    "smtp_host": "smtp.exmail.qq.com",
    "smtp_port": 465,
    "sender": "yourname@yourcompany.com",
    "password": "16位客户端专用密码",
    "recipients": ["leader@company.com"],
    "cc": ["colleague@company.com"],
    "subject_template": "Vue 周报 {last_week_range}",
    "attach_report": true
  }
}
```

### 邮件配置字段说明

| 字段                 | 说明                                              | 示例                             |
| -------------------- | ------------------------------------------------- | -------------------------------- |
| `enabled`          | 是否启用邮件发送                                  | `true` / `false`             |
| `smtp_host`        | 腾讯企业邮箱 SMTP 服务器，**不要修改**      | `smtp.exmail.qq.com`           |
| `smtp_port`        | SSL 端口，**不要修改**                      | `465`                          |
| `sender`           | 发件人邮箱（完整企业邮箱地址）                    | `zhangsan@company.com`         |
| `password`         | **客户端专用密码**（16 位，不是登录密码！） | `abcdefghijklmnop`             |
| `recipients`       | 收件人邮箱列表（数组）                            | `["a@xx.com", "b@yy.com"]`     |
| `cc`               | 抄送列表（数组，可为空`[]`）                    | `[]` 或 `["c@xx.com"]`       |
| `subject_template` | 邮件主题模板，支持日期占位符                      | `"Vue 周报 {last_week_range}"` |
| `attach_report`    | 是否附上周报`.md` 文件作为附件                  | `true` / `false`             |

### 邮件主题占位符

`subject_template` 支持以下占位符：

| 占位符                | 含义                           | 示例（周一执行）   |
| --------------------- | ------------------------------ | ------------------ |
| `{last_week_range}` | 上一周日期范围（同年省略年份） | `2026.7.13-7.19` |
| `{last_week_start}` | 上一周周一日期                 | `2026.7.13`      |
| `{last_week_end}`   | 上一周周日日期                 | `2026.7.19`      |
| `{date}`            | 当前日期                       | `2026.7.20`      |

### 邮箱密码环境变量（推荐）

为避免在配置文件中暴露邮箱密码，可使用环境变量：

```powershell
# Windows PowerShell
$env:EMAIL_PASSWORD="你的客户端专用密码"
python weekly_report.py
```

```bash
# Linux / macOS
export EMAIL_PASSWORD="你的客户端专用密码"
python weekly_report.py
```

环境变量会自动覆盖 `config.json` 中的 `email.password` 字段。

### 跳过邮件发送

如果本次只想生成周报，不发送邮件：

```bash
python weekly_report.py --no-email
```

---

## 定时任务与节假日检查

### 定时任务

项目支持通过 Windows 任务计划程序注册定时任务，实现每周一自动执行。

#### 注册定时任务

以**管理员身份**打开 PowerShell：

```powershell
cd C:\path\to\AIWeeklyReportMaster

# 注册每周一 10:00 执行的定时任务
.\register_weekly.ps1
```

脚本会自动：

- 删除同名的旧任务（若存在）
- 注册每周一 10:00 触发的新任务
- 使用当前登录用户身份运行（非 SYSTEM，确保能访问 Python 环境、API Key、邮箱密码）
- 通过 `run_weekly_report.bat` 启动，自动激活虚拟环境并记录日志

#### 管理定时任务

```powershell
# 查看任务状态
Get-ScheduledTask -TaskName "AIWeeklyReport"

# 查看下次运行时间
Get-ScheduledTaskInfo -TaskName "AIWeeklyReport"

# 手动触发任务
Start-ScheduledTask -TaskName "AIWeeklyReport"

# 删除任务
Unregister-ScheduledTask -TaskName "AIWeeklyReport" -Confirm:$false

# 查看执行日志
Get-Content -Path "logs\*.log" -Tail 50
```

#### 定时任务特性

| 特性       | 说明                                                   |
| ---------- | ------------------------------------------------------ |
| 执行账户   | 当前用户（非 SYSTEM，确保能访问 Python 环境和凭据）    |
| 唤醒休眠   | 笔记本休眠也会被唤醒执行                               |
| 错过补执行 | 如果触发时电脑关机，开机会自动补执行                   |
| 超时保护   | 1 小时超时，防止卡死                                   |
| 日志记录   | 每次执行写入`logs/weekly_report_YYYYMMDD_HHMMSS.log` |

### 节假日检查

定时任务在每周一触发后，脚本会自动检查今天是否为节假日：

- **工作日**：正常执行，生成周报并发送邮件
- **法定节假日**（如国庆节、春节）：跳过执行，不生成周报
- **调休上班日**（周末补班）：正常执行
- **普通周末**：跳过执行

#### 判断逻辑（三层优先级）

```
1. 本地硬编码节假日规则（最高优先级）
   ├── 调休上班日（如 2026-10-10 周六补班）→ 正常执行
   └── 法定节假日（如 2026-10-01 国庆）→ 跳过执行
        ↓ 都不匹配
2. 在线 API (timor.tech)
   └── 查询每天的 type: 0=工作日 1=节假日 2=调休 3=周末
        ↓ API 不可用时
3. 周末规则
   └── 周六/周日 → 跳过执行
```

#### 强制执行（跳过节假日检查）

如果需要在节假日手动执行：

```bash
python weekly_report.py --force
```

#### 更新节假日规则

每年国务院发布放假通知后，需要更新 [holiday_checker.py](holiday_checker.py) 中的 `HARDCODED_HOLIDAYS` 字典：

```python
HARDCODED_HOLIDAYS = {
    # 法定节假日（type=1）
    "2026-10-01": ("国庆节", 1),
    "2026-10-02": ("国庆节", 1),
    # ...
    # 调休上班日（type=2）
    "2026-10-10": ("国庆节后调休", 2),
    # ...
}
```

---

## 命令行参数

```bash
python weekly_report.py [OPTIONS]
```

| 参数                | 说明                                          | 示例                           |
| ------------------- | --------------------------------------------- | ------------------------------ |
| `--provider`      | 选择 AI provider                              | `--provider deepseek`        |
| `--model`         | 覆盖 provider 的 model 名称                   | `--model deepseek-v4-pro`    |
| `--format`        | 覆盖输出格式                                  | `--format bullet`            |
| `--output`        | 指定输出文件路径                              | `--output D:\report.md`      |
| `--output-folder` | 周报输出文件夹路径                            | `--output-folder D:\reports` |
| `--folder`        | 指定 Excel 文件夹路径                         | `--folder D:\excels`         |
| `--crm-start`     | CRM 下载起始日期 (YYYY-MM-DD)，默认上一周周一 | `--crm-start 2026-07-06`     |
| `--crm-finish`    | CRM 下载结束日期 (YYYY-MM-DD)，默认上一周周五 | `--crm-finish 2026-07-10`    |
| `--no-crm`        | 跳过 CRM 接口下载，直接使用本地 Excel 文件    | -                              |
| `--dry-run`       | 仅汇总 Excel 内容并打印，不调用 API           | -                              |
| `--thinking`      | 启用思考模式（DeepSeek/MiniMax 生效）         | -                              |
| `--debug`         | 打印详细异常调用栈                            | -                              |
| `--no-email`      | 跳过邮件发送（即使`email.enabled=true`）    | -                              |
| `--force`         | 强制执行，跳过节假日检查                      | -                              |

---

## 输出文件命名

输出文件名通过 `output_file_template` 配置，支持以下占位符：

| 占位符                | 含义                           | 示例（周一 2026.7.20 执行） |
| --------------------- | ------------------------------ | --------------------------- |
| `{date}`            | 当前日期                       | `2026.7.20`               |
| `{last_week_start}` | 上一周周一                     | `2026.7.13`               |
| `{last_week_end}`   | 上一周周日                     | `2026.7.19`               |
| `{last_week_range}` | 上一周日期范围（同年省略年份） | `2026.7.13-7.19`          |
| `{last_week_full}`  | 上一周日期范围（带完整年份）   | `2026.7.13-2026.7.19`     |

### 跨年处理

跨年时自动保留完整年份，避免歧义：

- 2026.1.4（周日）执行 → `Vue2025.12.29-2026.1.4周报.md`
- 同年内 → `Vue2026.7.13-7.19周报.md`

### 日期计算逻辑

无论你哪一天执行，**总是返回上周周一到周日**的范围：

| 执行日  | 上周一     | 上周日    |
| ------- | ---------- | --------- |
| 周一(0) | today - 7  | today - 1 |
| 周二(1) | today - 8  | today - 2 |
| 周三(2) | today - 9  | today - 3 |
| ...     | ...        | ...       |
| 周日(6) | today - 13 | today - 7 |

### 常用模板示例

```json
"output_file_template": "Vue{last_week_range}周报"              // Vue2026.7.13-7.19周报.md
"output_file_template": "周报_{last_week_start}_{last_week_end}"  // 周报_2026.7.13_2026.7.19.md
"output_file_template": "{last_week_start}~{last_week_end}周报"  // 2026.7.13~7.19周报.md
"output_file_template": "周报{last_week_full}"                    // 周报2026.7.13-2026.7.19.md
"output_file_template": "Vue{date}周报"                           // 退回当天日期
```

---

## 使用示例

### 基本用法

```bash
# 使用 config.json 中的默认 provider 生成周报
python weekly_report.py
```

### 切换 AI 服务商

```bash
# 使用 DeepSeek
python weekly_report.py --provider deepseek

# 使用 OpenCode Zen（GLM-5.2）
python weekly_report.py --provider opencode

# 使用通义千问
python weekly_report.py --provider qwen

# 临时覆盖模型名
python weekly_report.py --provider opencode --model gpt-5.5
```

### 启用思考模式

```bash
# DeepSeek / MiniMax 生效，OpenCode / Qwen 不支持
python weekly_report.py --provider deepseek --thinking
```

### 仅汇总 Excel（调试用）

```bash
# 不调用 API，只打印 Excel 汇总结果
python weekly_report.py --dry-run
```

### 跳过邮件发送

```bash
python weekly_report.py --no-email
```

### 切换输出格式

```bash
python weekly_report.py --format plain         # 纯文本
python weekly_report.py --format structured   # 结构化
python weekly_report.py --format bullet        # 项目符号列表
python weekly_report.py --format custom        # 使用 custom_prompt 字段
```

### 指定 Excel 文件夹

```bash
python weekly_report.py --folder "D:\my_excels"
```

### 跳过 CRM 接口下载（使用本地 Excel）

```bash
python weekly_report.py --no-crm
```

### 手动指定 CRM 下载日期范围

```bash
# 生成 2026-07-06 ~ 2026-07-10 的周报
python weekly_report.py --crm-start 2026-07-06 --crm-finish 2026-07-10
```

### 调试模式

```bash
python weekly_report.py --debug
```

### 完整示例

```bash
# 使用 DeepSeek + 思考模式 + 跳过邮件 + 调试
python weekly_report.py --provider deepseek --thinking --no-email --debug
```

---

## 邮件发送失败排查

### 诊断脚本

项目内置了邮件配置诊断脚本，可快速定位问题：

```bash
python diagnose_email.py
```

诊断脚本会：

1. 检查密码长度、格式、空格
2. 测试 SSL 端口 465 连接
3. 测试 STARTTLS 端口 587 连接
4. 显示腾讯返回的具体错误码和错误信息
5. 尝试发送一封测试邮件

### 常见错误及解决方案

#### 错误 1：`535 Error: authentication failed, system busy`

**最常见错误**，原因和解决方案：

| 原因                                | 解决方案                                               |
| ----------------------------------- | ------------------------------------------------------ |
| **SMTP 服务未开启**（最常见） | 登录 Web 邮箱 → 设置 → 客户端 → 开启 IMAP/SMTP 服务 |
| 使用了登录密码而非客户端专用密码    | 生成 16 位客户端专用密码                               |
| 客户端专用密码未真正生成成功        | 重新生成新密码，确保 16 位完整复制                     |
| 账号被风控（频繁失败触发）          | 等待 30-60 分钟后再试                                  |
| 密码复制错误（多了空格或换行）      | 重新复制，注意 JSON 格式                               |

**关键**：`system busy` ≠ 密码错误，通常是服务端配置问题。重点检查 **Web 邮箱中的 SMTP 服务是否已开启**。

#### 错误 2：`邮箱鉴权失败`

```
邮箱鉴权失败：请检查 email.sender 和 email.password 是否正确。
提示：腾讯企业邮箱需使用「客户端专用密码」，而非登录密码。
```

**原因**：密码错误或使用了登录密码

**解决方案**：

1. 登录 `https://exmail.qq.com`
2. 设置 → 客户端 → 客户端专用密码 → 生成新的专用密码
3. 替换 `config.json` 中 `email.password` 字段

#### 错误 3：`无法连接 smtp.exmail.qq.com:465`

**原因**：网络或防火墙问题

**解决方案**：

1. 检查网络连接是否正常
2. 确认公司防火墙未拦截 465 端口
3. 尝试切换网络（如手机热点）测试

#### 错误 4：`收件人被拒绝`

**原因**：收件人邮箱地址错误

**解决方案**：检查 `recipients` 列表中的邮箱地址拼写是否正确

### 获取客户端专用密码的详细步骤

1. 登录腾讯企业邮箱 Web 版 `https://exmail.qq.com`
2. 右上角点击 **设置**
3. 进入 **客户端** 标签页
4. 确认 **IMAP/SMTP 服务** 和 **POP/SMTP 服务** 都已开启
5. 找到 **"客户端专用密码"** 区域
6. 点击 **"生成"** 或 **"新增专用密码"**
7. 输入一个便于识别的名称（如 `AI周报`）
8. 系统会生成一个 **16 位字母数字** 的密码
9. **立即复制保存**（只显示一次！）
10. 将密码填入 `config.json` 的 `email.password` 字段

---

## 常见问题

### Q1: 首次运行报错 `provider 'minimax' 缺少 api_key`

**原因**：默认 provider 是 minimax，但未配置 api_key

**解决方案**：

- 方式 1：在 `config.json` 的 `providers.minimax.api_key` 中填入 MiniMax API Key
- 方式 2：切换到已配置 api_key 的 provider：`python weekly_report.py --provider deepseek`

### Q2: 终端输出中文乱码

**原因**：Windows PowerShell 默认使用 GBK 编码

**解决方案**：

- 脚本已自动设置 UTF-8 输出，无需处理
- 若仍有乱码，使用 **Windows Terminal** 替代旧版 PowerShell
- 或运行前执行：`chcp 65001`

### Q3: Excel 读取警告 `Workbook contains no default style`

**原因**：部分 Excel 文件缺少默认样式定义

**解决方案**：脚本已自动抑制此警告，不影响数据读取

### Q4: 周报内容包含"好的，根据您提供的 Excel 数据..."

**原因**：AI 模型输出对话式前缀

**解决方案**：脚本已内置 `strip_chat_prefix()` 自动清理，无需处理。若仍有残留，请检查是否使用了 `custom` 格式且 `custom_prompt` 中有相关引导语

### Q5: 周报内容重复（草稿 + 正式版）

**原因**：AI 模型输出了草稿、思考独白、正式版多份内容

**解决方案**：脚本已自动取最后一个顶层标题 `# ` 作为真正起点，丢弃草稿和思考过程

### Q6: 周报中包含"本周工作覆盖 8 个 Excel 来源的 103 条原始记录"等元信息

**原因**：AI 引用了汇总过程中的元数据

**解决方案**：脚本已通过提示词约束 + 汇总文本清理双重保险避免此问题。若仍出现，请确认使用的是最新版本代码

### Q7: API 调用超时

**原因**：网络慢、思考模式生成时间长、生成内容较长

**解决方案**：

- 增大 `config.json` 中的 `timeout` 字段（默认 180 秒）
- 或关闭思考模式：`python weekly_report.py`（不加 `--thinking`）

### Q8: 如何查看 token 使用情况

脚本会在每次 API 调用后自动在终端打印 token 统计：

```
[INFO] Token 使用统计:
       - 输入 Prompt tokens : 3,256
       - 其中思考 tokens    : 1,842
       - 输出 Completion    : 1,487
       - 总计 Total tokens  : 4,743
```

### Q9: 周报文件名不对

**原因**：`output_file_template` 配置错误

**解决方案**：检查 `config.json` 中的 `output_file_template` 字段，确保占位符拼写正确

### Q10: 如何安全地管理 API Key 和邮箱密码

**推荐做法**：

1. 将 `config.json` 加入 `.gitignore`，避免提交到版本控制
2. 使用环境变量注入敏感信息：
   ```powershell
   $env:DEEPSEEK_API_KEY="sk-xxx"
   $env:EMAIL_PASSWORD="你的客户端专用密码"
   python weekly_report.py
   ```

---

## 模块说明

### 模块依赖关系

```
weekly_report.py (主入口)
    ├── config_manager.py      (配置)
    ├── crm_downloader.py      (CRM 接口下载 Excel)
    ├── excel_aggregator.py    (Excel 汇总)
    ├── holiday_checker.py     (节假日检查)
    ├── llm_client.py          (LLM 调用)
    │     └── text_utils.py    (文本清理)
    ├── output_resolver.py     (输出路径)
    └── email_sender.py        (邮件发送)
          ├── output_resolver.py  (日期范围复用)
          └── text_utils.py       (Markdown 转 HTML)

register_weekly.ps1 (定时任务注册)
    └── run_weekly_report.bat (定时任务启动脚本)
          └── weekly_report.py (调用主脚本)
```

### 各模块职责

| 模块                                          | 职责                                              | 主要函数                                                     |
| --------------------------------------------- | ------------------------------------------------- | ------------------------------------------------------------ |
| [weekly_report.py](weekly_report.py)           | 主入口、命令行参数、流程编排                      | `main()`, `parse_args()`                                 |
| [config_manager.py](config_manager.py)         | 配置定义、加载、合并、环境变量                    | `load_config()`                                            |
| [crm_downloader.py](crm_downloader.py)         | CRM 工时 Excel 接口下载、日期范围计算、文件名解码 | `download_workhour_excel()`, `calc_last_week_workdays()` |
| [excel_aggregator.py](excel_aggregator.py)     | Excel 文件扫描、任务列识别、跨文件去重            | `aggregate_excel_content()`                                |
| [holiday_checker.py](holiday_checker.py)       | 节假日检查（法定假日 + 调休 + 在线 API）          | `is_holiday()`, `should_skip_execution()`                |
| [llm_client.py](llm_client.py)                 | LLM API 调用、prompt 构建、错误处理               | `call_llm_api()`, `build_prompt()`                       |
| [text_utils.py](text_utils.py)                 | 对话前缀清理、Markdown 转 HTML                    | `strip_chat_prefix()`, `markdown_to_html()`              |
| [output_resolver.py](output_resolver.py)       | 输出路径解析、日期范围计算                        | `resolve_output_path()`, `calc_last_week_range()`        |
| [email_sender.py](email_sender.py)             | 腾讯企业邮箱 SMTP 发送                            | `send_report_email()`                                      |
| [diagnose_email.py](diagnose_email.py)         | 邮件配置诊断                                      | `main()`                                                   |
| [register_weekly.ps1](register_weekly.ps1)     | 注册 Windows 定时任务（每周一 10:00）             | -                                                            |
| [run_weekly_report.bat](run_weekly_report.bat) | 定时任务启动脚本（激活 venv + 运行 Python）       | -                                                            |

### 工作流程

```
┌─────────────────────────────────────────────────────────────┐
│  Step 0: 节假日检查（定时任务触发时）                        │
│  ├─ 检查今天是否法定节假日 / 周末                              │
│  ├─ 节假日 → 跳过执行，退出                                    │
│  └─ 工作日 / 调休上班日 → 继续                                │
├─────────────────────────────────────────────────────────────┤
│  Step 1: CRM 接口下载工时 Excel（启用 crm 时）               │
│  ├─ 自动计算上一周周一至周五日期范围                          │
│  ├─ 调用 CRM exportWorkHourItems 接口                       │
│  ├─ 清理 excel_files/ 中的旧 Excel 文件                      │
│  └─ 保存最新工时 Excel 到 download_dir                       │
│      （未启用 CRM 时跳过此步，使用本地 Excel）                │
├─────────────────────────────────────────────────────────────┤
│  Step 2: Python 读取 Excel 文件夹                            │
│  ├─ 扫描 excel_files/ 下所有 .xlsx/.xls/.xlsm                │
│  └─ 按文件名排序                                             │
├─────────────────────────────────────────────────────────────┤
│  Step 3: Python 全量汇总为文本                                │
│  ├─ 读取每个 Excel 的所有 sheet                               │
│  ├─ 自动识别任务列（任务名称 / 项目/需求任务 / 第一列）        │
│  ├─ 跳过表头、空值、纯数字序号、"总计/合计"行                  │
│  ├─ 跨文件去重（保留首次出现顺序）                             │
│  └─ 拼接为编号列表格式的文本                                   │
├─────────────────────────────────────────────────────────────┤
│  Step 4: AI 优化（调用 LLM API）                             │
│  ├─ System Prompt：周报助手人设 + 严格输出要求                │
│  ├─ User Prompt：格式模板 + Excel 汇总文本                    │
│  ├─ 支持 4 家 Provider：minimax/deepseek/opencode/qwen       │
│  ├─ 可选启用思考模式                                          │
│  └─ 自动清理对话式前缀和重复输出                               │
├─────────────────────────────────────────────────────────────┤
│  Step 5: 输出文件                                             │
│  ├─ 保存到 reports/ 文件夹                                    │
│  ├─ 文件名：Vue{上一周日期范围}周报.md                        │
│  └─ 例如：reports/Vue2026.7.13-7.19周报.md                   │
├─────────────────────────────────────────────────────────────┤
│  Step 6: 发送邮件（可选）                                     │
│  ├─ Markdown 转 HTML 作为邮件正文                            │
│  ├─ 附上周报 .md 文件作为附件                                 │
│  ├─ 通过腾讯企业邮箱 SMTP SSL 发送                            │
│  └─ 支持收件人、抄送列表                                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 依赖

| 依赖         | 用途                   | 安装                     |
| ------------ | ---------------------- | ------------------------ |
| `pandas`   | Excel 数据读取         | `pip install pandas`   |
| `openpyxl` | `.xlsx` 文件解析引擎 | `pip install openpyxl` |
| `requests` | HTTP 请求 LLM API      | `pip install requests` |

其他模块（`smtplib`、`email`、`argparse`、`json`、`re` 等）均为 Python 标准库，无需额外安装。

---

## 许可证

本项目仅用于内部使用。
