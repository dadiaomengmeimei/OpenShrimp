"""
宋词写作机器人 (Song Ci Poetry Writer)
A specialized AI assistant for generating Song Dynasty poetry (宋词).
Supports various popular ci-poetic forms (词牌) and classical Chinese style.
"""

from fastapi import APIRouter
from backend.core.llm_service import chat_completion

router = APIRouter(prefix="/api/apps/ci_writer", tags=["宋词写作机器人"])

# Common Song Ci forms (词牌) with their characteristics
CI_PAI_FORMS = {
    "浣溪沙": {
        "lines": 6,
        "description": "双调四十二字，上片三句三平韵，下片三句两平韵。适合写景抒情。",
        "examples": ["一曲新词酒一杯", "无可奈何花落去，似曾相识燕归来"]
    },
    "如梦令": {
        "lines": 7,
        "description": "单调三十三字，七句五仄韵、一叠韵。婉转缠绵，适合抒写细腻情感。",
        "examples": ["常记溪亭日暮", "知否，知否？应是绿肥红瘦"]
    },
    "水调歌头": {
        "lines": 19,
        "description": "双调九十五字，上片九句四平韵，下片十句四平韵。气势恢宏，适合豪放派作品。",
        "examples": ["明月几时有，把酒问青天", "但愿人长久，千里共婵娟"]
    },
    "念奴娇": {
        "lines": 20,
        "description": "双调一百字，上片十句四仄韵，下片十一句五仄韵。豪放派代表词牌。",
        "examples": ["大江东去，浪淘尽", "人生如梦，一尊还酹江月"]
    },
    "满江红": {
        "lines": 18,
        "description": "双调九十三字，上片八句四仄韵，下片十句五仄韵。慷慨激昂，适合豪放壮志。",
        "examples": ["怒发冲冠，凭栏处", "莫等闲，白了少年头，空悲切"]
    },
    "清平乐": {
        "lines": 8,
        "description": "双调四十六字，上片四仄韵，下片三平韵。清新雅致，适合闲适题材。",
        "examples": ["春归何处，寂寞无行路", "若有人知春去处，唤取归来同住"]
    },
    "西江月": {
        "lines": 8,
        "description": "双调五十字，上下片各四句两平韵一叶韵。轻快流畅，适合即景抒情。",
        "examples": ["明月别枝惊鹊，清风半夜鸣蝉", "稻花香里说丰年，听取蛙声一片"]
    },
    "蝶恋花": {
        "lines": 10,
        "description": "双调六十字，上下片各四句四仄韵。婉转深情，适合闺怨、相思题材。",
        "examples": ["花褪残红青杏小", "枝上柳绵吹又少，天涯何处无芳草"]
    },
    "声声慢": {
        "lines": 20,
        "description": "双调九十七字，前后片各五仄韵。叠字开篇是其特色，适合悲秋怀人。",
        "examples": ["寻寻觅觅，冷冷清清，凄凄惨惨戚戚", "这次第，怎一个愁字了得"]
    },
    "雨霖铃": {
        "lines": 20,
        "description": "双调一百三字，上片十句五仄韵，下片十一句五仄韵。缠绵悱恻，适合离别题材。",
        "examples": ["寒蝉凄切，对长亭晚", "多情自古伤离别，更那堪冷落清秋节"]
    },
    "菩萨蛮": {
        "lines": 8,
        "description": "双调四十四字，上下片各四句两仄韵两平韵。格律独特，适合闺情、宫怨。",
        "examples": ["小山重叠金明灭", "新帖绣罗襦，双双金鹧鸪"]
    },
    "虞美人": {
        "lines": 8,
        "description": "双调五十六字，上下片各四句两仄韵两平韵。转折跌宕，适合抒发亡国之痛。",
        "examples": ["春花秋月何时了", "问君能有几多愁，恰似一江春水向东流"]
    },
    "青玉案": {
        "lines": 15,
        "description": "双调六十七字，上下片各六句五仄韵。适合豪放或婉约多种风格。",
        "examples": ["东风夜放花千树", "众里寻他千百度，蓦然回首，那人却在，灯火阑珊处"]
    },
    "卜算子": {
        "lines": 8,
        "description": "双调四十四字，上下片各四句两仄韵。简洁明快，适合咏物言志。",
        "examples": ["缺月挂疏桐，漏断人初静", "拣尽寒枝不肯栖，寂寞沙洲冷"]
    },
    "鹊桥仙": {
        "lines": 10,
        "description": "双调五十六字，上下片各五句两仄韵。专门咏七夕牛郎织女故事。",
        "examples": ["纤云弄巧，飞星传恨", "两情若是久长时，又岂在朝朝暮暮"]
    }
}


def get_system_prompt() -> str:
    """Generate the system prompt for Song Ci writing assistant."""
    forms_info = "\n".join([
        f"• {name}：{info['description']}\n  名句示例：{'; '.join(info['examples'])}"
        for name, info in CI_PAI_FORMS.items()
    ])
    
    return f"""你是一位精通宋代词学的文学大家，擅长创作婉约派和豪放派宋词。

## 你的专长
1. 精通各种词牌的格律、平仄、押韵要求
2. 深谙宋代文学风格，能模仿苏轼、李清照、辛弃疾、柳永、周邦彦、秦观等名家风格
3. 善于借景抒情，情景交融，意境深远

## 支持的词牌
{forms_info}

## 创作原则
1. **格律严谨**：严格遵循所选词牌的句式结构和韵律要求
2. **意境优美**：情景交融，意在言外
3. **用典恰当**：适当运用典故，增强文化内涵
4. **语言典雅**：使用典雅凝练的文言词汇
5. **情感真挚**：抒发真情实感，避免空洞辞藻

## 输出格式
每次创作包含：
1. **词牌名**：注明所用词牌
2. **题目**：根据内容拟定（可选）
3. **正文**：按传统格式排列，注意断句
4. **赏析**：简要解读词的意境、用典和情感（100-200字）

## 创作提示
- 当用户指定词牌时，严格按该词牌格律创作
- 当用户未指定词牌时，根据主题推荐最适合的词牌
- 可根据用户要求模仿特定词人风格
- 用户可提供意象、情感或主题，你据此创作

请以古典雅致、意境深远的风格创作宋词，展现中国传统文学之美。"""


def detect_ci_pai(user_message: str) -> str | None:
    """Detect if user specified a ci-pai (词牌) in their message."""
    for name in CI_PAI_FORMS.keys():
        if name in user_message:
            return name
    return None


def get_ci_pai_suggestion(theme: str) -> str:
    """Suggest a ci-pai based on the theme."""
    theme_keywords = {
        "离别": "雨霖铃、浣溪沙",
        "思念": "蝶恋花、菩萨蛮",
        "豪放": "念奴娇、水调歌头",
        "壮志": "满江红、贺新郎",
        "闲适": "清平乐、西江月",
        "婉约": "声声慢、如梦令",
        "爱情": "鹊桥仙、临江仙",
        "咏物": "卜算子、贺新郎",
        "月夜": "水调歌头、念奴娇",
        "春天": "蝶恋花、浣溪沙",
        "秋天": "声声慢、水龙吟",
    }
    
    suggestions = []
    for keyword, ci_pai_list in theme_keywords.items():
        if keyword in theme:
            suggestions.append(ci_pai_list)
    
    if suggestions:
        return f"根据你的主题，推荐使用：{'; '.join(suggestions[:2])}"
    return "推荐使用：浣溪沙、水调歌头、蝶恋花、清平乐"


@router.post("/chat")
async def chat_endpoint(request: dict) -> dict:
    """Standard chat endpoint for the platform."""
    messages = request.get("messages", [])
    config = request.get("config", {})
    
    result = await handle_chat(messages, config=config)
    
    if isinstance(result, str):
        return {"content": result}
    return result


async def handle_chat(messages: list[dict], *, config: dict | None = None) -> dict:
    """
    Main entry point for the Song Ci writer chatbot.
    
    Args:
        messages: Chat history including the latest user message
        config: Optional configuration dict
        
    Returns:
        dict with 'content' key containing the reply
    """
    print(f"[ci_writer] handle_chat called | messages_count={len(messages)}")
    
    # Get the latest user message
    user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_msg = msg.get("content", "").strip()
            break
    
    print(f"[ci_writer] user_message_len={len(user_msg)}")
    
    # Check for ci-pai specification
    specified_pai = detect_ci_pai(user_msg)
    if specified_pai:
        print(f"[ci_writer] detected specified ci-pai: {specified_pai}")
    
    # Build the conversation for LLM
    system_msg = {"role": "system", "content": get_system_prompt()}
    conversation = [system_msg] + messages
    
    try:
        # Get response from LLM
        print("[ci_writer] calling chat_completion...")
        response = await chat_completion(conversation)
        print(f"[ci_writer] received response | length={len(response)}")
        
        # If no ci-pai was specified, add a suggestion
        if not specified_pai and len(user_msg) > 5:
            suggestion = get_ci_pai_suggestion(user_msg)
            response = f"{response}\n\n---\n💡 **词牌建议**：{suggestion}"
        
        return {"content": response}
        
    except Exception as e:
        print(f"[ci_writer] ERROR: {type(e).__name__}: {e}")
        return {
            "content": f"抱歉，创作过程中遇到了问题：{str(e)}\n\n请稍后再试，或换个方式描述你的想法。"
        }


@router.get("/ci-pai-list")
async def get_ci_pai_list() -> dict:
    """Get the list of supported ci-pai forms."""
    return {
        "content": "支持的词牌列表",
        "data": {
            name: {
                "description": info["description"],
                "examples": info["examples"]
            }
            for name, info in CI_PAI_FORMS.items()
        }
    }