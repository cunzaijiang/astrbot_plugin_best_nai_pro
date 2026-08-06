# 变更记录

## 0.3.5 - 2026-08-06

### 反推 LLM 改走 AstrBot provider 体系
- 新增 `retag_provider` 配置（select_provider 下拉，留空回退默认 provider）：从 AstrBot 已配置的 LLM 供应商中选一个支持视觉的（如 OpenAI gpt-4o / Gemini）
- 反推 LLM 调用改用 `context.llm_generate(image_urls=...)`，不再自己裸调 OpenAI 接口
- `core/tag_extractor.py` 重构：移除 `llm_base_url`/`llm_api_key`/`llm_model`，改接收 `llm_chat` 回调，与 LLM SDK 解耦
- 移除 `retag_llm_model` 配置（AstrBot provider 自带 model 字段，模型名随 provider 一起选，无需单独覆盖）
- Level 1（PNG 元数据）不受影响，始终可用

## 0.3.4 - 2026-08-06

### 反推功能增强
- `/反推` 命令支持「同时发图和指令」场景的取图（沿用原版四级兜底）
- 反推失败提示文案完善：分别列出元数据 / Danbooru API / LLM 视觉三级状态

### 修复
- `/nai` 指令把命令名 `nai` 当提示词传给上游：`core/parse.py` 剥离开头命令名（兼容 `!`/`#`/`/` 等任意唤醒符，`\b` 保护 nai 出现在中间的情况）

## 0.3.3 - 2026-08-06

### 提示词反推（新功能）
- 新增 `/反推` 命令：发图（或回复图）自动反推 Danbooru 风格 NAI 提示词，可直接用于 `/nai`
- 三级降级策略：
  1. 📦 PNG 元数据（tEXt/iTXt/zTXt）- 最快最准，支持 NAI / SD WebUI / 通用格式
  2. 🔍 LLM 中文描述 + Danbooru API 语义检索（需配 danbooru_api_url + 视觉模型）
  3. 🤖 LLM 视觉直接输出 tag（需配 retag_llm_model，如 gpt-4o-mini）
- 取图四级兜底：当前消息 / message_obj / 引用消息 / aiocqhttp CQ:image 原文
- 新增配置项：`danbooru_api_url` / `retag_llm_model` / `retag_show_source`
- LLM 凭据复用生图配置（base_url + image_gen_key），无需单独配

## 0.3.2 - 2026-07-30

### Studio 顶栏
- 左侧 brand 使用插件 `logo.jpg`（`pages/studio/logo.jpg` 128px 缩略图）替换色块占位

## 0.3.1 - 2026-07-30

### Studio 预览
- 修复竖图 832×1216（及任意高图）结果超出舞台框：`.stage-result img` 改为绝对定位 + `object-fit: contain`，强制缩放到绘图框内；单击 lightbox 仍按原图尺寸查看

### 局部重绘
- 非标准尺寸上传不再静默 cover 裁剪，改为弹出「适配绘图尺寸」对话框
- 支持选择目标尺寸（竖/横/方）与适配方式：裁剪填满 / 完整缩放（黑边）/ 拉伸
- 裁剪填满模式下可拖动预览调整裁剪位置

## 0.2.0 - 2026-07-30

### 结构
- 按 AstrBot 插件开发规范拆分为 `core/` + `services/` + `main.py`
- 删除单体 1800+ 行 main，职责分离：常量 / 错误 / 图片解析 / outfit / 生图 / 转译 / 代理

### Studio 面板（全新布局）
- 废弃 `pages/test-panel`（左右双栏亮色卡片）
- 新增 `pages/studio`：暗色 **舞台预览 + 右侧 Dock**
- Web API 前缀改为 `/{plugin}/studio/*`
- 顶栏生成按钮 + Ctrl/⌘+Enter，尺寸用分段控件
- Prompt Trace 折叠条、单图大预览 + lightbox

### 行为
- 核心能力保持：`/nai` `/画师` `/nsfw_*` `/imgstatus`、LLM tool、本地代理、outfit 缓存、双提示词合并
- 响应解析补充 seed 注释提取（API 文档 §13）
- 默认 steps 与 schema 对齐为 28

## 0.1.x

见原版备份目录中的 CHANGES.md（OpenAI 兼容 API 改造记录）。
