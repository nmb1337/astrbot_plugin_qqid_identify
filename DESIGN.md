# QQID识别插件 - 核心设计文档

**版本**: v1.0.0  
**兼容**: AstrBot v4.22.2+  
**语言**: Python 3.10+

## 核心问题

机器人需要根据用户的 **QQ号（user_id）** 识别用户身份，而不是基于可变的群昵称。

**场景**：
- 用户改了群昵称 → 机器人应该仍能识别出是同一个人
- 用户被设为管理员 → 改名后仍然是管理员（基于user_id）
- 用户被加入黑名单 → 改名后仍然被屏蔽（基于user_id）

## 解决方案

### 1. 获取user_id

```python
# 从事件对象获取发送者的QQ号（唯一稳定的身份标识）
user_id = event.get_sender_id()  # 返回字符串类型的QQ号

# 对比：获取可变的昵称（不用于身份判断）
nickname = event.get_sender_name()  # 可能被用户改动
```

### 2. 标准化消息发送者信息

关键步骤：将所有昵称字段替换为user_id，确保后续处理都基于稳定的身份标识

```python
# 获取发送者对象
sender = event.message_obj.sender

# 【关键】替换所有昵称字段为user_id
sender.nickname = user_id      # 主昵称字段
if hasattr(sender, 'card'):
    sender.card = user_id      # 群昵称字段（如果存在）

# 【强化】在事件中标记识别完成，供后续逻辑使用
event.set_extra("qqid_identified", True)
event.set_extra("qqid_user_id", user_id)
event.set_extra("qqid_original_nickname", original_nickname)
```

### 3. 权限检查流程（所有基于user_id）

```
消息到达
    ↓
【高优先级】check_permissions()
    - 从event.get_sender_id()获取user_id
    - 检查user_id是否在blacklist → 停止处理
    - 检查user_id是否在whitelist（如启用） → 停止处理
    ↓
【中优先级】identify_by_qq_id()
    - 修改事件中的所有昵称字段为user_id
    - 记录原始昵称用于追踪
    ↓
【后续处理】管理员命令
    - 从event.get_sender_id()获取user_id
    - 检查user_id是否在admins列表 → 决定是否允许执行
```

### 4. 数据存储（以user_id为键）

```json
{
  "users": {
    "123456789": "原始昵称1",
    "987654321": "原始昵称2"
  },
  "admins": ["123456789"],
  "blacklist": ["999999999"],
  "whitelist": ["123456789", "111111111"],
  "whitelist_enabled": false
}
```

## 关键API调用

| 方法 | 作用 | 返回值 | 稳定性 |
|------|------|-------|-------|
| `event.get_sender_id()` | 获取发送者的QQ号 | `str` (e.g. "123456789") | ✅ 高（唯一身份标识） |
| `event.get_sender_name()` | 获取发送者的昵称 | `str` | ❌ 低（用户可改动） |
| `event.message_obj.sender.nickname` | 消息发送者的昵称字段 | `str` | ⚠️ 可被修改 |
| `event.message_obj.sender.card` | 群昵称字段 | `str` | ⚠️ 可被修改 |

## 工作流程示例

### 场景：用户改名后执行管理命令

```
用户原名：小明 (QQ: 123456789)
操作：
  1. 用户改群昵称为"小张"
  2. 用户发送命令: /add_blacklist 999999999

插件处理：
  1. [识别] event.get_sender_id() → "123456789"
  2. [权限] 检查 "123456789" 是否在admins → 是（基于user_id，不受改名影响）
  3. [执行] 添加 "999999999" 到黑名单
  4. [反馈] "✅ 已添加黑名单: 999999999"

日志输出：
  [管理操作] 操作者=123456789 添加管理员=999999999
```

## 调试技巧

启用 `debug_mode: true` 后，查看日志中的以下信息：

```
[识别标识] user_id=123456789, 原始昵称=小明
[QQ号识别] user_id=123456789, nickname改为: 小明 -> 123456789
[权限检查] user_id=123456789, 是否管理员=true
[管理操作] 操作者=123456789 添加管理员=999999999
```

## 兼容性说明

### AstrBot 事件对象 (v4.22.2)

```python
class AstrMessageEvent:
    def get_sender_id(self) -> str:  # ✅ 可靠获取QQ号
        """获取消息发送者的id。"""
        sender = getattr(self.message_obj, "sender", None)
        if sender and isinstance(getattr(sender, "user_id", None), str):
            return sender.user_id
        return ""
    
    def get_sender_name(self) -> str:  # ⚠️ 可变的昵称
        """获取消息发送者的名称。(可能会返回空字符串)"""
        # ... 返回nickname或其他字段
```

## 性能考虑

- 权限检查使用列表查询（O(n)），建议列表大小 < 1000
- 用户数据JSON方式存储，足以满足大多数场景
- 对每条消息都进行权限检查，但由于优先级机制，黑名单用户会快速停止处理

## 扩展建议

如需进一步增强，可考虑：
1. 使用集合(set)替代列表存储权限数据（O(1) lookup）
2. 添加正则表达式支持黑名单（如按QQ段屏蔽）
3. 添加时间限制的临时黑名单
4. 集成数据库存储大规模权限数据
