# AI Director · 个人 AI 导演生产系统

> 小说 → 剧本 → 分镜提示词 → 资产图 → 打包导出 → 豆包生成视频

## 技术栈

- **后端**: Python 3.12+ / Flask / SQLAlchemy (SQLite)
- **前端**: 原生 JS 单页应用 (无框架)
- **大模型**: OpenAI 兼容 API 直连，支持 6 个服务商

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
python app.py
# 浏览器访问 http://127.0.0.1:5000

# 3. 离线模式（不调真实 LLM，用 Mock 数据）
AI_DIRECTOR_OFFLINE=1 python app.py
```

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
| 火山引擎 | VOLC_API_KEY | doubao-pro-32k |
| 自定义 | - | 用户自定义 |

配置方式：在前端「🤖 大模型配置」页面填写 API Key。

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

## 开发规范

1. **禁止大规模重构** — 小步增量迭代
2. **先跑通再优化** — 优先保证链路可用
3. **全中文体系** — Prompt、配置、注释使用中文
4. **模块独立** — 各阶段独立，只有用户主动推进才进入下一阶段

## 给接手 AI 的一句话

这是一个**个人 AI 导演生产系统**，核心流程是：小说→剧本→分镜提示词→资产图→打包→视频生成。代码只是工具，重点是系统架构、资产管理和自动化流程。用户的目标是利用 Python + 大模型搭建个人影视生产系统。
