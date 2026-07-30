# 魔法绘图 Studio (astrbot_plugin_best_nai_pro)

基于 OpenAI 兼容 API 的 NovelAI 生图插件，适用于 AstrBot v3.4+。  
模块化后端 + **Studio** 暗色调试面板（舞台预览 + 右侧参数 Dock），支持文生图与局部重绘。

## 功能

- NovelAI 4.5 全模型支持（full / curated）
- OpenAI 兼容接入：`POST /v1/chat/completions` + Bearer 鉴权
- 自然语言提示词自动转译为 NAI 标签
- 多风格预设（条漫清新、同人分镜、半立体唯美、半立体幼态、里番本格、视觉小说、自定义）
- 画师预设系统（自定义风格下可切换）
- NSFW 开关（切换 full / curated）
- 本地 Images 代理（供陪伴插件调用）
- Studio Web 调试面板
  - 文生图 / 局部重绘双模式
  - 双提示词、采样参数、Prompt Trace、面板缓存
  - 竖图等比例结果自适应舞台框
  - 非标准尺寸原图：裁剪填满 / 完整缩放 / 拉伸后再重绘

## 指令

| 指令 | 说明 |
|---|---|
| `/nai <提示词>` | 生成图片，支持 `--style=` / `--size=` |
| `/画师` | 查看 / 切换画师预设（仅自定义风格） |
| `/nsfw_on` | 开启 NSFW（full 模型） |
| `/nsfw_off` | 关闭 NSFW（curated 模型） |
| `/imgstatus` | 查看本地代理与上游连通性 |

## 配置

在 AstrBot WebUI 插件管理页配置：

| 项 | 说明 |
|---|---|
| `image_gen_key` | OpenAI 兼容 API 密钥 |
| `base_url` | API 地址（不带 `/v1`） |
| `image_style` | 默认风格 |
| `image_size` | 竖图 / 横图 / 方图 |
| `artist_presets` | 画师预设列表，格式 `名称:画师串` |
| `enable_translate` | 是否开启自然语言转译 |
| `enable_llm_tool` | 是否允许 LLM 调用生图工具 |
| `max_tokens` | 单次预算（1 Anlas = 10000 tokens） |

## 项目结构

```
astrbot_plugin_best_nai_pro/
├── main.py                 # 插件入口（指令 / 生命周期 / Studio API）
├── metadata.yaml
├── _conf_schema.json
├── logo.jpg                # 插件图标
├── core/                   # 常量、错误映射、图片解析、outfit
├── services/               # 生图 / 转译 / 本地代理
└── pages/studio/           # Studio 面板（HTML/CSS/JS + logo）
```

## 版本

- **0.3.2** — Studio 顶栏 logo；竖图预览适配；局部重绘非标尺寸裁剪/缩放对话框
- **0.3.0** — Studio 文生图 / 局部重绘双模式
- **0.2.0** — 模块化重构 + Studio 面板重设计
- **0.1.0** — OpenAI 兼容 API 改造
