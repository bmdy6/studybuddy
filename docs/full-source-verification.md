# 完整源码与 README 验证（2026-11-11）

来源：原 main `4c2c984` 的只读 Git archive，公开基线 `7f1e31d`；分支 `feat/full-source-readme`。没有使用原仓库的未提交内容。

## 自动化结果

| 检查 | 结果 |
| --- | --- |
| 后端完整 pytest | **1303 passed, 50 skipped**，434.21 秒；50 项均为需显式 `--run-live` 的真实模型测试 |
| 微信 Bot pytest | **27 passed**（原 23 + 空内部 token 的 4 项回归） |
| 前端 Vitest | **52 files / 342 passed** |
| 主前端 lint / typecheck / build | 全部通过 |
| 官网独立 build:landing | 通过 |
| HobbyBuddy 后端 pytest | **10 passed**，SQLite 内存库、模型与搜索 mock；也按 CI 的仓库根目录调用方式复验通过 |
| HobbyBuddy 客户端 lint / typecheck / build | 全部通过；原 lint 脚本实际为 tsc，无独立前端 test 脚本 |
| 脱敏后的题源测试夹具复跑 | **55 passed**；不重复计入后端总数 |
| git diff --check | 通过 |

后端 7 条 warning 属于依赖弃用提示；前端有 jsdom 的 pseudo-element getComputedStyle 提示，不影响测试结果。Bot 的 pytest-asyncio 有 fixture loop scope 配置弃用提示。没有真实模型调用，调用预算为 **0**。

## 隔离与真实页面

新建 `mysql:8.4` 容器，绑定 `127.0.0.1:33383`，`/var/lib/mysql` 使用 tmpfs；测试库 `studybuddy_issue3_test` 与演示库 `readme_demo_test` 均只含合成数据。未连接既有容器、个人 MySQL 或生产数据库。服务只监听本机。

Headless Chromium 149.0.7827.55 实际访问 React → FastAPI → MySQL：

- 页面点击「确认并创建」返回 200，切换到计划页后新计划仍可见。
- 手机端任务会话刷新后，已保存的作答与后续练习起点仍可见。
- 微信关闭、模型 key 为空时，上述主流程可用；浏览器没有请求微信 API。进一步移除所有微信环境变量重启后，真实登录、读取已确认计划和手机任务刷新也通过。
- 官网在 320 / 768 / 1024 / 1440px 验证图片加载、CTA 指向与无水平溢出。修正了原版 768px 截图卡片约 12px 溢出。

截图使用手写的虚构数据，不能证明模型教学效果。微信日报正文确由 `build_parent_daily_summary` 读取合成数据生成；气泡是明确标注的示意，未向真实微信发送。完整来源与复现见 [截图说明](images/SOURCES.md)。

## 脱敏

全工作树执行 `gitleaks dir . --redact`，最终 **0 findings**。中途检测到的 2 项为截图脚本生成且被 Git 忽略的合成登录 JWT；完成浏览器检查后已删除并重新扫描，不是通过添加扫描豁免掩盖。

人工检索手机号、邮箱、真实姓名/学校、IP、域名、`sk-`：私人服务域名已替换为本机或 example.invalid；真实学校示例（含旧公开夹具中的残留）替换为「示例学校」。保留的 IP 均为回环地址、协议/版本测试字符串；`@im.wechat` / `@im.bot` 是合成协议身份，非真实邮箱。公开第三方资源与模型/微信官方域名保留，package.json 的作者署名 `xiaoliang` 保留。未发现需公开核实的未知凭据或个人身份数据。

原版 `app` 和客户端 `src` 中所有源文件在公开版都有对应路径；已有开源修复未回退。未搬文件逐项见 [manifest](source-import-manifest.json)，包括真实样本、旧二维码、私有部署配置与含运行记录的文档。未读取未跟踪的密钥、数据库、上传或日志。

## 本次边界

没有部署、数据迁移、真实模型、真实微信扫码/投递、COS、外部搜索或 OCR 供应商端到端验收。Bot 的扫码状态机、鉴权、恢复、白名单和消息状态由合成适配器测试。修复空内部 token 时先复现 4 failed / 23 passed，再实现校验，最终 27 passed。

GitHub README 的图片、表格与 Mermaid 渲染截图及 PR 地址在交付记录中另行回读确认；不把本地 Markdown 预览算作 GitHub 渲染证据。
