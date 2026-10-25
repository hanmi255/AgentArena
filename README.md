# AgentArena

多智能体商业经营沙盘。让不同经营策略在同一市场竞争，用实际成交、库存和现金流检验 Agent 的决策。

## 启动

需要 Python 3.11+、Node.js 20.19+。Windows PowerShell：

```powershell
cd AgentArena
./setup.ps1
./start.ps1
```

macOS / Linux：

```bash
cd AgentArena
bash setup.sh
bash start.sh
```

打开 **http://127.0.0.1:8010** 首次启动自动运行一场真实的规则策略示例赛，并创建一场待开始的对局。之后启动保留已有数据。

默认规则模式不需要模型账号。进入「运行设置」添加模型连接，填写服务地址、模型名和 API Key。测试连接直接使用当前表单，验证工具调用及结果回传，不必先保存。保存后可复制连接、保留原 Key 并修改模型名。

DeepSeek 地址为 `https://api.deepseek.com`，可分别保存 `deepseek-flash`、`deepseek-v4-pro` 两个连接。在创建对局时把两家商店切换为 LLM Agent，分别选择连接，即可同场比较。兼容自定义模型名和兼容 API 服务；各连接独立设置思考模式、超时、输出 Token 上限与可选成本单价。实际调用产生服务商费用。

DeepSeek 专用适配器保留思考模式工具回传所需的 `reasoning_content`，方案通过原生 JSON 模式提交，由 Pydantic 校验；内部推理不展示在工作台。[官方思考协议](https://api-docs.deepseek.com/guides/thinking_mode/)

## 全景赛场

打开对局默认进入全景赛场：2–4 家商店同时显示 Agent 动作、货架、拟定价格与补货、报价轨迹、现金、销量和收益。桌面并排显示，窄屏使用两列，不需要切换商店。所有动画来自真实事件，后端不等待动画播放；销售动画表示已完成的回合结算。

- 一条事件游标同步回放全店；支持暂停、变速、关键回合跳转。回放使用当轮起点和结算事件，不提前显示后续余额。
- 店铺「详情」查看流程与完整决策；经营数据、账本、执行记录保留在次级视图。谈判原文默认收起。
- 实验室以收益／每轮 Token 或耗时图和摘要卡展示结果，完整指标展开查看；分叉对照增加原策略与新策略收益曲线。
- 自主模式在稳定局势只生成一个方案，风险或退回时扩展候选。模型只接收经营字段；工具预算贯穿自动修订。切换为 LLM 默认关闭谈判，预算 3 次，新连接默认 Flash、关闭思考、输出上限 2,048。

## 决策系统升级

已增加自主规划、实时节点与工具动画、候选对比、供应商多轮协商、经验检索、持久化人工审批、历史回合分叉和能力消融。

新建对局默认启用自主规划、经验检索与供应商协商；可逐店关闭以做对照。规则模式仍不需要 Key。人工审批默认关闭，可在创建时选择风险触发或每轮审批。

## 可以做什么

- 创建 2–4 家商店参与的对局，选择街区日常、周末市集或供应危机，设定种子、资金与 3–60 个经营回合。
- 混合规则策略与真实模型 Agent，运行、暂停、继续或单步结算。
- 编辑和复制策略；模型 Agent 使用策略提示词，规则模式使用毛利、库存与营销参数。
- 每店独立选择模型和「标准决策 / 试算与审核 / 自主规划」。审核流程生成多个候选，进行三种需求情景试算，再由独立审核 Agent 复核，必要时最多修订两次。
- 查看利润曲线、排名、库存、采购、销量、逐笔账本及 Agent 工具调用、结构化方案和跨回合记忆。
- 按历史回合回放、自动播放，导出完整 JSON 或账本 CSV；使用相同配置从零再赛。
- 在实验室使用多个种子并轮换策略席位，比较平均收益、收益波动和胜率；支持导出结果。
- 同策略可对照不同模型和流程，输出收益区间、种子配对差值、断货率、周转、回撤、Token、成本估算与耗时。开发与保留集登记种子禁止重叠。
- 后台任务持久化，支持独立 worker、心跳租约、过期接管和瞬时错误退避重试；对局中可查看执行记录。

已创建的对局和实验保存策略快照，修改策略库不会改变历史配置。相同种子可重现规则模式结果；真实模型的输出不保证确定性。

## 技术组成

| 层     | 实现                                                                       |
| ------ | -------------------------------------------------------------------------- |
| 工作台 | React、TypeScript strict、Vite、响应式布局、SSE                            |
| API    | FastAPI、Pydantic、后台异步调度                                            |
| Agent  | LangChain `create_agent`、工具预算中间件、JSON / ToolStrategy 结构化方案 |
| 编排   | LangGraph 条件分支、规划 / 试算 / 审核 / 修订，内外层 checkpoint           |
| 结算   | 独立确定性引擎，整数分记账、库存成本核算                                   |
| 存储   | SQLite WAL、事务、唯一约束、历史快照                                       |
| 调度   | SQLite 持久化任务、事务 Outbox、租约与独立 worker；可启用 Redis Streams    |

## 代码结构

```text
arena/
  api/             HTTP API、SSE、导出与前端托管
  application/     比赛编排、业务事务、快照与分叉
  agents/          规划、工具、审核、记忆、谈判与人工审批
  domain/          经营协议、采购分配、试算与确定性结算
  execution/       持久化任务、租约、重试与 worker 调度
  infrastructure/ SQLite、配置、事件与文件属性处理
  evaluation/      指标、策略筛选与独立验证
  cli/             基线与显式付费模型验收
frontend/src/
  features/        全景赛场、决策、账本与实验功能
  pages/           页面入口
  components/      共用组件
tests/             后端回归与协议测试
```

模型只能提出经营方案；资金、库存与账本由确定性引擎在事务中更新。检查点、任务租约、回合校验和唯一约束用于恢复与防止重复结算。金额持久化为整数分。

## 配置与开发

可复制 `.env.example` 为 `.env`；模型也可通过设置页配置。`.env` 仅用于初始化数据库中的模型配置，之后以设置页保存的值为准。

| 变量                               | 默认值                                               |
| ---------------------------------- | ---------------------------------------------------- |
| `ARENA_HOST`                     | `127.0.0.1`                                        |
| `ARENA_PORT`                     | `8010`                                             |
| `ARENA_DATA_DIR`                 | 本项目 `data/`                                     |
| `REDIS_URL`                      | 留空，使用 SQLite 任务队列                           |
| `ARENA_EXECUTION`                | `embedded`，内置 worker；`external`，独立 worker |
| `MODEL_BASE_URL`                 | `https://api.openai.com/v1`                        |
| `MODEL_NAME` / `MODEL_API_KEY` | 留空                                                 |

后端 `.venv/Scripts/python -m arena.main`，前端 `npm run dev --prefix frontend`（5178，API 代理到 8010）。Linux Python 路径改为 `.venv/bin/python`。前端构建后由后端统一提供，不需要额外 Web 服务。API 文档位于 `/api/docs`。

可选 Redis 部署：

```bash
docker compose up --build -d
```

Compose 包含 Redis AOF 与独立 SQLite 挂载目录。也可设置 `REDIS_URL=redis://127.0.0.1:6385/0` 连接本地 Redis。默认每个 worker 同时运行两场比赛，支持共享本地 SQLite 的同机多进程领取与接管。独立 worker 模式下，先设置 `ARENA_EXECUTION=external` 启动 API，再在另一终端运行 `.venv/Scripts/python -m arena.worker`；两者需使用相同的 `ARENA_DATA_DIR` 和 Redis 配置。

## 验证

```powershell
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m pip check
npm run build --prefix frontend
npm run test:browser --prefix frontend
```

浏览器验收在独立临时数据库启动完整服务，默认使用 Windows Edge。其他平台先安装 Playwright Chromium，并设置 `BROWSER_PATH` 为实际浏览器可执行路径。截图和报告写入被 Git 忽略的 `test-results/`。

真实付费模型验收为显式执行：

```powershell
.venv/Scripts/python -m arena.cli.live_test --workspace-key --model deepseek-flash --workflow adaptive --negotiation --memory episodic --steps 2
.venv/Scripts/python -m arena.cli.live_test --base-url https://api.deepseek.com --model deepseek-chat
.venv/Scripts/python -m arena.cli.live_test --models deepseek-flash,deepseek-v4-pro
.venv/Scripts/python -m arena.cli.live_test --models deepseek-flash,deepseek-v4-pro --workflow reviewed --thinking enabled --steps 1
```

交互式输入 Key，不回显；也可从 `LIVE_MODEL_API_KEY` 读取，或使用 `--workspace-key` 读取已保存的默认连接凭据。临时数据库结束时清理，报告不含 Key。一个模型会增加规则对手，多个模型分别对应商店。`--steps 1` 仅运行一轮。常规测试不调用付费模型。

快速、免费地复现规则基线：

```bash
.venv/bin/python -m arena.cli.benchmark
```

显式 Flash 小额真实验证（Key 文件已加入忽略规则）：

```bash
.venv/bin/python -m arena.cli.live_test --key-file key.txt --model deepseek-flash --workflow adaptive --memory episodic --steps 2 --max-tokens 2048 --tool-budget 3
```

工具预算限制经营工具执行，模型调用还受各连接的输出上限与执行步数控制；启用谈判会增加独立买卖双方调用。以上命令不启用谈判。

## 数据与运行边界

Windows 启动时会检查本项目两个 SQLite 数据库及其 WAL/SHM 文件，自动解除这些运行文件的“只读”属性，不修改目录 ACL、其他文件或 Linux 文件权限。如果出现 `attempt to write a readonly database`，应同时检查数据库与旁边日志文件的属性、数据目录的写入权限。复制或还原数据库时必须成组处理主文件与对应日志，避免混用不同时点的文件。

`data/arena.sqlite` 保存业务、模型连接、任务及 Outbox，`data/checkpoints.sqlite` 保存 Agent 状态。升级自动添加新表和字段，保留旧比赛、密钥和回放。设置接口不返回 Key，但本地数据库保存原始凭据，需要限制目录访问。备份应先停止 API 和 worker，再复制完整 `data/`，包括可能存在的 WAL / SHM 文件。数据库与 `.env` 均不提交。

当前交付为本地单工作区产品，无账号、支付和租户隔离。默认仅监听回环地址；公开部署前需接入登录、权限、TLS 和服务端凭据管理。经营结果是沙盘模拟数据。
