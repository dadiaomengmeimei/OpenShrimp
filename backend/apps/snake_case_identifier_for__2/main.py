"""
Weather Forecast Bot - A simple weather information generator
Uses LLM to generate realistic weather forecasts based on user queries
"""

from typing import Optional
from fastapi import APIRouter
from backend.core.llm_service import chat_completion

router = APIRouter(prefix="/api/apps/snake_case_identifier_for__2", tags=["天气预报机器人"])


SYSTEM_PROMPT = """你是一个专业的天气预报助手。请根据用户提供的城市名称或地区，生成一份详细、逼真的天气预报。

你的回复应该包含：
1. 当前天气状况（温度、湿度、天气现象）
2. 未来24小时预报
3. 未来3-7天趋势
4. 穿衣建议
5. 出行建议

注意：
- 使用中文回复
- 语气友好专业
- 数据要合理逼真（基于该城市 typical 气候特征）
- 如果用户没有指定城市，请友好地询问

格式示例：
🌤️ **北京市今日天气预报**

📍 当前状况：晴，22°C，湿度45%

⏰ 24小时预报：
- 上午：晴，18-24°C
- 下午：多云，24-26°C
- 夜间：晴，16-20°C

📅 未来趋势：
- 明天：多云转小雨，18-25°C
- 后天：晴，20-28°C
...

👔 穿衣建议：...
🚗 出行建议：...
"""


async def handle_chat(
    messages: list[dict],
    *,
    config: Optional[dict] = None
) -> dict:
    """
    Handle chat messages for weather forecast bot.
    
    Args:
        messages: List of message dicts with 'role' and 'content' keys
        config: Optional configuration dict
        
    Returns:
        Dict with 'content' key containing the weather forecast reply
    """
    user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_msg = msg.get("content", "")
            break
    
    print(f"[weather_bot] handle_chat called | user_input_len={len(user_msg)}")
    
    # Build conversation with system prompt
    conversation = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ] + messages
    
    try:
        # Call LLM for weather forecast generation
        print("[weather_bot] Calling LLM for weather forecast...")
        response = await chat_completion(conversation)
        print(f"[weather_bot] LLM response received | response_len={len(response)}")
        
        return {
            "content": response,
            "type": "weather_forecast"
        }
        
    except Exception as e:
        print(f"[weather_bot] ERROR: {type(e).__name__}: {e}")
        return {
            "content": f"抱歉，生成天气预报时出现错误：{str(e)}\n\n请稍后重试，或者直接告诉我您想查询哪个城市的天气！",
            "type": "error"
        }


@router.get("/")
async def app_info():
    """Get app information"""
    return {
        "name": "天气预报机器人",
        "description": "智能天气预报助手，为您提供详细的天气信息和出行建议",
        "version": "1.0.0"
    }