"""
LLM Prompt Templates for Tang Poetry Generator (唐诗生成器)
"""

# System prompt for the Tang poetry expert role
TANG_POET_SYSTEM_PROMPT = """你是一位精通唐诗的文学大师，擅长创作格律严谨、意境深远的唐诗。

你的职责：
1. 根据用户给定的主题、体裁和情感基调，创作一首符合唐诗格律的诗歌
2. 遵循平仄规则，讲究押韵和对仗
3. 意境要优美，用词要典雅，体现唐诗的韵味

创作要求：
- 五言绝句：4句，每句5字，共20字
- 七言绝句：4句，每句7字，共28字  
- 五言律诗：8句，每句5字，共40字
- 七言律诗：8句，每句7字，共56字

绝句讲究起承转合，律诗则要求中间两联对仗工整。

输出格式必须是JSON，包含以下字段：
{
    "title": "诗歌标题",
    "poem_lines": ["第一句", "第二句", "第三句", "第四句"],
    "annotation": "对诗歌的注释、赏析和创作背景说明"
}"""


def build_poetry_prompt(theme: str, style: str, mood: str) -> str:
    """
    Build a user prompt for Tang poetry generation.
    
    Args:
        theme: 诗歌主题
        style: 诗歌体裁（五言绝句/七言绝句/五言律诗/七言律诗）
        mood: 情感基调
    
    Returns:
        Formatted prompt string
    """
    style_requirements = {
        "五言绝句": "创作一首五言绝句（4句，每句5字），讲究起承转合，押韵自然。",
        "七言绝句": "创作一首七言绝句（4句，每句7字），讲究起承转合，押韵自然。",
        "五言律诗": "创作一首五言律诗（8句，每句5字），要求中间两联对仗工整，押韵严谨。",
        "七言律诗": "创作一首七言律诗（8句，每句7字），要求中间两联对仗工整，押韵严谨。"
    }
    
    requirement = style_requirements.get(style, style_requirements["五言绝句"])
    
    prompt = f"""请为我创作一首唐诗。

主题：{theme}
体裁：{style}
情感基调：{mood}

{requirement}

请确保：
1. 标题贴切，富有诗意
2. 格律严谨，符合{style}的格式要求
3. 意境优美，体现{mood}的情感
4. 用词典雅，有唐诗韵味

请以JSON格式返回结果。"""

    return prompt


# Example response format for few-shot learning
EXAMPLE_POETRY_JSON = """
{
    "title": "春晓",
    "poem_lines": ["春眠不觉晓", "处处闻啼鸟", "夜来风雨声", "花落知多少"],
    "annotation": "这首诗描绘了春日清晨醒来时的情景。诗人通过听觉感受春天的气息，表达了对春光流逝的淡淡惋惜之情。全诗语言清新自然，意境优美，是五言绝句的经典之作。"
}
"""