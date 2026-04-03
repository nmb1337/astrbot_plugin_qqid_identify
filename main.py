import json
import os
from pathlib import Path
from typing import List, Dict, Any

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.api.platform import MessageType
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

@register("astrbot_plugin_qqid_identify", "YourName", "基于QQ号识别用户，避免昵称误认", "1.0.0")
class QQIDIdentifyPlugin(Star):
    """
    QQ ID 识别插件

    核心功能：机器人收到消息时，只根据QQ号（user_id）识别用户，
    永远不使用昵称（user_name）作为识别依据，避免改名认错人。

    通过修改消息发送者的昵称为QQ号，确保所有用户交互都使用稳定的user_id。
    支持所有平台，但主要针对QQ平台（aiocqhttp, qq_official）。

    数据持久化：存储用户ID到原始昵称的映射，数据保存在data/plugins/astrbot_plugin_qqid_identify/user_data.json
    包含管理员、黑名单、白名单功能。
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.user_data: Dict[str, str] = {}  # user_id: original_nickname
        self.admins: List[str] = []
        self.blacklist: List[str] = []
        self.whitelist: List[str] = []
        self.whitelist_enabled: bool = False
        self.data_file = None
        
        # 从配置中读取设置
        self.enable_permission_check: bool = config.get("enable_permission_check", True)
        self.enable_identify: bool = config.get("enable_identify", True)
        self.debug_mode: bool = config.get("debug_mode", False)

    async def initialize(self):
        """插件初始化"""
        # 获取数据目录
        data_dir = Path(get_astrbot_data_path())
        plugin_data_dir = data_dir / "plugins" / "astrbot_plugin_qqid_identify"
        plugin_data_dir.mkdir(parents=True, exist_ok=True)
        self.data_file = plugin_data_dir / "user_data.json"
        
        # 从配置读取白名单启用状态
        self.whitelist_enabled = self.config.get("whitelist_enabled", False)
        
        # 加载用户数据
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.user_data = data.get("users", {})
                self.admins = data.get("admins", [])
                self.blacklist = data.get("blacklist", [])
                self.whitelist = data.get("whitelist", [])
                logger.info(f"加载用户数据: {len(self.user_data)} 个用户, {len(self.admins)} 个管理员, {len(self.blacklist)} 个黑名单, {len(self.whitelist)} 个白名单")
            except Exception as e:
                logger.error(f"加载用户数据失败: {e}")
                self._init_default_data()
        else:
            logger.info("用户数据文件不存在，将创建新的数据文件")
            self._init_default_data()
        
        # 从配置读取默认管理员并添加到管理员列表
        default_admin = self.config.get("default_admin", "")
        if default_admin:
            admin_list = [a.strip() for a in default_admin.split(",") if a.strip()]
            for admin_id in admin_list:
                if admin_id not in self.admins:
                    self.admins.append(admin_id)
                    logger.info(f"添加默认管理员: {admin_id}")
            if admin_list:
                await self._save_user_data()
        
        # 输出初始化信息
        log_level = "DEBUG" if self.debug_mode else "INFO"
        logger.info(f"QQ ID 识别插件已加载 [权限检查: {'启用' if self.enable_permission_check else '禁用'}, "
                    f"QQ号识别: {'启用' if self.enable_identify else '禁用'}, 日志级别: {log_level}]")

    def _init_default_data(self):
        """初始化默认数据"""
        self.user_data = {}
        self.admins = []
        self.blacklist = []
        self.whitelist = []
        self.whitelist_enabled = False

    @filter.event_message_type(filter.EventMessageType.ALL, priority=1)
    async def check_permissions(self, event: AstrMessageEvent):
        """
        权限检查：基于user_id的黑名单和白名单过滤
        高优先级执行，在其他处理之前
        
        【关键】所有权限检查都基于user_id，不依赖昵称
        """
        # 如果权限检查已禁用，直接返回
        if not self.enable_permission_check:
            return
        
        # 【关键】从事件对象获取user_id
        user_id = event.get_sender_id()
        if not user_id:
            logger.warning("无法获取发送者user_id，无法进行权限检查")
            return
        
        # 【基于user_id的黑名单检查】
        if user_id in self.blacklist:
            logger.info(f"[权限拒绝] 用户 {user_id} 在黑名单中，停止处理")
            event.stop_event()
            return
        
        # 【基于user_id的白名单检查】
        if self.whitelist_enabled and user_id not in self.whitelist:
            logger.info(f"[权限拒绝] 白名单模式启用，用户 {user_id} 不在白名单中，停止处理")
            event.stop_event()
            return
        
        if self.debug_mode:
            logger.debug(f"[权限允许] user_id={user_id} 通过权限检查")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def identify_by_qq_id(self, event: AstrMessageEvent):
        """
        根据QQ号识别用户的主处理函数 (v4.22.2+)

        核心逻辑：
        1. 从event对象中提取user_id（QQ号），这是唯一稳定的身份标识
        2. 将消息发送者的所有昵称字段（nickname/card）替换为user_id
        3. 确保LLM上下文中看到的都是user_id而不是可能变化的昵称
        4. 记录原始昵称供历史追踪，但不用于身份识别
        """
        # 如果QQ号识别已禁用，直接返回
        if not self.enable_identify:
            return
        
        # 【关键】从事件对象获取发送者的user_id（QQ号）
        user_id = event.get_sender_id()
        if not user_id:
            if self.debug_mode:
                logger.debug("警告：无法获取发送者user_id")
            return
        
        # 获取原始昵称用于记录和调试（但不用于身份识别）
        original_nickname = event.get_sender_name()
        
        # 【核心】将所有基于昵称的判断改为基于user_id
        # 记录原始昵称（仅用于历史追踪，身份判断全部基于user_id）
        if user_id not in self.user_data or self.user_data[user_id] != original_nickname:
            self.user_data[user_id] = original_nickname
            await self._save_user_data()
            logger.info(f"[识别标识] user_id={user_id}, 原始昵称={original_nickname}")
        
        # 【关键】修改发送者的所有昵称字段为user_id
        # 这确保无论用户改了群昵称还是card，机器人都识别user_id
        sender = event.message_obj.sender
        
        # 修改主昵称字段
        old_nickname = sender.nickname
        sender.nickname = user_id
        
        # 如果存在card字段（群昵称），也修改为user_id
        if hasattr(sender, 'card'):
            sender.card = user_id
        
        # 【强化】在事件对象中添加标准化识别标记，供后续使用
        event.set_extra("qqid_identified", True)
        event.set_extra("qqid_user_id", user_id)
        event.set_extra("qqid_original_nickname", original_nickname)
        
        if self.debug_mode:
            logger.debug(f"[QQ号识别] user_id={user_id}, nickname改为: {old_nickname} -> {user_id}")

    # 管理员命令
    @filter.command("add_admin")
    async def add_admin(self, event: AstrMessageEvent):
        """添加管理员 (仅管理员可用)"""
        # 【关键】基于user_id检查权限
        operator_id = event.get_sender_id()
        if not self._is_admin(operator_id):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        args = event.message_str.strip().split()
        if len(args) < 2:
            yield event.plain_result("用法: /add_admin <QQ号>")
            return
        
        qq = args[1]
        if qq in self.admins:
            yield event.plain_result(f"管理员 {qq} 已存在")
            return
        
        self.admins.append(qq)
        await self._save_user_data()
        logger.info(f"[管理操作] 操作者={operator_id} 添加管理员={qq}")
        yield event.plain_result(f"✅ 已添加管理员: {qq}")

    @filter.command("remove_admin")
    async def remove_admin(self, event: AstrMessageEvent):
        """移除管理员 (仅管理员可用)"""
        if not self._is_admin(event.get_sender_id()):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        args = event.message_str.strip().split()
        if len(args) < 2:
            yield event.plain_result("用法: /remove_admin <QQ号>")
            return
        
        qq = args[1]
        if qq not in self.admins:
            yield event.plain_result(f"用户 {qq} 不是管理员")
            return
        
        self.admins.remove(qq)
        await self._save_user_data()
        yield event.plain_result(f"已移除管理员: {qq}")

    @filter.command("list_admins")
    async def list_admins(self, event: AstrMessageEvent):
        """列出所有管理员 (仅管理员可用)"""
        if not self._is_admin(event.get_sender_id()):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        if not self.admins:
            yield event.plain_result("暂无管理员")
            return
        
        admin_list = "\n".join(f"- {admin}" for admin in self.admins)
        yield event.plain_result(f"管理员列表:\n{admin_list}")

    # 黑名单命令
    @filter.command("add_blacklist")
    async def add_blacklist(self, event: AstrMessageEvent):
        """添加黑名单 (仅管理员可用)"""
        if not self._is_admin(event.get_sender_id()):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        args = event.message_str.strip().split()
        if len(args) < 2:
            yield event.plain_result("用法: /add_blacklist <QQ号>")
            return
        
        qq = args[1]
        if qq in self.blacklist:
            yield event.plain_result(f"用户 {qq} 已经在黑名单中")
            return
        
        self.blacklist.append(qq)
        await self._save_user_data()
        yield event.plain_result(f"已添加黑名单: {qq}")

    @filter.command("remove_blacklist")
    async def remove_blacklist(self, event: AstrMessageEvent):
        """移除黑名单 (仅管理员可用)"""
        if not self._is_admin(event.get_sender_id()):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        args = event.message_str.strip().split()
        if len(args) < 2:
            yield event.plain_result("用法: /remove_blacklist <QQ号>")
            return
        
        qq = args[1]
        if qq not in self.blacklist:
            yield event.plain_result(f"用户 {qq} 不在黑名单中")
            return
        
        self.blacklist.remove(qq)
        await self._save_user_data()
        yield event.plain_result(f"已移除黑名单: {qq}")

    @filter.command("list_blacklist")
    async def list_blacklist(self, event: AstrMessageEvent):
        """列出黑名单 (仅管理员可用)"""
        if not self._is_admin(event.get_sender_id()):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        if not self.blacklist:
            yield event.plain_result("黑名单为空")
            return
        
        blacklist_str = "\n".join(f"- {user}" for user in self.blacklist)
        yield event.plain_result(f"黑名单列表:\n{blacklist_str}")

    # 白名单命令
    @filter.command("add_whitelist")
    async def add_whitelist(self, event: AstrMessageEvent):
        """添加白名单 (仅管理员可用)"""
        if not self._is_admin(event.get_sender_id()):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        args = event.message_str.strip().split()
        if len(args) < 2:
            yield event.plain_result("用法: /add_whitelist <QQ号>")
            return
        
        qq = args[1]
        if qq in self.whitelist:
            yield event.plain_result(f"用户 {qq} 已经在白名单中")
            return
        
        self.whitelist.append(qq)
        await self._save_user_data()
        yield event.plain_result(f"已添加白名单: {qq}")

    @filter.command("remove_whitelist")
    async def remove_whitelist(self, event: AstrMessageEvent):
        """移除白名单 (仅管理员可用)"""
        if not self._is_admin(event.get_sender_id()):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        args = event.message_str.strip().split()
        if len(args) < 2:
            yield event.plain_result("用法: /remove_whitelist <QQ号>")
            return
        
        qq = args[1]
        if qq not in self.whitelist:
            yield event.plain_result(f"用户 {qq} 不在白名单中")
            return
        
        self.whitelist.remove(qq)
        await self._save_user_data()
        yield event.plain_result(f"已移除白名单: {qq}")

    @filter.command("list_whitelist")
    async def list_whitelist(self, event: AstrMessageEvent):
        """列出白名单 (仅管理员可用)"""
        if not self._is_admin(event.get_sender_id()):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        if not self.whitelist:
            yield event.plain_result("白名单为空")
            return
        
        whitelist_str = "\n".join(f"- {user}" for user in self.whitelist)
        yield event.plain_result(f"白名单列表:\n{whitelist_str}")

    @filter.command("enable_whitelist")
    async def enable_whitelist(self, event: AstrMessageEvent):
        """启用白名单模式 (仅管理员可用)"""
        if not self._is_admin(event.get_sender_id()):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        self.whitelist_enabled = True
        await self._save_user_data()
        yield event.plain_result("白名单模式已启用")

    @filter.command("disable_whitelist")
    async def disable_whitelist(self, event: AstrMessageEvent):
        """禁用白名单模式 (仅管理员可用)"""
        if not self._is_admin(event.get_sender_id()):
            yield event.plain_result("权限不足，只有管理员可以使用此命令")
            return
        
        self.whitelist_enabled = False
        await self._save_user_data()
        yield event.plain_result("白名单模式已禁用")

    def _is_admin(self, user_id: str) -> bool:
        """
        检查用户是否为管理员
        【关键】基于user_id而非昵称进行权限判断
        """
        if not user_id:
            return False
        is_admin = user_id in self.admins
        if self.debug_mode:
            logger.debug(f"[权限检查] user_id={user_id}, 是否管理员={is_admin}")
        return is_admin

    async def terminate(self):
        """插件卸载"""
        # 保存用户数据
        await self._save_user_data()
        logger.info("QQ ID 识别插件已卸载")

    async def _save_user_data(self):
        """保存用户数据到文件"""
        if self.data_file:
            try:
                data = {
                    "users": self.user_data,
                    "admins": self.admins,
                    "blacklist": self.blacklist,
                    "whitelist": self.whitelist,
                    "whitelist_enabled": self.whitelist_enabled
                }
                with open(self.data_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.debug(f"保存用户数据: {len(self.user_data)} 个用户, {len(self.admins)} 个管理员, {len(self.blacklist)} 个黑名单, {len(self.whitelist)} 个白名单")
            except Exception as e:
                logger.error(f"保存用户数据失败: {e}")
