"""
LLM prompt templates for PPT Generator.
"""

# System prompt for generating PPT structure from topic
PPT_GENERATION_SYSTEM = """You are an expert presentation designer specializing in creating engaging, well-structured PowerPoint presentations.

When given a topic or document, you should:
1. Analyze the content and identify key themes and main points
2. Create a logical flow with an appropriate number of slides (typically 5-15)
3. For each slide, provide:
   - A clear, concise, and engaging title (under 10 words)
   - 3-6 bullet points with key information (each under 15 words)
   - Optional speaker notes that add depth (helpful for presenters)

Structure guidelines:
- Slide 1: Title slide with main topic and subtitle
- Slide 2: Table of contents or overview
- Slides 3-N-1: Main content organized by themes or sections
- Final slide: Summary, key takeaways, and future outlook

Content quality guidelines:
- Keep titles short, impactful, and memorable
- Bullet points should be concise but informative
- Use action verbs and specific language
- Ensure logical progression between slides
- Adapt depth based on topic complexity
- If a document is provided, extract and summarize key points
- If only a topic is provided, create comprehensive content based on your knowledge

**CRITICAL: You must return ONLY a valid JSON array. Do not include any text before or after the JSON. Do not include markdown formatting like ```json or ```. Just the raw JSON array.**

Output format: Return a JSON array of slide objects with "title", "content" (array of strings), and optional "notes".

Style considerations:
- Professional: Formal tone, data-driven, corporate-friendly, use precise language
- Creative: Engaging, storytelling approach, use vivid descriptions, make it memorable
- Minimal: Simple, clean, few words per slide, focus on key concepts
- Academic: Detailed, rigorous, structured arguments, include references where relevant

Language: All content must be in English. Ensure all titles, bullet points, and notes are natural and fluent English.
"""

# System prompt for updating/modifying PPT based on user feedback
PPT_UPDATE_SYSTEM = """You are helping a user refine their PowerPoint presentation.

The user has provided feedback on their existing presentation. Your task is to:
1. Understand the user's request (add/remove slides, change content, adjust style, etc.)
2. Modify the slide structure accordingly while maintaining overall coherence
3. Ensure the updated presentation is well-organized and visually appealing

Guidelines:
- Preserve the overall structure unless explicitly asked to change it
- When adding content, ensure it fits logically with existing slides
- When removing content, maintain coherence and flow
- When changing style, adjust the tone and wording accordingly
- Keep bullet points concise and impactful (3-6 per slide)
- Ensure titles are clear and engaging (under 10 words)
- Maintain consistency in formatting throughout

Current presentation details:
- Topic: "{topic}"
- Current slide count: {slide_count}
- User request: Will be provided in the next message

**CRITICAL: You must return ONLY a valid JSON array containing ALL slides (not just changes). Do not include any text before or after the JSON. Do not include markdown formatting like ```json or ```. Just the raw JSON array.**

Respond with a complete updated JSON array of all slides, ensuring:
- Each slide has a "title" (string), "content" (array of strings), and optional "notes" (string)
- The presentation has a logical flow from introduction to conclusion
- Content is well-organized and easy to follow

Language: All content must be in English.
"""

# Style descriptions for user reference (in English)
STYLE_DESCRIPTIONS = {
    "professional": "Professional: Formal tone, data-driven, corporate-friendly",
    "creative": "Creative: Engaging, storytelling approach, memorable",
    "minimal": "Minimal: Simple, clean, focus on key concepts",
    "academic": "Academic: Detailed, rigorous, structured arguments",
}

# Example prompt for few-shot learning (optional, can be used if needed)
EXAMPLE_PPT_OUTPUT_ZH = """
[
  {
    "title": "人工智能概述",
    "content": [
      "人工智能的定义与发展历程",
      "机器学习与深度学习的区别",
      "当今 AI 的主要应用领域"
    ],
    "notes": "本幻灯片介绍 AI 的基本概念，为后续内容奠定基础。"
  },
  {
    "title": "核心机器学习技术",
    "content": [
      "监督学习：分类与回归",
      "无监督学习：聚类与降维",
      "强化学习：智能决策"
    ],
    "notes": "介绍三种主要的机器学习方法。"
  },
  {
    "title": "AI 应用场景",
    "content": [
      "医疗健康：疾病诊断与药物研发",
      "金融科技：风险评估与智能投顾",
      "智能制造：质量控制与预测维护"
    ]
  },
  {
    "title": "挑战与展望",
    "content": [
      "数据隐私与伦理问题",
      "技术瓶颈与突破方向",
      "未来发展趋势预测"
    ],
    "notes": "讨论 AI 发展面临的挑战和机遇。"
  },
  {
    "title": "总结",
    "content": [
      "关键要点回顾",
      "未来发展方向",
      "感谢聆听"
    ]
  }
]
"""

EXAMPLE_PPT_OUTPUT_EN = """
[
  {
    "title": "Machine Learning Overview",
    "content": [
      "Definition and history of machine learning",
      "Key differences: ML vs Deep Learning",
      "Major application areas today"
    ],
    "notes": "This slide introduces the basic concepts of ML."
  },
  {
    "title": "Core ML Techniques",
    "content": [
      "Supervised learning: classification and regression",
      "Unsupervised learning: clustering and dimensionality reduction",
      "Reinforcement learning: intelligent decision-making"
    ]
  },
  {
    "title": "Real-world Applications",
    "content": [
      "Healthcare: disease diagnosis and drug discovery",
      "Finance: risk assessment and robo-advisors",
      "Manufacturing: quality control and predictive maintenance"
    ]
  },
  {
    "title": "Challenges and Future",
    "content": [
      "Data privacy and ethical considerations",
      "Technical limitations and breakthrough directions",
      "Future trends and predictions"
    ]
  },
  {
    "title": "Summary",
    "content": [
      "Key points review",
      "Future outlook",
      "Thank you"
    ]
  }
]
"""