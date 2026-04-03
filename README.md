# astrbot-plugin-qqid-identify

QQID识别插件 / QQID Identification Plugin

## 功能特性 qq交流群1093496287反馈bug及闲聊

### 核心功能
- **QQ号识别**: 机器人只根据QQ号（user_id）识别用户，避免昵称变化导致的误认
- **昵称修改**: 自动将用户昵称修改为QQ号，确保稳定识别

### 管理功能
- **管理员系统**: 只有指定QQ号的用户能使用管理命令
- **黑名单功能**: 按QQ号屏蔽用户，禁止其发言
- **白名单功能**: 可启用白名单模式，只允许指定QQ号使用机器人

### 管理命令
所有管理命令都需要管理员权限：

#### 管理员管理
- `/add_admin <QQ号>` - 添加管理员
- `/remove_admin <QQ号>` - 移除管理员
- `/list_admins` - 列出所有管理员

#### 黑名单管理
- `/add_blacklist <QQ号>` - 添加黑名单用户
- `/remove_blacklist <QQ号>` - 移除黑名单用户
- `/list_blacklist` - 列出黑名单用户

#### 白名单管理
- `/add_whitelist <QQ号>` - 添加白名单用户
- `/remove_whitelist <QQ号>` - 移除白名单用户
- `/list_whitelist` - 列出白名单用户
- `/enable_whitelist` - 启用白名单模式
- `/disable_whitelist` - 禁用白名单模式

## 工作原理（v1.0.0+）

### 核心识别机制

本插件采用 **严格基于user_id的识别策略**，确保不会因为用户改群昵称而导致身份混淆：

#### 1. 识别过程（优先级=高）
- 从事件对象 `event.get_sender_id()` 获取 **user_id（QQ号）**，这是唯一稳定的身份标识
- 获取原始昵称（仅用于历史记录，**不用于身份判断**）
- 将事件对象中的所有昵称字段（`nickname`、`card`等）**全部替换为user_id**
- 在事件对象中标记识别完成，供后续逻辑使用

#### 2. 权限检查（优先级=最高）
- **黑名单判断**：基于 `user_id` 检查是否在黑名单 → 高优先级拦截
- **白名单判断**：基于 `user_id` 检查是否在白名单 → 高优先级拦截
- **管理员判断**：基于 `user_id` 检查是否是管理员 → 控制指令执行权限

#### 3. LLM上下文保证
- 由于修改了 `nickname`/`card` 等字段，LLM生成的上下文中看到的是user_id而非可变的昵称
- 即使用户改了群内昵称，机器人持有的用户身份信息不会改变

### 关键特性

✅ **昵称变化隔离**：用户改名后，机器人仍能准确识别（基于user_id，不受影响）  
✅ **权限稳定性**：管理员、黑名单、白名单都基于user_id，改名不影响权限  
✅ **历史追踪**：记录原始昵称用于审计和调试，但不用于身份判断  
✅ **完整排查**：通过调试日志清楚看到识别过程和权限检查详情  

## 配置说明

插件支持通过配置文件进行配置。配置文件位置：`data/config/astrbot_plugin_qqid_identify_config.json`

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|------|------|-------|------|
| `enable_permission_check` | bool | true | 是否启用权限检查（黑名单和白名单） |
| `whitelist_enabled` | bool | false | 是否启用白名单模式 |
| `enable_identify` | bool | true | 是否启用QQ号识别 |
| `debug_mode` | bool | false | 调试模式，启用后输出更详细的日志 |
| `default_admin` | string | "" | 默认管理员QQ号，多个用逗号分隔(如: 123456,789012) |

### 配置方式

1. **WebUI配置**: 在AstrBot WebUI的插件页面找到本插件，点击配置按钮进行设置
2. **文件配置**: 编辑 `data/config/astrbot_plugin_qqid_identify_config.json` 文件
3. **命令配置**: 首次运行时可通过 `default_admin` 配置项添加初始管理员

## 数据持久化

插件会自动创建数据目录 `data/plugins/astrbot_plugin_qqid_identify/`，并在其中存储用户数据：

- `user_data.json`: 存储所有数据，包括：
  - `users`: 用户ID到原始昵称的映射
  - `admins`: 管理员QQ号列表
  - `blacklist`: 黑名单QQ号列表
  - `whitelist`: 白名单QQ号列表
  - `whitelist_enabled`: 白名单模式是否启用

- 数据在插件初始化时加载，卸载时保存
- 支持热重载，数据会实时更新

## 兼容性

- **AstrBot >= 4.22.2** ✓ (完全支持，针对此版本优化)
- **AstrBot >= 4.16.0** ✓ (支持)
- **Python 3.10+** ✓

## 快速验证

### 如何确认插件正在基于user_id识别？

1. **启用调试模式**：在配置中设置 `debug_mode: true`
2. **查看日志**：重启后，在AstrBot日志中查看如下信息：
   ```
   [识别标识] user_id=123456789, 原始昵称=小明
   [QQ号识别] user_id=123456789, nickname改为: 小明 -> 123456789
   [权限检查] user_id=123456789, 是否管理员=false
   ```

3. **测试权限变化**：
   - 用户修改群昵称后，再次在群内发言
   - 查看日志是否显示相同的user_id（证明识别成功）
   - 昵称变化不影响黑名单/白名单/管理员权限

### 常见问题排查

| 问题 | 原因 | 解决方案 |
|------|------|--------|
| 无法识别user_id | `get_sender_id()`返回为空 | 确认消息类型是否支持（QQ平台应该支持） |
| 权限检查没生效 | 权限检查未启用 | 检查配置 `enable_permission_check` 是否为true |
| 黑名单没生效 | 平台不支持或user_id格式不同 | 启用debug_mode查看实际的user_id格式 |
| 改名后还是被识别为昵称 | 其他插件修改了nickname字段 | 调整插件加载顺序，让此插件优先级最高 |

## 注意事项

- 本插件会修改消息对象的发送者信息，可能影响其他插件或功能的显示
- 对于需要显示用户昵称的场景，可能需要额外处理

> [!NOTE]
> This plugin is for [AstrBot](https://github.com/AstrBotDevs/AstrBot).
>
> [AstrBot](https://github.com/AstrBotDevs/AstrBot) is an agentic assistant for both personal and group conversations. It can be deployed across dozens of mainstream instant messaging platforms, including QQ, Telegram, Feishu, DingTalk, Slack, LINE, Discord, Matrix, etc. In addition, it provides a reliable and extensible conversational AI infrastructure for individuals, developers, and teams. Whether you need a personal AI companion, an intelligent customer support agent, an automation assistant, or an enterprise knowledge base, AstrBot enables you to quickly build AI applications directly within your existing messaging workflows.

# Supports

- [AstrBot Repo](https://github.com/AstrBotDevs/AstrBot)
- [AstrBot Plugin Development Docs (Chinese)](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot Plugin Development Docs (English)](https://docs.astrbot.app/en/dev/star/plugin-new.html)