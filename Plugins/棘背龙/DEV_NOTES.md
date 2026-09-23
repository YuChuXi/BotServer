# 棘背龙插件开发笔记

## Qwen 工作流契约（代码 ↔ 模板）

代码 `build_qwen_workflow` 按以下约定接管模板，节点 id 无关紧要，靠 class_type 与 `_meta.title` 定位：

| 约定 | 说明 |
|---|---|
| `PrimitiveStringMultiline` 标题"提示词" | 用户提示词填入 `inputs.value` |
| `PrimitiveInt` 标题"宽度"/"高度" | 输出尺寸（由比例与基准档计算，32 步进） |
| `SeedNode` | 每次随机 seed |
| `TextEncodeQwenImage21` | 锚点之一；`resolution` 填档位值；参考图接 `images.image_1..N` |
| `OllamaImages` | 重写版锚点；参考图接 `images.image0..N-1`；无输入时整个节点删除 |
| `LoadImage` 标题以"输入图"开头 | **占位节点**，代码删除后按本条消息图片数重建 |
| 其他 `LoadImage`（如"参考底图"） | 模板作者的自有素材，代码一律不动 |

### 占位删除的传播规则

占位节点可能经中转节点（如 `JoinImageWithAlpha` 把 LoadImage 的 MASK 输出合并回 RGBA）间接接入锚点。清理时从占位集合出发向下游传播：**全部输入**均来自待删集合的非锚点节点一并删除；锚点（TextEncode/OllamaImages）只删指向待删集合的接线键。因此模板可以随意增删占位与中转层，代码自适应。

### alpha 管线

QQ 下载的 PNG 原样上传（无转码），LoadImage 输出 IMAGE+MASK，模板内用 `JoinImageWithAlpha` 合并后送入 TextEncode，透明信息对模型可见（系统提示词约定"transparent background"写法）。代码不做任何白底合成。

### 模板切换

触发 emoji 决定模板：`🤓` = `workflow_qwenimage21.json`（Ollama gemma-26B 重写提示词），`😋` = `workflow_qwenimage21dr.json`（直出，无 Ollama 节点，代码对 OllamaImages 全部逻辑自动跳过）。

## 其他约定

- **OneBot 客户端（NapCat）与本服务不在同一台机器**：任何发给 QQ 的图片必须自包含（base64:// 或 URL），禁止 `file://` 本机路径。
- **chatrecorder 0.7.0（上游最新）的库行为**：`on_called_api` 记录 `message_sent` 时会把发送 Message 里的 `base64://` 图片段**就地改写**为 `file:///~/.cache/nonebot2/nonebot_plugin_chatrecorder/images/<md5>.cache`（为省内存）。因此**任何被复用发送的 Message 对象**第二次都会把本机路径发给远程 NapCat → Node 侧 ENOENT（日志形如 `[error] 墨子不是猫（不许逗） | 发生错误 Error: ENOENT ...cache`）。规避：缓存物用不可变的 base64 字符串，Message 每次发送现构造（Tarot.py 已按此实现）；收到的 event.message 同样会被改写，禁止把收到的消息段原样再发送。
- `execute_prompt_ws`：先连 WebSocket 再提交队列（事件不丢失），`asyncio.timeout` 总超时，连接中断/超时以异常传播，无重连
- 触发格式：`@bot ☝️{🤓|😋}提示词\n[宽:高[高清|超清]]` + 图片（被回复消息的图片排最前，合计前 10 张）
- 分辨率：`calc_resolution` 总像素 ≈ 档位²，`RESOLUTION_LEVELS = {"": 1024, "高清": 1536, "超清": 2048}`
- 权限：群配置 `enable_image_gen` / 主机管理员
