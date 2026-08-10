# AI Director · 个人 AI 导演生产系统

> 小说 → 剧本 → 分镜提示词 → 资产图 → 打包导出 → 豆包生成视频

## 技术栈

- **后端**: Python 3.10+（已在 3.13 验证）/ Flask / SQLAlchemy (SQLite)
- **前端**: 原生 JS 单页应用 (无框架，**无需 Node / 无构建步骤**)
- **大模型**: OpenAI 兼容 API 直连，支持 6 个服务商
- **依赖管理**: 纯 pip，`requirements.txt` 即完整依赖清单

> 说明：本项目前端为零构建的原生 JS，运行只需 Python，无需 Node.js。
> 若你从其他脚手架迁移而来保留了 `package.json`，本仓库前端并不依赖它。

## 运行环境要求

| 依赖 | 版本要求 | 用途 |
|------|----------|------|
| Python | ≥ 3.10（推荐 3.10 ~ 3.13） | 运行 Flask 后端 |
| pip | 随 Python 自带 | 安装依赖 |
| 大模型 API Key | 火山引擎 / DeepSeek / OpenAI 等 | 真实生成（可选，离线模式可免） |
| Node.js | **非必须** | 前端无需构建；仅在你自行接入构建工具时需要 |

## 快速开始

### 方式一 · 一键启动（推荐，零配置）

下载项目后，直接运行对应脚本即可。**无需填写任何 API Key 也能跑通全功能**（默认离线 Mock 模式）：

```bash
# Linux / macOS
./start.sh

# Windows（双击，或在 CMD / PowerShell 中运行）
start.bat
```

脚本会自动完成：检查 Python → 创建并激活虚拟环境 `.venv` → 安装依赖 → 以离线模式启动。
启动后浏览器打开 **http://127.0.0.1:5000** 即可使用。

> 离线模式下所有大模型调用返回 Mock 数据，用于零成本验证全流程；要真正出图 / 成片，按「方式二」配置 Key 并关闭离线即可。
> 首次使用字幕 / 语音功能时，`faster-whisper` 会自动下载语音识别模型（约数百 MB），请保持联网。

### 方式二 · 接入真实大模型（可选）

```bash
cp .env.example .env
# 编辑 .env：填入 VOLC_API_KEY（火山引擎方舟）等，并把 AI_DIRECTOR_OFFLINE 改为 0
python app.py
```

### 方式三 · 手动启动（进阶）

```bash
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py                 # 默认离线，无需 Key
```

### 离线 / 在线切换

| 模式 | 环境变量 | 说明 |
|------|----------|------|
| 离线（默认） | `AI_DIRECTOR_OFFLINE=1` | Mock 数据，免 Key，跑通全链路 |
| 在线 | `AI_DIRECTOR_OFFLINE=0` + 已配置 Key | 调用真实火山引擎等出图 / 成片 |

## 目录结构

```
AI_Director/
├── app.py                          # Web 入口
├── requirements.txt                # 依赖清单
├── README.md                       # 本文件
├── 01_Global_Assets/               # 全局通用资产库
│   ├── Camera/                     # 镜头库（全景/中景/近景/特写）
│   ├── Lighting/                   # 灯光库
│   ├── Emotion/                    # 情绪库
│   ├── Action/                     # 动作库
│   ├── Transition/                 # 转场库
│   ├── Style/                      # 风格库
│   ├── Template/                   # 模板库
│   └── negative_prompts.yaml       # 全局负面提示词
├── 02_Projects/                    # 项目分层存储
│   └── {项目名}/
│       ├── 04_Story/               # 小说原文
│       ├── 05_Script/              # 结构化剧本 JSON
│       ├── 06_Storyboard/          # 分镜
│       ├── 07_Prompt/              # 视觉提示词
│       ├── 08_Image/               # 资产图（可外部导入）
│       └── 09_Video/               # 成片视频
├── 03_AI_Workflow/                 # 工作流文档
├── 04_Output/                      # 全局输出 + SQLite 数据库
├── core/                           # 通用工具模块
│   ├── yaml_reader.py
│   ├── global_asset_loader.py
│   └── negative_prompt.py
└── web/                            # Flask 分层架构
    ├── services/                   # 业务逻辑层
    │   ├── llm_client.py           # 通用 LLM 客户端
    │   ├── pipeline_service.py     # 四阶段流水线
    │   ├── script_generator.py     # 小说→剧本
    │   ├── prompt_generator.py     # 剧本→提示词
    │   ├── task_manager.py         # 异步任务管理
    │   ├── project_service.py      # 项目路径管理
    │   ├── storyboard_assets.py   # 素材图例（图N↔0N.jpg）
    │   └── novel_ai_service.py     # 小说创作 AI 服务
    ├── routes/                     # API 蓝图（全部前缀 /api）
    │   ├── projects.py             # 项目 CRUD
    │   ├── chapters.py             # 章节管理
    │   ├── pipeline.py             # 流水线触发
    │   ├── tasks.py                # 任务查询/清理
    │   ├── providers.py            # LLM 服务商配置
    │   ├── project_config.py       # 项目配置（全局+各阶段）
    │   ├── global_assets.py        # 全局资产
    │   ├── asset_versions.py       # 资产版本管理
    │   ├── asset_packages.py       # 素材打包导出
    │   ├── novel_world.py          # 世界观设定
    │   ├── novel_characters.py     # 角色管理
    │   ├── novel_outline.py        # 大纲+关键节点
    │   ├── novel_chapters.py       # 小说章节+场景
    │   ├── import_files.py         # 小说/图片导入 + 打包文件夹导入
    │   ├── inkos_import.py         # inkos 书籍回写导入
    │   └── novel_chat.py           # AI 自由对话
    ├── models/
    │   ├── database.py             # 核心数据表
    │   ├── novel_models.py         # 小说创作数据表
    │   └── asset_models.py         # 资产版本+打包数据表
    └── templates/
        └── index.html              # 前端单页应用
```

## 四阶段生产流程

### 第一阶段 · 小说创作
1. **世界观设定** — 构建世界类型、地理、力量体系、社会结构
2. **人物设计** — 创建角色外貌、性格、背景、能力、关系
3. **剧情大纲** — 规划主题、Logline、梗概、矛盾、结局
4. **关键节点** — 拆解开场/转折/高潮/结局等关键事件
5. **章节创作** — 撰写小说正文，支持 AI 生成概要和正文

### 第二阶段 · 剧本+分镜
6. **剧本生成** — 调用 LLM 小说自动转为结构化 JSON 剧本
7. **分镜提示词** — 剧本转为电影级视觉 Prompt

### 第三阶段 · 资产管理
8. **资产提示词** — 从角色/场景设定提取视觉提示词
9. **资产图管理** — 导入或 AI 生成资产参考图

### 第四阶段 · 打包导出
10. **打包导出** — 分镜提示词 + 最终版资产图 → 丢给豆包生成视频

## 大模型配置

### 三层配置体系

```
🔑 服务商 API Key（全局共享）
   支持：OpenAI / DeepSeek / 智谱GLM / 通义千问 / 火山引擎 / 自定义

🌐 全局默认模型
   所有环节的兜底配置

🎛 各环节独立配置（12个环节，可选）
   世界观/人物/大纲/节点/章节/场景/润色/对话/剧本/提示词/图片/视频
   每个可单独选择模型 + 编写自定义 System Prompt
```

### 支持的服务商

| 服务商 | 环境变量 | 默认模型 |
|--------|----------|----------|
| OpenAI | OPENAI_API_KEY | gpt-4o-mini |
| DeepSeek | DEEPSEEK_API_KEY | deepseek-chat |
| 智谱 GLM | GLM_API_KEY | glm-4-flash |
| 通义千问 | QWEN_API_KEY | qwen-max |
| 火山引擎 | VOLC_API_KEY | glm-5-2-260617 |
| 自定义 | - | 用户自定义 |

### 通过 .env 自动注入（推荐）

复制 `.env.example` 为 `.env`，填入真实值后启动时**自动**注入，无需在前端手动填写：

```ini
AI_DIRECTOR_OFFLINE=0                       # 0=真实模型, 1=Mock
VOLC_API_KEY=ark-xxxxxxxx                   # 火山引擎方舟 Key
VOLC_TEXT_MODELS=glm-5-2-260617,doubao-seed-2-1-turbo-260628   # 文本模型，逗号分隔
VOLC_IMAGE_MODELS=doubao-seedream-5-0-pro-260628,doubao-seedream-5-0-260128  # 图片模型，额度有限
VOLC_DEFAULT=1                              # 1=将火山引擎设为默认服务商
```

`create_app` 启动时会读取 `.env`，把 `VOLC_API_KEY` 写进 `volcengine` 服务商、按 `VOLC_TEXT_MODELS` 刷新模型清单，并在 `VOLC_DEFAULT=1` 时把火山引擎设为全局默认服务商。图片模型仅记录备用（当前 `draw_images` 为占位、未真正调用生图接口，避免浪费额度）。

配置方式：`.env` 自动注入 **或** 前端「🤖 大模型配置」页面填写 API Key（二选一，前端填写会写入数据库并覆盖）。

## 版本管理

- 每次保存自动创建版本（v1, v2, v3...）
- 版本选择器下拉查看所有版本
- 点击「确认最终版」锁定
- 只有最终版才会被打包导出
- 支持的资产类型：世界观、角色、大纲、章节、全局资产

## 素材打包

### 文件命名规范
```
{类型}_{名称}_{关键词1}_{关键词2}_{版本}.扩展名

示例:
角色_陈默_寸头_深邃_final.png
场景_停车场_深夜_v2.jpg
```

### 打包流程
1. 系统自动从分镜提示词中提取所需素材关键词
2. 匹配资产库中已有的最终确认版素材
3. 一键导出到规范命名的文件夹
4. 导出后直接丢给豆包生成视频

### 素材导入方式
- 资产图：直接放入 `02_Projects/{项目名}/08_Image/` 目录
- 小说原文：放入 `02_Projects/{项目名}/04_Story/` 目录
- 全局资产：放入 `01_Global_Assets/{分类}/` 目录
- 打包文件夹：`POST /api/import/:id/import-package`，传入已导出的打包文件夹路径，自动把 `prompts/` 落到目标项目 `07_Prompt/`、图片/视频落到 `08_Image/` 或 `09_Video/`，同名幂等跳过（详见下方「打包文件夹重新导入」）

### 素材参考图例（图N ↔ 0N.jpg）

为了让打包产物能直接丢进豆包等外部生图工具，系统使用统一的「素材图例」：

- **提示词首段声明**：`gen_prompts` 生成分镜提示词时，会自动在每条 `video_prompt` 开头注入素材参考声明，仅标注该镜用到的素材：
  ```
  【素材参考】图1=林深(角色图)、图2=地铁站台(场景图)…
  ```
- **打包按图例顺序重命名**：`export_package` 按分镜出现顺序（角色优先，其次场景，逐镜推进）生成全局图例，把导出素材文件重命名为 `01.jpg / 02.jpg …`。
- **严格一一对应**：提示词里的「图1」就是打包文件夹里的「01.jpg」，两者共用同一图例函数，方便你直接按图号把对应素材和提示词喂给豆包。

> 打包产物**不做自动关联**（分镜画布不按文件名绑定静帧预览），纯按图例顺序命名，便于在 AI Director 之外直接使用。

### 打包文件夹重新导入（import-package）

导出后的打包文件夹可作为自包含单元二次复用或换机迁移：

- `POST /api/import/:id/import-package` — 传入已导出的打包文件夹路径，自动把 `prompts/` 落到目标项目 `07_Prompt/`、图片/视频落到 `08_Image/` 或 `09_Video/`，同名幂等跳过。导入后提示词首段的【素材参考】声明保留，可再次打包导出。

## API 端点一览

### 项目管理
- `GET /api/projects` — 列出项目
- `POST /api/projects` — 创建项目
- `DELETE /api/projects/:id` — 删除项目

### 小说创作
- `GET/POST /api/novel/:pid/world` — 世界观
- `GET/POST /api/novel/:pid/characters` — 角色
- `GET/POST /api/novel/:pid/outline` — 大纲
- `GET/POST /api/novel/:pid/plot-points` — 关键节点
- `GET/POST /api/novel/:pid/novel-chapters` — 章节
- `GET/POST /api/novel/novel-chapters/:id/scenes` — 场景
- `POST /api/novel/:pid/chat` — AI 自由对话

### 流水线
- `POST /api/pipeline/run` — 提交任务
- `GET /api/tasks` — 查看任务
- `POST /api/tasks/clean` — 清理已完成任务

### 资产管理
- `GET /api/global-assets` — 全局资产
- `GET/POST /api/asset-versions/...` — 版本管理
- `GET/POST /api/asset-packages/...` — 素材打包

### 配置
- `GET/PUT /api/providers/:key` — 服务商配置
- `GET/PUT /api/projects/:id/config` — 项目全局配置
- `GET/PUT /api/projects/:id/config/stage/:key` — 各阶段独立配置
- `GET /api/stages` — 列出所有可配置阶段

## 数据库

SQLite 文件：`04_Output/ai_video_data.db`（自动创建）

### 核心表

| 表名 | 说明 |
|------|------|
| projects | 项目 |
| chapters | 章节（旧版，兼容） |
| scripts | 剧本（关联 chapters 或 novel_chapters） |
| tasks | 异步任务 |
| providers | LLM 服务商 |
| project_configs | 项目配置（全局+各阶段） |
| world_settings | 世界观设定 |
| novel_characters | 小说角色 |
| plot_outlines | 剧情大纲 |
| plot_points | 关键节点 |
| novel_chapters | 小说章节 |
| novel_scenes | 场景 |
| asset_versions | 资产版本 |
| asset_packages | 素材打包 |

## 换机迁移 / 新机器安装

### 关键：GitHub 上有什么、没有什么
- **GitHub 上（已被 git 跟踪）**：全部代码、`01_Global_Assets/`（YAML 资产库）、部分 demo 子集（`02_Projects/末日女子生存指南` 的 script/prompt）、`requirements.txt`、`.env.example`、`README.md`。
- **GitHub 上没有（被 `.gitignore` 屏蔽，必须手动拷）**：
  - `.env` — 真实 API Key
  - `04_Output/ai_video_data.db` — 主数据库，所有项目 / 角色 / 剧本 / 提示词元数据都在这里
  - 你自己的 `02_Projects/*`（除 demo 子集）、`04_Output/package_*`

> 所以「另一台同步过 GitHub」只代表代码在云端，**数据不在云端**——换机迁移务必单独处理 `.env` 和数据库。

### 方式一：只要代码（全新开始）
```bash
git clone https://github.com/woanderingboy/AI_Director.git
cd AI_Director
cp .env.example .env      # 或拷旧机的 .env（含真实 Key）
pip install -r requirements.txt
python app.py             # 首次启动自动建空数据库
```
离线可用（不填 Key）：`AI_DIRECTOR_OFFLINE=1 python app.py`。

### 方式二：连带现有项目数据一起搬（推荐）
直接拷贝整个项目文件夹（**除 `.git` 和 venv**）到新机，再补两样 gitignore 的关键物：
- `.env` — 真实 Key，必拷
- `04_Output/ai_video_data.db` — 主数据库，不拷就看不到旧项目
- 如需保留已生成图 / 视频，连 `02_Projects/`、`04_Output/` 一起拷

### 另一台已是 clone 的：直接 git pull
```bash
cd AI_Director
git pull origin master     # 自动拿到最新代码，不动那台的 .env 和 db
```
前提：那台没有未提交的本地改动（有则先 `git stash` 或提交）。

## 开发规范

1. **禁止大规模重构** — 小步增量迭代
2. **先跑通再优化** — 优先保证链路可用
3. **全中文体系** — Prompt、配置、注释使用中文
4. **模块独立** — 各阶段独立，只有用户主动推进才进入下一阶段

## 给接手 AI 的一句话

这是一个**个人 AI 导演生产系统**，核心流程是：小说→剧本→分镜提示词→资产图→打包→视频生成。代码只是工具，重点是系统架构、资产管理和自动化流程。用户的目标是利用 Python + 大模型搭建个人影视生产系统。
