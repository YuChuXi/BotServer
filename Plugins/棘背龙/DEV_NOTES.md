# 棘背龙插件开发笔记

## 模块结构

| 文件 | 职责 |
|---|---|
| `__init__.py` | 插件入口：模板表、matcher 注册、处理器、权限开关、经协议端取消息图片 |
| `comfy.py` | ComfyUI 传输层：上传参考图、提交工作流、WebSocket 等待完成、取回输出图 |
| `qwen.py` | Qwen 生图编辑：触发词与尾行解析、尺寸计算、工作流构建与执行 |
| `avatar.py` | 旧头像工作流：下载 QQ 头像、按模板打补丁并生成图片 |
| `workflows/` | ComfyUI 导出的模板（API 格式），节点 id 无关紧要，靠 class_type 与节点标题定位 |

## 功能开关

功能一律由群配置开关控制，不使用注释禁用：

| 群配置字段 | 功能 | 触发 |
|---|---|---|
| `enable_image_gen` | Qwen 生图编辑 | @机器人 + ☝️{🤓\|😋}，见下 |
| `enable_avatar_gen` | 旧头像工作流 | 关键词，见 `AVATAR_WORKFLOW_TEMPLATES` |

开关在 matcher 的 rule 中判定（不是处理器内部 return），未启用的会话不会被该 matcher 拦截消息。主机管理员不受开关限制，私聊仅限主机管理员。

## Qwen 工作流契约（代码 ↔ 模板）

| 约定 | 说明 |
|---|---|
| `PrimitiveStringMultiline` 标题“提示词” | 用户提示词填入 `inputs.value` |
| `PrimitiveInt` 标题“宽度”/“高度” | 输出尺寸（由比例与基准档计算，32 步进） |
| `SeedNode` | 每次随机 seed |
| `TextEncodeQwenImage21` | 锚点之一；`resolution` 填档位值；参考图接 `images.image_1..N` |
| `OllamaImages` | 重写版锚点；参考图接 `images.image0..N-1`；无输入时整个节点及其引用删除 |
| `OllamaChat`（重写版） | 输出 JSON（`rewritten_prompt`/`wh_ratio`/`ratio_follow`），模板内 `JsonExtractString` 提取提示词填入 TextEncode；其比例字段不影响代码注入的宽高 |
| `LoadImage` 标题以“输入图”开头 | **占位节点**，代码删除后按本条消息图片数重建（每张图配一个 `JoinImageWithAlpha`：LoadImage 槽 0 IMAGE + 槽 1 MASK 合并为 RGBA 接入锚点，alpha 对编码器与 LLM 可见） |
| 其他 `LoadImage` | 模板作者自备的底图，代码一律不动 |

### 占位删除的传播规则

占位节点可能经中转节点（如 `JoinImageWithAlpha` 把 LoadImage 的 MASK 输出合并回 RGBA）间接接入锚点。清理时从占位集合向下游传播：**全部输入**均来自待删集合的非锚点节点一并删除；锚点只删指向待删集合的接线键。模板可随意增删占位与中转层，代码自适应。新建节点接在各锚点序列的下一个编号，底图已有接线保持原位。

### 模板切换与解析

触发 emoji 决定模板：`🤓` = `workflow_qwenimage21.json`（本地 LLM 重写提示词），`😋` = `workflow_qwenimage21dr.json`（直出，无 Ollama 节点，相关逻辑自动跳过）。

触发格式：`@bot ☝️{🤓|😋}提示词\n[宽:高][高清|超清]`。被回复消息的图片排最前，其后是本条消息的图片，合计取前 10 张。比例与档位是两个独立参数，可单独或组合出现在末行；比例由正则整行识别，档位按 `RESOLUTION_LEVELS` 的词元从行尾剥除，新增档位只需扩该字典。

## 其他约定

- **OneBot 客户端（NapCat）与本服务不在同一台机器**：任何发给 QQ 的图片必须自包含（`base64://` 或 URL），禁止 `file://` 本机路径。
- **消息图片的获取走协议端**：`bot.get_image(file=消息段 file 或 url)` 取 `base64`（NapCat 文档：[获取图片](https://napcat.apifox.cn/226657066e0)），下载由 NapCat 完成。bot 不自行 httpx 访问 QQ 图片 CDN——`gchat.qpic.cn` 校验 Referer（缺失返回 400）且 rkey 时效短。协议端未回 `base64` 时显式报错，不做兜底。
- **chatrecorder 0.7.0（上游最新）的库行为**：`on_called_api` 记录 `message_sent` 时会把发送 Message 里的 `base64://` 图片段**就地改写**为 `file:///~/.cache/nonebot2/nonebot_plugin_chatrecorder/images/<md5>.cache`（为省内存）。因此**任何被复用发送的 Message 对象**第二次都会把本机路径发给远程 NapCat → Node 侧 ENOENT。规避：缓存物用不可变的 base64 字符串，Message 每次发送现构造（Tarot.py 已按此实现）；收到的 `event.message` 同样会被改写，禁止把收到的消息段原样再发送。
- `comfy.execute_prompt`：先连 WebSocket 再提交队列（事件不丢失），`asyncio.timeout` 总超时，中断与超时以异常传播。
- 分辨率：`qwen.calc_resolution` 总像素 ≈ 档位²，`RESOLUTION_LEVELS = {"": 1024, "高清": 1536, "超清": 2048}`。
