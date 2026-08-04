# AI 周报生成器 - 项目流程图

## 一、整体业务流程

```mermaid
flowchart TD
    Start([周一 10:00 定时触发<br/>或手动运行]) --> Lock{获取单实例锁}
    Lock -->|失败<br/>已有进程运行| LockFail([退出 LOCK_FAILED=10])
    Lock -->|成功| Load[加载 config.json<br/>+ 环境变量 + .env]

    Load --> ApplyArgs[应用 CLI 参数覆盖配置<br/>--provider / --output / --folder 等]
    ApplyArgs --> InitLog[初始化日志系统<br/>logs/{周报名}.txt<br/>自动清理 90 天前旧日志]

    InitLog --> Holiday{--force?}
    Holiday -->|是| SkipHoliday[跳过节假日检查]
    Holiday -->|否| CheckHoliday[节假日检查<br/>硬编码规则 > timor.tech API > 缓存 > 周末规则]
    CheckHoliday --> IsHoliday{今天是节假日?}
    IsHoliday -->|是| SkipExec([跳过执行 SUCCESS=0])
    IsHoliday -->|否| SkipHoliday

    SkipHoliday --> CrmCheck{CRM 启用?<br/>--no-crm?}
    CrmCheck -->|启用且未跳过| DownloadCrm[下载 CRM 工时 Excel<br/>自动计算上一周周一至周五]
    CrmCheck -->|禁用或 --no-crm| UseLocal[使用 excel_folder 下<br/>最新修改的本地 Excel]

    DownloadCrm --> CrmOK{下载成功?}
    CrmOK -->|失败| CrmFail[发送失败告警<br/>通知钉钉审核人]
    CrmFail --> ExitCrm([退出 CRM_ERROR=1])
    CrmOK -->|成功| Aggregate

    UseLocal --> Aggregate[Excel 汇总<br/>提取 B/D/H 三列<br/>单文件内去重]
    Aggregate --> DryRun{--dry-run?}
    DryRun -->|是| PrintPreview[打印预览退出]
    PrintPreview --> ExitDry([退出 SUCCESS=0])
    DryRun -->|否| BuildPrompt[构建 AI Prompt]

    BuildPrompt --> CallLLM[调用 LLM API<br/>主 Provider 失败自动降级]
    CallLLM --> LLMOK{生成成功?}
    LLMOK -->|失败| LLMFail[发送失败告警<br/>通知钉钉审核人]
    LLMFail --> ExitLLM([退出 LLM_ERROR=2])
    LLMOK -->|成功| SaveReport[保存周报到文件<br/>reports/Vue{last_week_range}周报.md]

    SaveReport --> DtCheck{钉钉启用?<br/>--no-confirm?}
    DtCheck -->|需审核| WaitForConfirm[钉钉推送预览给审核人<br/>Stream 长连接等待回复]
    DtCheck -->|无需审核| SendDt[直接推送钉钉]

    WaitForConfirm --> ConfirmResult{审核结果}
    ConfirmResult -->|确认| SendDt
    ConfirmResult -->|取消| ExitCancel([跳过发送 SUCCESS=0])
    ConfirmResult -->|超时| ExitTimeout([超时退出])
    WaitForConfirm -->|异常| DtFail[发送失败告警]
    DtFail --> ExitDt([退出 DINGTALK_ERROR=4])

    SendDt --> SendEmail{邮件启用?<br/>--no-email?}
    SendEmail -->|启用且未跳过| SendMail[通过腾讯企业邮箱发送<br/>附件: 周报.md + CRM Excel]
    SendEmail -->|禁用或 --no-email| Done
    SendMail --> MailOK{发送成功?}
    MailOK -->|失败| MailFail[发送失败告警]
    MailFail --> ExitMail([退出 EMAIL_ERROR=3])
    MailOK -->|成功| Done([完成 SUCCESS=0])

    style Start fill:#bbdefb,color:#0d47a1
    style Done fill:#c8e6c9,color:#1a5e20
    style ExitCrm fill:#ffcdd2,color:#b71c1c
    style ExitLLM fill:#ffcdd2,color:#b71c1c
    style ExitMail fill:#ffcdd2,color:#b71c1c
    style ExitDt fill:#ffcdd2,color:#b71c1c
    style ExitCancel fill:#fff3e0,color:#e65100
    style ExitTimeout fill:#fff3e0,color:#e65100
    style ExitDry fill:#fff3e0,color:#e65100
    style SkipExec fill:#fff3e0,color:#e65100
    style LockFail fill:#ffcdd2,color:#b71c1c
```

## 二、模块依赖关系

```mermaid
flowchart LR
    weekly_report[weekly_report.py<br/>主入口]
    config_manager[config_manager.py<br/>配置加载]
    holiday_checker[holiday_checker.py<br/>节假日检查]
    crm_downloader[crm_downloader.py<br/>CRM 下载]
    excel_aggregator[excel_aggregator.py<br/>Excel 汇总]
    llm_client[llm_client.py<br/>AI 调用]
    dingtalk_confirmer[dingtalk_confirmer.py<br/>钉钉审核]
    email_sender[email_sender.py<br/>邮件发送]
    output_resolver[output_resolver.py<br/>路径解析]
    logger[logger.py<br/>日志系统]
    retry_utils[retry_utils.py<br/>重试工具]
    text_utils[text_utils.py<br/>文本处理]

    weekly_report --> config_manager
    weekly_report --> holiday_checker
    weekly_report --> crm_downloader
    weekly_report --> excel_aggregator
    weekly_report --> llm_client
    weekly_report --> dingtalk_confirmer
    weekly_report --> email_sender
    weekly_report --> output_resolver
    weekly_report --> logger

    crm_downloader --> retry_utils
    crm_downloader --> config_manager
    llm_client --> retry_utils
    llm_client --> text_utils
    dingtalk_confirmer --> retry_utils
    dingtalk_confirmer --> config_manager
    email_sender --> output_resolver
    email_sender --> text_utils

    style weekly_report fill:#bbdefb,color:#0d47a1
    style config_manager fill:#c8e6c9,color:#1a5e20
    style holiday_checker fill:#c8e6c9,color:#1a5e20
    style crm_downloader fill:#c8e6c9,color:#1a5e20
    style excel_aggregator fill:#c8e6c9,color:#1a5e20
    style llm_client fill:#c8e6c9,color:#1a5e20
    style dingtalk_confirmer fill:#c8e6c9,color:#1a5e20
    style email_sender fill:#c8e6c9,color:#1a5e20
    style output_resolver fill:#c8e6c9,color:#1a5e20
    style logger fill:#c8e6c9,color:#1a5e20
    style retry_utils fill:#fff3e0,color:#e65100
    style text_utils fill:#fff3e0,color:#e65100
```

## 三、CRM 下载详细流程（含 Token 自动刷新）

```mermaid
sequenceDiagram
    participant Main as weekly_report.py
    participant CRM as crm_downloader
    participant API as CRM 接口
    participant Login as userLoginPlm
    participant FS as config.json

    Main->>CRM: download_workhour_excel(config)
    CRM->>CRM: 验证配置 (url/token/userid)
    CRM->>CRM: 计算日期范围 (上一周周一~周五)
    CRM->>CRM: 清理下载目录中日期重复的旧 Excel

    CRM->>API: POST exportWorkHourItems<br/>Authorization: Bearer:xxx
    API-->>CRM: HTTP 响应

    alt HTTP 401 (Token 失效)
        CRM->>CRM: 尝试刷新 Token (最多 1 次)
        CRM->>Login: POST userLoginPlm<br/>{name, password, appID}
        Login-->>CRM: 200 + Header.authorization=Bearer:eyJ...
        CRM->>FS: 写回新 Token 持久化
        CRM->>API: 重试请求 (新 Token)
        API-->>CRM: HTTP 响应
    end

    alt HTTP 200
        CRM->>CRM: 解析响应 (Excel 二进制 / JSON base64)
        CRM->>FS: 保存 Excel 文件<br/>可视化团队{range}.xlsx
        CRM-->>Main: 返回 Path
    else HTTP 4xx/5xx
        CRM-->>CRM: 抛出 RuntimeError
        CRM-->>Main: 异常向上传递
    end
```

## 四、钉钉人工审核详细流程

```mermaid
sequenceDiagram
    participant Main as weekly_report.py
    participant DT as dingtalk_confirmer
    participant Approver as 审核人钉钉
    participant Stream as 钉钉 Stream 服务

    Main->>DT: wait_for_confirmation(report, config)
    DT->>DT: 读取审核人 approver_staff_ids
    DT->>DT: 构建预览消息 (含周报内容 + 确认/取消提示)
    DT->>Approver: 推送 Markdown 待审核消息 (单聊)

    DT->>Stream: 启动 WebSocket 长连接
    Stream-->>DT: 连接建立

    loop 监听消息 (最多 30 分钟)
        Approver->>Stream: 回复消息 (如"发送"/"取消")
        Stream->>DT: 转发消息
        DT->>DT: 校验 sender_staff_id ∈ 审核人列表
        alt 关键词匹配
            DT->>DT: 设置 done_event
        else 未识别
            DT->>Approver: 回复提示"未识别的指令"
        end
    end

    alt 收到"发送" / "send" / "确认"
        DT->>Approver: 回复"已确认, 正在发送..."
        DT-->>Main: 返回 ("confirm", reason)
    else 收到"取消" / "cancel" / "放弃"
        DT->>Approver: 回复"已取消"
        DT-->>Main: 返回 ("cancel", reason)
    else 超时无回复
        DT->>Approver: 推送超时通知
        DT-->>Main: 返回 ("timeout", reason)
    end
```

## 五、AI Provider 降级调用流程

```mermaid
flowchart TD
    Start[开始调用 LLM] --> Build[构建降级顺序<br/>当前 Provider 优先<br/>其余已配置 api_key 的按序]
    Build --> Loop{遍历 Provider 列表}

    Loop --> Try[调用当前 Provider]
    Try --> Result{结果}
    Result -->|成功| Return[返回周报文本]
    Result -->|配置错误 ValueError| CheckCfg{还有下一个?}
    Result -->|调用失败 RuntimeError| CheckNext{还有下一个?}
    Result -->|未知异常| CheckUnknown{还有下一个?}

    CheckCfg -->|是| NextCfg[切换到下一个]
    NextCfg --> Loop
    CheckCfg -->|否| FailCfg([所有 Provider 配置错误<br/>退出 LLM_ERROR=2])

    CheckNext -->|是| NextProv[切换到下一个]
    NextProv --> Loop
    CheckNext -->|否| AllFail[所有 Provider 均失败]

    CheckUnknown -->|是| Loop
    CheckUnknown -->|否| AllFail

    AllFail --> Alert[发送失败告警<br/>通知钉钉审核人]
    Alert --> ExitFail([退出 LLM_ERROR=2])

    style Return fill:#c8e6c9,color:#1a5e20
    style ExitFail fill:#ffcdd2,color:#b71c1c
    style FailCfg fill:#ffcdd2,color:#b71c1c
```

## 六、关键文件与职责

| 文件 | 职责 |
|------|------|
| [weekly_report.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/weekly_report.py) | 主入口，编排全流程 |
| [config_manager.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/config_manager.py) | 加载配置、默认值合并、环境变量覆盖、通知模板渲染 |
| [holiday_checker.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/holiday_checker.py) | 节假日检查（硬编码 > 在线 API > 缓存 > 周末规则） |
| [crm_downloader.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/crm_downloader.py) | CRM 工时 Excel 下载、Token 自动刷新 |
| [excel_aggregator.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/excel_aggregator.py) | 提取 B/D/H 三列、单文件内去重 |
| [llm_client.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/llm_client.py) | LLM API 调用、OpenAI 兼容协议 |
| [dingtalk_confirmer.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/dingtalk_confirmer.py) | 钉钉审核流程、Stream 长连接、失败告警 |
| [email_sender.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/email_sender.py) | 腾讯企业邮箱 SMTP 发送 |
| [output_resolver.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/output_resolver.py) | 输出路径解析、日期占位符替换 |
| [logger.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/logger.py) | 日志系统（tee stdout/stderr 到文件） |
| [retry_utils.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/retry_utils.py) | 通用 HTTP 重试工具（指数退避） |
| [text_utils.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/text_utils.py) | 文本清洗、Markdown 转 HTML |
| [dingtalk_userid.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/dingtalk_userid.py) | 钉钉 userId 查询工具 |
| [dingtalk_send_notice.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/dingtalk_send_notice.py) | 钉钉通知发送工具 |
| [diagnose_email.py](file:///c:/Users/w/Desktop/InteVueWeb/AIWeeklyReportMaster/diagnose_email.py) | 邮箱 SMTP 诊断工具 |

## 七、退出码定义

| 退出码 | 含义 | 触发场景 |
|--------|------|---------|
| 0 | 成功 | 周报生成并发送完成，或节假日跳过、dry-run、用户取消等正常退出 |
| 1 | CRM 错误 | CRM 下载失败、Excel 文件夹不存在 |
| 2 | LLM 错误 | 所有 AI Provider 均失败 |
| 3 | 邮件错误 | SMTP 发送失败 |
| 4 | 钉钉错误 | 钉钉审核流程异常、发送失败 |
| 10 | 锁失败 | 已有进程运行，拒绝启动 |

## 八、关键设计决策

1. **单文件处理**：不再扫描目录、不做跨文件合并，只处理 CRM 下载的或最新的单个 Excel 文件
2. **列字母优先**：提取 B/D/H 列时优先按表头名匹配，失败时回退到列字母，保证 CRM 与手工 Excel 都能处理
3. **Token 自动刷新**：CRM JWT 失效时自动调用登录接口刷新，持久化到 config.json
4. **Provider 降级**：当前 Provider 失败时自动切换到其他已配置 api_key 的 Provider
5. **Stream 自实现监听**：避免 SDK 的 `start()` 无限重连问题，支持 `done_event` 优雅退出
6. **日志 tee 机制**：通过包装 stdout/stderr，所有 print 输出同步写入日志文件
7. **节假日三级兜底**：硬编码规则 > 在线 API > 缓存 > 周末规则
8. **通知模板系统**：支持多通知类型，自动注入联系方式占位符
