# AI 周报生成器 — 项目流程图

> 本文档用 Mermaid 描述整个项目的业务流程、模块依赖与各脚本执行路径。
> 阅读方式：GitHub / Typora / VS Code 安装 Mermaid 插件后可直接渲染。

---

## 一、整体业务流程（weekly_report.py 主流程）

```mermaid
flowchart TD
    Start([周一定时触发<br/>或手动运行]) --> Lock{获取单实例锁}
    Lock -->|已有进程运行| LockFail([退出 LOCK_FAILED=10])
    Lock -->|成功| Load[加载 config.json<br/>+ 环境变量 + .env]
    Load --> ApplyArgs[CLI 参数覆盖配置<br/>--provider/--model/--format/--folder 等]
    ApplyArgs --> Validate[启动关键配置校验<br/>AI api_key / CRM / 邮箱 / 钉钉凭证]
    Validate -->|缺失| CfgError([退出 CONFIG_ERROR=11])
    Validate -->|通过| InitLog[初始化日志<br/>logs/{周报名}.txt<br/>清理 90 天前旧日志]

    InitLog --> Force{--force?}
    Force -->|是| SkipHoliday[跳过节假日检查]
    Force -->|否| CheckHoliday[节假日检查<br/>硬编码 > timor.tech API > 缓存 > 周末规则]
    CheckHoliday --> IsHoliday{今天是节假日/周末?}
    IsHoliday -->|是| SkipExec([正常退出 SUCCESS=0<br/>不生成周报])
    IsHoliday -->|否| SkipHoliday

    SkipHoliday --> CrmOn{CRM 启用<br/>且未 --no-crm?}
    CrmOn -->|是| DownloadCrm[下载 CRM 工时 Excel<br/>计算上一周周一~周五<br/>清理日期重复旧文件]
    CrmOn -->|否| UseLocal[取 excel_folder 下<br/>最新修改的本地 Excel]

    DownloadCrm --> CrmOk{下载成功?}
    CrmOk -->|失败| CrmFail[发送失败告警<br/>通知钉钉审核人]
    CrmFail --> ExitCrm([退出 CRM_ERROR=1])
    CrmOk -->|成功| Aggregate[Excel 汇总<br/>提取 B/D/H 三列 + F/G/I 时间工时<br/>单文件内去重]
    UseLocal --> Aggregate

    Aggregate --> DryRun{--dry-run?}
    DryRun -->|是| Print[打印汇总结果]
    Print --> ExitDry([正常退出 SUCCESS=0])
    DryRun -->|否| BuildPrompt[构建 AI Prompt<br/>格式模板 + 汇总文本]

    BuildPrompt --> CallLLM[调用 LLM API<br/>provider 失败自动降级<br/>--thinking 可选]
    CallLLM --> LLMOk{生成成功?}
    LLMOk -->|失败| LLMFail[发送失败告警]
    LLMFail --> ExitLLM([退出 LLM_ERROR=2])
    LLMOk -->|成功| Save[保存周报<br/>reports/Vue{last_week_range}周报.md]

    Save --> DtNeed{钉钉启用<br/>且未 --no-confirm?}
    DtNeed -->|需审核| Review[推送预览给审核人<br/>Stream 长连接等待回复]
    DtNeed -->|免审| DirectDt[直接推送钉钉给接收人]

    Review --> ReviewRs{审核结果}
    ReviewRs -->|确认"发送"| DirectDt
    ReviewRs -->|取消"取消/放弃"| ExitOk1([正常退出 SUCCESS=0<br/>周报文件保留，不发送])
    ReviewRs -->|反馈问题| Regen[重新调 LLM 修订周报<br/>再次推送审核（可多轮）]
    Regen --> Review
    ReviewRs -->|30 分钟超时| Timeout1([超时自动放弃])
    Review -->|流程异常| DtErr[发送失败告警]
    DtErr --> ExitDt([退出 DINGTALK_ERROR=4])

    DirectDt --> MailOn{邮件启用<br/>且未 --no-email?}
    MailOn -->|是| SendMail[发送邮件<br/>正文: Markdown 转 HTML<br/>附件: 周报.md + CRM Excel]
    MailOn -->|否| Done([完成 SUCCESS=0])
    SendMail --> MailOk{发送成功?}
    MailOk -->|失败| MailFail[发送失败告警]
    MailFail --> ExitMail([退出 EMAIL_ERROR=3])
    MailOk -->|成功| Done

    style Start fill:#bbdefb,color:#0d47a1
    style Done fill:#c8e6c9,color:#1a5e20
    style SkipExec fill:#fff3e0,color:#e65100
    style ExitDry fill:#fff3e0,color:#e65100
    style ExitOk1 fill:#fff3e0,color:#e65100
    style Timeout1 fill:#fff3e0,color:#e65100
    style LockFail fill:#ffcdd2,color:#b71c1c
    style CfgError fill:#ffcdd2,color:#b71c1c
    style ExitCrm fill:#ffcdd2,color:#b71c1c
    style ExitLLM fill:#ffcdd2,color:#b71c1c
    style ExitEmail fill:#ffcdd2,color:#b71c1c
    style ExitDt fill:#ffcdd2,color:#b71c1c
```

---

## 二、模块全景依赖关系

```mermaid
flowchart LR
    subgraph Scheduled[定时任务与独立脚本]
        weekly[weekly_report.py<br/>周报主流程]
        reminder[crm_reminder.py<br/>周五 CRM 填写提醒]
        attendance[attendance_checker.py<br/>考勤查询]
        chat[dingtalk_chatbot.py<br/>AI 问答机器人（常驻）]
        notice[dingtalk_send_notice.py<br/>周报通知发送]
        userid[dingtalk_userid.py<br/>userId 查询工具]
    end

    subgraph Core[公共核心模块]
        cfg[config_manager.py<br/>配置加载/校验/渲染]
        lgr[logger.py<br/>日志系统]
        dtx[dingtalk_confirmer.py<br/>钉钉收发/审核底层]
        llm[llm_client.py<br/>AI 调用/降级]
        crmd[crm_downloader.py<br/>CRM 下载/Token 刷新]
        excel[excel_aggregator.py<br/>Excel 汇总]
        holi[holiday_checker.py<br/>节假日检查]
        outp[output_resolver.py<br/>路径/日期解析]
        mail[email_sender.py<br/>邮件发送]
        retry[retry_utils.py<br/>HTTP 重试]
        text[text_utils.py<br/>文本处理]
    end

    weekly --> cfg & lgr & crmd & excel & holi & llm & outp & mail & dtx
    reminder --> cfg & lgr & holi & dtx
    attendance --> cfg & lgr & dtx & retry
    chat --> cfg & lgr & dtx & llm
    notice --> cfg & lgr & dtx
    userid --> cfg & lgr & dtx

    crmd --> retry & cfg
    llm --> retry & text
    dtx --> retry & cfg
    mail --> outp & text
    excel --> cfg
    holi --> cfg

    style weekly fill:#bbdefb,color:#0d47a1
    style cfg fill:#c8e6c9,color:#1a5e20
    style lgr fill:#c8e6c9,color:#1a5e20
    style dtx fill:#c8e6c9,color:#1a5e20
    style llm fill:#c8e6c9,color:#1a5e20
    style retry fill:#fff3e0,color:#e65100
    style text fill:#fff3e0,color:#e65100
```

---

## 三、定时任务链

```mermaid
flowchart LR
    subgraph WeeklyChain[周报主流程]
        wps[register_weekly.ps1<br/>每周一 10:00<br/>需管理员注册]
        wbat[run_weekly_report.bat<br/>激活 venv + 运行]
        weekly[weekly_report.py]
        wps --> wbat --> weekly
    end

    subgraph RemindChain[CRM 提醒流程]
        rps[register_crm_reminder.ps1<br/>每周五 15:00<br/>需管理员注册]
        rbat[run_crm_reminder.bat<br/>激活 venv + 运行]
        rem[crm_reminder.py --yes]
        rps --> rbat --> rem
    end

    weekly -->|周一生成并发送周报| Out[周报 + 邮件 + 钉钉推送]
    rem -->|周五提醒成员填 CRM 工时| Notify[钉钉群消息 @ 成员]

    style weekly fill:#bbdefb,color:#0d47a1
    style rem fill:#ffe0b2,color:#e65100
```

---

## 四、CRM 下载详细流程（含 Token 自动刷新）

```mermaid
sequenceDiagram
    participant Main as weekly_report.py
    participant CRM as crm_downloader
    participant API as CRM 工时接口
    participant Login as userLoginPlm
    participant FS as config.json / 磁盘

    Main->>CRM: download_workhour_excel(config)
    CRM->>CRM: 验证配置 url/token/userid
    CRM->>CRM: 计算上一周周一~周五日期范围
    CRM->>CRM: 清理下载目录中日期重复的旧 Excel

    CRM->>API: POST exportWorkHourItems<br/>Authorization: Bearer:xxx
    API-->>CRM: HTTP 响应

    alt HTTP 401（Token 失效）
        CRM->>CRM: 尝试刷新 Token（限 1 次）
        CRM->>Login: POST userLoginPlm<br/>{name, password, appID}
        Login-->>CRM: 200 + authorization = Bearer:eyJ...
        CRM->>FS: 新 Token 加密落盘<br/>enc:v1:...（DPAPI / 机器码混淆）
        CRM->>API: 用新 Token 重试
        API-->>CRM: HTTP 响应
    end

    alt HTTP 200
        CRM->>CRM: 解析响应（Excel 二进制 / JSON base64）
        CRM->>FS: 保存 Excel<br/>{prefix}{日期范围}.xlsx
        CRM-->>Main: 返回文件路径
    else HTTP 4xx/5xx
        CRM-->>CRM: 抛出 RuntimeError
        CRM-->>Main: 异常向上传递 → CRM_ERROR
    end
```

---

## 五、钉钉人工审核流程

```mermaid
sequenceDiagram
    participant Main as weekly_report.py
    participant DT as dingtalk_confirmer
    participant Approver as 审核人（钉钉）
    participant Stream as 钉钉 Stream 长连接
    participant LLM as llm_client

    Main->>DT: wait_for_confirmation(report, config)
    DT->>DT: 构建预览消息（周报内容 + 确认/取消提示）
    DT->>Approver: 推送 Markdown 待审核消息（单聊）
    DT->>Stream: 启动 WebSocket 长连接

    loop 监听回复（默认最多 30 分钟）
        Approver->>Stream: 发送"发送"/"取消"/反馈
        Stream->>DT: 转发消息
        DT->>DT: 校验 sender 是否在审核人列表
        alt 命中确认关键词 "发送/send/确认/ok"
            DT->>DT: 标记已确认
        else 命中取消关键词 "取消/cancel/放弃/不发送"
            DT->>DT: 标记已取消
        else 其他文本 = 修改反馈
            DT->>LLM: call_llm_chat 修订周报<br/>(build_revision_messages)
            LLM-->>DT: 修订版周报
            DT->>Approver: 再次推送审核（可多轮）
        end
    end

    alt 确认
        DT-->>Main: 返回 (confirm)
    else 取消
        DT-->>Main: 返回 (cancel)
    else 超时
        DT->>Approver: 推送超时通知
        DT-->>Main: 返回 (timeout)
    end
```

---

## 六、AI Provider 降级调用流程

```mermaid
flowchart TD
    S[开始调用 LLM<br/>call_llm_api / call_llm_chat] --> Build[确定调用顺序<br/>主 provider 优先<br/>fallback_providers + 其余已配 api_key 依次]
    Build --> Loop{遍历 provider 列表}
    Loop --> Try[调用当前 provider<br/>构建 payload + POST]
    Try --> Rs{结果}
    Rs -->|成功| Ret([返回文本<br/>strip_chat_prefix 清理])
    Rs -->|ValueError 配置错误| N1{还有下一个?}
    Rs -->|RuntimeError 调用失败| N2{还有下一个?}

    N1 -->|是| Next1[切换下一个 provider]
    Next1 --> Loop
    N1 -->|否| AllFail1[所有 provider 配置错误]
    N2 -->|是| Next2[切换下一个 provider]
    Next2 --> Loop
    N2 -->|否| AllFail2[所有 provider 均失败]

    AllFail1 --> Alert[发送失败告警<br/>通知钉钉审核人]
    AllFail2 --> Alert
    Alert --> ExitFail([退出 LLM_ERROR=2])

    style Ret fill:#c8e6c9,color:#1a5e20
    style ExitFail fill:#ffcdd2,color:#b71c1c
```

> 内置 provider：`minimax` / `deepseek` / `opencode` / `qwen` / `volc_glm`（火山方舟 GLM-5.3）
> 以及 `opencode_deepseek`，均可通过 `--provider` 切换，配置见 `config.json` 的 `providers` 段。

---

## 七、CRM 提醒脚本（crm_reminder.py）

```mermaid
flowchart TD
    S([register_crm_reminder.ps1<br/>每周五 15:00 触发]) --> B[run_crm_reminder.bat<br/>python crm_reminder.py --yes]
    B --> L[load_config]
    L --> C1{dingtalk.enabled?}
    C1 -->|否| E1([退出 1 配置错误])
    C1 -->|是| C2{crm_reminder.enabled?}
    C2 -->|否| E1
    C2 -->|是| C3{获取钉钉凭证 success}
    C3 -->|失败| E1
    C3 -->|成功| Week{今天是周五?<br/>send_weekday 默认 4}
    Week -->|否| E0([退出 0 正常跳过])
    Week -->|是| Holi{skip_holiday 且<br/>今天为节假日?}
    Holi -->|是| E0
    Holi -->|否| Conv{校验 conversation_id}
    Conv -->|缺失| E1
    Conv -->|成功| Render[渲染提醒模板<br/>notification.templates.crm_reminder<br/>注入成员姓名]
    Render --> Confirm{--yes 跳过确认?}
    Confirm -->|否| Pre[终端预览确认]
    Confirm -->|是| Send[钉钉群发 markdown<br/>@ remind_user_ids 成员]
    Send --> Ok{成功?}
    Ok -->|失败 RuntimeError| E2([退出 2 发送失败])
    Ok -->|成功| Done([退出 0])

    style Done fill:#c8e6c9,color:#1a5e20
    style E0 fill:#fff3e0,color:#e65100
    style E1 fill:#ffcdd2,color:#b71c1c
    style E2 fill:#ffcdd2,color:#b71c1c
```

---

## 八、考勤检查脚本（attendance_checker.py）

```mermaid
flowchart TD
    S([手动运行 attendance_checker.py]) --> L[load_config]
    L --> Target{查询目标}
    Target -->|--userids| U[逗号分隔的 userId 列表]
    Target -->|--dept| D[部门 ID → 列出部门成员]
    Target -->|默认| Dflt[config.attendance.user_ids<br/>回退钉钉接收人/审核人]

    U & D & Dflt --> Range{日期范围}
    Range -->|--start/--end| R1[指定范围]
    Range -->|config.attendance 起止| R2[配置范围]
    Range -->|默认| R3[最近 7 天]

    R1 & R2 & R3 --> Chunk[按 7 天/段自动分片<br/>单次接口限 7 天 50 人]
    Chunk --> Token[经 dingtalk_confirmer<br/>获取 OAPI access_token]
    Token --> Query[POST oapi.dingtalk.com/attendance/list<br/>retry_utils 重试]
    Query --> Parse[解析打卡结果<br/>正常/迟到/旷工等]
    Parse --> Show[打印明细矩阵<br/>--excel 导出到 attendance_output/]

    style Show fill:#c8e6c9,color:#1a5e20
```

---

## 九、钉钉 AI 问答机器人（dingtalk_chatbot.py）

```mermaid
flowchart TD
    S([常驻运行 dingtalk_chatbot.py]) --> L[load_config]
    L --> E1{chatbot.enabled?}
    E1 -->|否| Exit0([退出 0])
    E1 -->|是| E2{dingtalk-stream 已安装?}
    E2 -->|否| Exit1([退出 1])
    E2 -->|是| E3{获取钉钉凭证}
    E3 -->|失败| Exit1
    E3 -->|成功| Handler[实例化 ChatbotLLMHandler<br/>start_forever 常驻]

    Handler --> Msg[收到钉钉消息]
    Msg --> Strip[去除 @ 机器人前缀]
    Strip --> Auth{allow_user_ids 白名单非空<br/>且发送人不在内?}
    Auth -->|是| Deny([拒绝回复])
    Auth -->|否| GType{群聊?}
    GType -->|群聊且未 @ 机器人| Ignore([忽略])
    GType -->|其他| Sess[按会话取上下文<br/>单聊按人 / 群聊按群]
    Sess --> Reset{命中 reset 关键词?<br/>清空/重置//clear}
    Reset -->|是| Clear[清空该会话历史]
    Reset -->|否| Call[llm_client.call_llm_chat<br/>system_prompt = 人设参数<br/>携带最近 N 轮历史]
    Call --> Reply[回复 markdown<br/>超 max_reply_chars 截断]
    Clear --> Reply

    style Reply fill:#c8e6c9,color:#1a5e20
```

---

## 十、退出码定义

| 退出码 | 含义 | 触发场景 |
|--------|------|----------|
| 0 | 成功 | 周报生成并发送完成、节假日跳过、`--dry-run`、审核未确认取消等正常退出 |
| 1 | CRM / 配置错误 | CRM 下载失败、Excel 文件缺失、独立脚本（提醒/通知）配置缺失 |
| 2 | LLM 错误 | 所有 AI Provider 均失败；通知/提醒脚本发送失败 |
| 3 | 邮件错误 | SMTP 发送失败 |
| 4 | 钉钉错误 | 钉钉审核流程异常、推送失败 |
| 10 | 锁失败 | 已有周报进程运行，拒绝重复启动 |
| 11 | 配置校验失败 | 启动时关键配置缺失（`validate_required_config` 抛错） |

---

## 十一、关键文件职责

| 文件 | 职责 |
|------|------|
| [weekly_report.py](../weekly_report.py) | 主入口，编排全流程（下载 → 汇总 → AI → 审核 → 发送） |
| [config_manager.py](../config_manager.py) | 配置加载/默认值合并/环境变量覆盖/启动校验/通知模板渲染 |
| [crm_downloader.py](../crm_downloader.py) | CRM 工时 Excel 下载、日期范围计算、Token 自动刷新与加密落盘 |
| [excel_aggregator.py](../excel_aggregator.py) | 单文件列识别（B/D/H）+ 去重汇总 |
| [llm_client.py](../llm_client.py) | OpenAI 兼容 AI 调用、prompt 构建、provider 降级、token 统计 |
| [dingtalk_confirmer.py](../dingtalk_confirmer.py) | 钉钉消息唯一发送实现：审核流、Stream 监听、单聊/群聊推送、凭证与 OAPI token |
| [email_sender.py](../email_sender.py) | 腾讯企业邮箱 SMTP 发送（Markdown 转 HTML + 附件） |
| [holiday_checker.py](../holiday_checker.py) | 节假日判断（硬编码 > timor.tech API > 缓存 > 周末规则） |
| [output_resolver.py](../output_resolver.py) | 输出路径解析、上一周日期范围、模板占位符 |
| [logger.py](../logger.py) | 控制台 + 日志文件双写，按周报名称落盘，自动清理旧日志 |
| [retry_utils.py](../retry_utils.py) | 通用 HTTP 指数退避重试 |
| [text_utils.py](../text_utils.py) | 对话前缀清理、Markdown 转 HTML |
| [crm_reminder.py](../crm_reminder.py) | 每周五 CRM 工时填写提醒（独立定时任务） |
| [attendance_checker.py](../attendance_checker.py) | 钉钉考勤记录查询与导出 |
| [dingtalk_chatbot.py](../dingtalk_chatbot.py) | AI 问答机器人（常驻 Stream 进程） |
| [dingtalk_send_notice.py](../dingtalk_send_notice.py) | 群发周报"已生成"通知（单聊） |
| [dingtalk_userid.py](../dingtalk_userid.py) | 查询部门/手机号 userId、群 conversationId 工具 |
| [register_weekly.ps1](../register_weekly.ps1) / [register_crm_reminder.ps1](../register_crm_reminder.ps1) | 注册 Windows 计划任务（周一 10:00 / 周五 15:00） |
| [run_weekly_report.bat](../run_weekly_report.bat) / [run_crm_reminder.bat](../run_crm_reminder.bat) | 定时任务启动脚本（激活 venv + 运行 + 记日志 + 透传退出码） |