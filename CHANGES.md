# 变更记录

## 0.3.2 — 2026-07-30

### Studio 顶栏
- 左侧 brand 使用插件 `logo.jpg`（`pages/studio/logo.jpg` 128px 缩略图）替换色块占位

## 0.3.1 — 2026-07-30

### Studio 预览
- 修复竖图 832×1216（及任意高图）结果超出舞台框：`.stage-result img` 改为绝对定位 + `object-fit: contain`，强制缩放到绘图框内；单击 lightbox 仍按原图尺寸查看

### 局部重绘
- 非标准尺寸上传不再静默 cover 裁剪，改为弹出「适配绘图尺寸」对话框
- 支持选择目标尺寸（竖/横/方）与适配方式：裁剪填满 / 完整缩放（黑边）/ 拉伸
- 裁剪填满模式下可拖动预览调整裁剪位置

## 0.2.0 — 2026-07-30

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
