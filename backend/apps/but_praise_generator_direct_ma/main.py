"""
夸夸机器人 (Praise Bot)
对用户输入的内容主体进行真诚、有趣的夸奖
支持文件上传：txt、word(docx) 文件内容提取后进行夸奖
"""

from fastapi import APIRouter
from backend.core.llm_service import chat_completion
from backend.core.file_toolkit import parse_docx

router = APIRouter(prefix="/api/apps/but_praise_generator_direct_ma", tags=["夸夸机器人"])


PRAISE_SYSTEM_PROMPT = """你是一位超级厉害的夸夸机器人！你的任务就是对用户输入的内容进行真诚、有趣、走心的夸奖。

请遵循以下原则：
1. 首先识别用户输入内容的主体（人、事物、行为、作品等）
2. 从多个角度发掘值得夸奖的亮点（努力、创意、态度、结果、细节等）
3. 用温暖、幽默、真诚的语言进行夸奖
4. 夸奖要具体，不要空洞，要让人感受到你是真心在夸
5. 可以适当使用emoji增加亲切感
6. 语气要积极向上，让人看了心情变好
7. 如果用户输入的是自我分享，要给予鼓励和支持

输出格式要求：
- 先点明你夸的是什么主体
- 然后给出3-5个角度的具体夸奖
- 最后送上祝福或鼓励
- 整体字数控制在200-400字左右
- 使用Markdown格式，让内容更易读
"""

FILE_CONTENT_PRAISE_PROMPT = """你是一位超级厉害的夸夸机器人！用户上传了一份文件，你需要先阅读文件内容，然后对内容进行真诚、有趣、走心的夸奖。

请遵循以下原则：
1. 识别文件内容的主题和核心要点
2. 从多个角度发掘值得夸奖的亮点（创意、结构、表达、努力、思考深度、细节等）
3. 用温暖、幽默、真诚的语言进行夸奖
4. 夸奖要具体，结合文件中的实际内容，不要空洞
5. 可以适当使用emoji增加亲切感
6. 语气要积极向上，让人看了心情变好
7. 如果内容是作品/文章，可以点评其亮点；如果是记录/笔记，可以夸奖其认真态度

输出格式要求：
- 先简要概括你读到的内容主题
- 然后给出3-5个角度的具体夸奖（结合文件内容）
- 最后送上祝福或鼓励
- 整体字数控制在300-500字左右
- 使用Markdown格式，让内容更易读
"""


def parse_txt_file(file_path: str) -> str:
    """解析txt文件内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        # 尝试其他编码
        with open(file_path, 'r', encoding='gbk') as f:
            return f.read()


def extract_file_content(file_path: str, file_name: str) -> str:
    """
    根据文件类型提取内容
    
    Args:
        file_path: 文件路径
        file_name: 文件名（用于判断文件类型）
        
    Returns:
        str: 提取的文件内容
    """
    file_name_lower = file_name.lower()
    
    if file_name_lower.endswith('.txt'):
        print(f"[夸夸机器人] 解析TXT文件: {file_name}")
        return parse_txt_file(file_path)
    
    elif file_name_lower.endswith('.docx') or file_name_lower.endswith('.doc'):
        print(f"[夸夸机器人] 解析Word文件: {file_name}")
        return parse_docx(file_path)
    
    else:
        raise ValueError(f"不支持的文件类型: {file_name}。目前支持 txt 和 word(docx) 文件。")


async def handle_chat(
    messages: list[dict],
    *,
    config: dict | None = None
) -> dict:
    """
    处理用户输入，生成夸奖内容
    支持直接输入文本或上传文件(txt/word)
    
    Args:
        messages: 聊天消息列表，包含用户输入和文件
        config: 可选的配置参数
        
    Returns:
        dict: 包含夸奖内容的响应
    """
    # 获取用户最后一条消息
    user_message = ""
    uploaded_files = []
    
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "").strip()
            uploaded_files = msg.get("files", [])
            break
    
    print(f"[夸夸机器人] 收到用户输入 | 文本长度: {len(user_message)} 字符 | 上传文件数: {len(uploaded_files)}")
    
    # 检查是否有文件上传
    if uploaded_files:
        try:
            # 处理上传的文件
            file_contents = []
            for file_info in uploaded_files:
                file_path = file_info.get("path", "")
                file_name = file_info.get("name", "")
                
                if not file_path or not file_name:
                    continue
                
                # 提取文件内容
                content = extract_file_content(file_path, file_name)
                if content.strip():
                    file_contents.append(f"【文件: {file_name}】\n{content}")
                    print(f"[夸夸机器人] 成功提取文件内容 | {file_name} | 内容长度: {len(content)} 字符")
            
            if file_contents:
                # 合并所有文件内容
                combined_content = "\n\n---\n\n".join(file_contents)
                
                # 构建LLM消息，使用文件内容专用提示词
                llm_messages = [
                    {"role": "system", "content": FILE_CONTENT_PRAISE_PROMPT},
                    {"role": "user", "content": f"我上传了以下文件，请阅读后夸夸我：\n\n{combined_content}"}
                ]
                
                print(f"[夸夸机器人] 调用LLM基于文件内容生成夸奖...")
                
                # 调用LLM生成夸奖
                praise_content = await chat_completion(llm_messages)
                
                print(f"[夸夸机器人] 夸奖生成成功 | 长度: {len(praise_content)} 字符")
                
                return {
                    "content": praise_content
                }
            else:
                return {
                    "content": "📄 我收到了你的文件，但是没能从中读取到内容呢～\n\n可以检查一下文件是否正常，或者直接把内容发给我，我一样会好好夸夸你的！✨"
                }
                
        except Exception as e:
            print(f"[夸夸机器人] 处理文件时出错: {type(e).__name__}: {e}")
            return {
                "content": f"📄 文件处理时遇到了一点小问题：{str(e)}\n\n别担心，你上传文件这个行为本身就值得夸奖！愿意分享和展示自己的想法，这是很棒的品质！🌟\n\n也可以直接把内容文字发给我，我会好好夸夸你的～"
            }
    
    # 没有文件上传，处理普通文本输入
    if not user_message:
        return {
            "content": "💫 你什么都不说，我怎么夸你呀～\n\n快告诉我你想让我夸什么吧！可以是你自己、你的作品、你的努力，或者上传一个 txt/word 文件让我来夸！"
        }
    
    # 构建LLM消息
    llm_messages = [
        {"role": "system", "content": PRAISE_SYSTEM_PROMPT},
        {"role": "user", "content": f"请夸夸这个：\n\n{user_message}"}
    ]
    
    print(f"[夸夸机器人] 调用LLM生成夸奖内容...")
    
    try:
        # 调用LLM生成夸奖
        praise_content = await chat_completion(llm_messages)
        
        print(f"[夸夸机器人] 夸奖生成成功 | 长度: {len(praise_content)} 字符")
        
        return {
            "content": praise_content
        }
        
    except Exception as e:
        print(f"[夸夸机器人] 生成夸奖时出错: {type(e).__name__}: {e}")
        # 返回一个友好的错误消息
        return {
            "content": "✨ 哎呀，我的夸奖系统暂时有点卡壳了～\n\n但我还是要说：\n\n**你愿意分享这件事本身就很棒！**\n\n每一个愿意表达、愿意分享的人，都值得被看见和被夸奖！🌟"
        }