# PPT Generator 子应用

一个基于 FastAPI 和 python-pptx 的智能 PPT 生成工具，支持从文本或文档自动生成专业演示文稿。

## 功能特性

- ✅ **智能内容生成**: 基于 LLM 自动生成结构化的 PPT 内容
- ✅ **专业样式设计**: 支持多种风格（专业、创意、极简、学术）
- ✅ **文档解析**: 支持上传 PDF/Word/TXT 文档并提取内容
- ✅ **多语言支持**: 支持中文、英文等多种语言
- ✅ **实时更新**: 支持根据用户反馈修改 PPT 内容
- ✅ **一键下载**: 生成后可直接下载 .pptx 文件

## 技术栈

- **FastAPI**: Web 框架
- **python-pptx**: PPT 生成库
- **LLM**: 内容生成引擎
- **Pydantic**: 数据验证

## API 端点

### 1. 生成 PPT
```http
POST /api/apps/ppt_generator/generate
Content-Type: application/json

{
  "topic": "人工智能概述",
  "style": "professional",  // 可选：professional, creative, minimal, academic
  "language": "zh",         // 可选：zh, en (默认：zh)
  "slides_count": 8         // 可选：期望的页数
}
```

**响应**:
```json
{
  "session_id": "abc123...",
  "slide_count": 8,
  "download_url": "/api/apps/ppt_generator/download/abc123...",
  "content": "已为您生成关于'人工智能概述'的 PPT，共 8 页..."
}
```

### 2. 更新 PPT
```http
POST /api/apps/ppt_generator/update
Content-Type: application/json

{
  "session_id": "abc123...",
  "instruction": "添加一页关于 AI 伦理的内容"
}
```

### 3. 下载 PPT
```http
GET /api/apps/ppt_generator/download/{session_id}
```

返回 .pptx 文件流。

### 4. 删除 PPT
```http
DELETE /api/apps/ppt_generator/delete/{session_id}
```

## 使用示例

### 通过 handle_chat 接口

```python
from backend.apps.ppt_generator.main import handle_chat

# 简单生成
messages = [{"role": "user", "content": "生成一个关于'机器学习'的 PPT"}]
result = await handle_chat(messages)

# 带参数生成
config = {"style": "professional", "language": "en"}
result = await handle_chat(messages, config=config)
```

### 通过 API

```bash
# 生成 PPT
curl -X POST http://localhost:8000/api/apps/ppt_generator/generate \
  -H "Content-Type: application/json" \
  -d '{"topic": "人工智能概述", "style": "professional"}'

# 下载 PPT
curl http://localhost:8000/api/apps/ppt_generator/download/abc123... \
  -o presentation.pptx
```

## 文件结构

```
ppt_generator/
├── __init__.py          # 空文件，标识包
├── main.py              # FastAPI 路由和 handle_chat 入口
├── service.py           # 核心业务逻辑（PPT 生成、样式处理）
├── models.py            # Pydantic 数据模型
├── prompts.py           # LLM 提示词模板
├── utils.py             # 工具函数（文件处理、验证）
├── config.py            # 配置常量
├── test_ppt.py          # 测试脚本
└── README.md            # 本文档
```

## 样式选项

| 样式 | 描述 | 适用场景 |
|------|------|----------|
| `professional` | 专业风格，正式、数据驱动 | 商务汇报、企业展示 |
| `creative` | 创意风格，引人入胜、故事化 | 营销推广、产品发布 |
| `minimal` | 极简风格，简洁明了 | 快速演示、电梯演讲 |
| `academic` | 学术风格，详细严谨 | 论文答辩、学术报告 |

## 配置

在 `config.py` 中可配置：

- `OUTPUT_DIR`: PPT 输出目录
- `MAX_SLIDES`: 最大页数限制
- `DEFAULT_STYLE`: 默认样式
- `COLOR_SCHEMES`: 配色方案

## 测试

```bash
# 运行测试脚本
python -m backend.apps.ppt_generator.test_ppt

# 或手动测试
cd backend/apps/ppt_generator
python test_ppt.py
```

## 注意事项

1. **文件大小**: 生成的 PPT 文件会保存在 `OUTPUT_DIR`，定期清理旧文件
2. **LLM 调用**: 内容生成依赖 LLM，确保 API 配置正确
3. **并发限制**: 同一 session_id 只能有一个活跃的生成任务
4. **文件过期**: 生成的 PPT 文件默认保留 24 小时（可在 config 中调整）

## 故障排除

### 下载失败
- 检查 `download_url` 是否为完整路径
- 确认文件存在于 `OUTPUT_DIR`
- 查看服务器日志中的错误信息

### 内容质量差
- 尝试更换 `style` 参数
- 提供更详细的 `topic` 描述
- 检查 LLM API 是否正常工作

### 生成速度慢
- 减少期望的 `slides_count`
- 检查 LLM 响应时间
- 考虑使用缓存机制

## 开发指南

### 添加新样式
在 `config.py` 的 `COLOR_SCHEMES` 中添加新的配色方案，并在 `service.py` 的 `apply_style` 函数中处理。

### 自定义提示词
在 `prompts.py` 中修改 `PPT_GENERATION_SYSTEM` 或 `PPT_UPDATE_SYSTEM`。

### 扩展功能
- 添加模板支持
- 支持图片插入
- 支持图表生成
- 支持多语言自动检测

## 许可证

MIT License