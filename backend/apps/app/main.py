"""
剑明夸夸机器人 (Jianming Praise Bot)

一个充满正能量的夸夸机器人，专门为用户提供温暖、真诚的夸奖和鼓励。
"""

from fastapi import APIRouter
from backend.core.llm_service import chat_completion

router = APIRouter(prefix="/api/apps/app", tags=["剑明夸夸机器人"])


SYSTEM_PROMPT = """你是"剑明夸夸机器人"，一个超级温暖、充满正能量的夸夸大师！🌟

你的使命是：
1. 发现每个人身上独特的闪光点和优点
2. 用真诚、温暖、有趣的方式表达赞美
3. 给用户带来快乐和自信

夸夸原则：
- 真诚：赞美要具体、真实，不要空洞
- 温暖：语气亲切友善，像最好的朋友一样
- 创意：用生动有趣的比喻和表达方式
- 鼓励：不仅夸现在，还要鼓励未来

夸夸风格：
- 热情洋溢，充满活力
- 可以适当使用emoji增加趣味性
- 根据用户的分享内容，找到最独特的角度进行夸奖
- 回复长度适中（50-150字），精炼而有力

记住：你是世界上最会发现别人优点的机器人！"""


async def handle_chat(messages: list[dict], *, config: dict | None = None) -> dict:
    """
    处理用户消息，返回温暖的夸奖和鼓励。
    
    Args:
        messages: 聊天消息列表
        config: 可选配置
        
    Returns:
        包含夸奖内容的字典
    """
    user_msg = messages[-1] if messages else {}
    user_text = user_msg.get("content", "")
    
    print(f"[夸夸机器人] 收到消息: {user_text[:50]}...")
    
    try:
        # 构建系统消息 + 用户消息
        chat_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *messages
        ]
        
        # 调用LLM生成夸奖内容
        praise_response = await chat_completion(chat_messages)
        
        print(f"[夸夸机器人] 生成夸奖成功，长度: {len(praise_response)}")
        
        return {
            "content": praise_response,
            "type": "praise",
            "success": True
        }
        
    except Exception as e:
        print(f"[夸夸机器人] 错误: {type(e).__name__}: {e}")
        # 出错时返回一个友好的默认夸奖
        return {
            "content": "哇！你真的好棒！✨ 光是愿意和我聊天这一点，就说明你是个超级友善、乐于尝试新事物的人呢！给你一个大大的赞！👍",
            "type": "praise",
            "success": False,
            "error": str(e)
        }