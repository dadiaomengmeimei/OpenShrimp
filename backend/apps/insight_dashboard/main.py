"""
Insight Dashboard - Excel数据分析与可视化仪表盘
自适应生成数据洞察、统计图表和九宫格分析
"""

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from backend.core.file_toolkit import (
    parse_excel,
    generate_chart,
    generate_and_register_chart,
    make_download_link,
    make_image_embed,
    truncate_text,
    format_table_as_markdown,
)
from backend.core.llm_service import chat_completion

router = APIRouter(prefix="/api/apps/insight_dashboard", tags=["Insight Dashboard"])


def _rows_to_dicts(data: dict) -> list[dict]:
    """Convert parse_excel rows (list[list]) to list[dict] using headers as keys."""
    headers = data["headers"]
    return [dict(zip(headers, row)) for row in data["rows"]]

# Ensure static directory exists
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

# Store uploaded files temporarily
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@router.get("/web", response_class=HTMLResponse)
async def web_ui():
    """Serve the main web application page."""
    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="Web UI not found")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@router.post("/upload")
async def upload_excel(file: UploadFile = File(...)):
    """Upload and parse Excel file, return parsed data for the frontend."""
    print(f"[insight_dashboard] Uploading file: {file.filename}")

    if not file.filename:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "未提供文件"}
        )

    try:
        # Save file to uploads dir
        import uuid as _uuid
        ext = Path(file.filename).suffix
        unique_name = f"{_uuid.uuid4().hex[:12]}{ext}"
        file_path = UPLOAD_DIR / unique_name

        content = await file.read()
        file_path.write_bytes(content)
        print(f"[insight_dashboard] File saved: {file.filename} -> {file_path} ({len(content)} bytes)")

        # Parse the Excel/CSV file
        data = parse_excel(str(file_path))

        # Convert rows from list[list] to list[dict] for frontend
        headers = data["headers"]
        sample_rows = data["rows"][:20]
        sample_data = [dict(zip(headers, row)) for row in sample_rows]

        return {
            "success": True,
            "file_path": str(file_path),
            "data": {
                "file_name": file.filename,
                "row_count": data["row_count"],
                "column_count": len(headers),
                "headers": headers,
                "sample_data": sample_data,
            },
        }
    except Exception as e:
        print(f"[insight_dashboard] Upload error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": f"文件解析失败: {str(e)}"}
        )


@router.post("/analyze")
async def analyze_data(
    file_path: str = Form(...),
    analysis_type: str = Form("comprehensive"),
):
    """Generate AI-powered data insights."""
    print(f"[insight_dashboard] Analyzing data: {file_path}, type: {analysis_type}")
    
    try:
        # Parse Excel
        data = parse_excel(file_path)
        
        if data["row_count"] == 0:
            return {"success": False, "error": "数据为空"}
        
        # Prepare data summary for LLM
        headers = data["headers"]
        rows = _rows_to_dicts(data)
        
        # Calculate basic stats for numeric columns
        numeric_stats = calculate_numeric_stats(data)
        
        # Create data summary for LLM
        data_summary = {
            "总记录数": data["row_count"],
            "字段列表": headers,
            "数值字段统计": numeric_stats,
            "样本数据": rows[:10],
        }
        
        # Generate insights using LLM
        system_prompt = """你是一位专业的数据分析师。请根据提供的数据生成深入的数据洞察报告。

要求：
1. 分析数据的整体特征和分布
2. 识别关键趋势和模式
3. 发现异常值或值得关注的数据点
4. 提供业务建议和数据驱动的洞察
5. 使用中文回答，结构清晰

输出格式要求（JSON）：
{
    "overview": "数据概览（2-3句话）",
    "key_findings": ["发现1", "发现2", "发现3"],
    "trends": ["趋势1", "趋势2"],
    "anomalies": ["异常1"],
    "recommendations": ["建议1", "建议2", "建议3"],
    "risk_factors": ["风险1", "风险2"]
}"""

        user_prompt = f"""请分析以下数据并生成洞察报告：

{json.dumps(data_summary, ensure_ascii=False, indent=2)}

分析类型: {analysis_type}
"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        
        print(f"[insight_dashboard] Calling LLM for analysis...")
        llm_response = await chat_completion(messages)
        
        # Try to parse JSON from response (may be wrapped in markdown code block)
        cleaned = llm_response.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
            cleaned = cleaned[first_newline + 1:]
            if cleaned.rstrip().endswith("```"):
                cleaned = cleaned.rstrip()[:-3].rstrip()
        try:
            insights = json.loads(cleaned)
        except json.JSONDecodeError:
            # If not valid JSON, wrap the text response
            insights = {
                "overview": llm_response[:500],
                "key_findings": ["数据包含丰富的信息"],
                "trends": [],
                "anomalies": [],
                "recommendations": [],
                "risk_factors": [],
            }
        
        print(f"[insight_dashboard] Analysis complete")
        
        return {
            "success": True,
            "insights": insights,
            "stats": numeric_stats,
        }
    
    except Exception as e:
        print(f"[insight_dashboard] Analysis error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@router.post("/charts")
async def generate_charts(
    file_path: str = Form(...),
    chart_types: str = Form("auto"),  # auto, bar, line, pie, scatter
):
    """Generate statistical charts based on data."""
    print(f"[insight_dashboard] Generating charts for: {file_path}")
    
    try:
        data = parse_excel(file_path)
        headers = data["headers"]
        rows = _rows_to_dicts(data)
        
        if not rows:
            return {"success": False, "error": "无数据可分析"}
        
        # Identify numeric columns
        numeric_cols = identify_numeric_columns(data)
        categorical_cols = [h for h in headers if h not in numeric_cols]
        
        charts = []
        
        # Chart 1: Bar chart for first numeric column (if exists)
        if numeric_cols:
            col = numeric_cols[0]
            values = [row.get(col, 0) for row in rows if isinstance(row.get(col), (int, float))]
            labels = [f"记录{i+1}" for i in range(len(values))][:20]
            
            if values:
                chart_data = {
                    "labels": labels,
                    "values": values[:20],
                    "ylabel": col,
                }
                result = generate_and_register_chart(
                    "bar", chart_data, title=f"{col} 分布"
                )
                charts.append({
                    "type": "bar",
                    "title": f"{col} 分布",
                    "embed": result["image_embed"],
                    "download": result["markdown_link"],
                })
        
        # Chart 2: Pie chart for first categorical column (if exists)
        if categorical_cols:
            col = categorical_cols[0]
            category_counts = {}
            for row in rows:
                val = str(row.get(col, "未知"))
                category_counts[val] = category_counts.get(val, 0) + 1
            
            sorted_items = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:8]
            chart_data = {
                "labels": [item[0] for item in sorted_items],
                "values": [item[1] for item in sorted_items],
            }
            result = generate_and_register_chart(
                "pie", chart_data, title=f"{col} 分类占比"
            )
            charts.append({
                "type": "pie",
                "title": f"{col} 分类占比",
                "embed": result["image_embed"],
                "download": result["markdown_link"],
            })
        
        # Chart 3: Line chart for second numeric column over index
        if len(numeric_cols) >= 2:
            col = numeric_cols[1]
            values = [row.get(col, 0) for row in rows if isinstance(row.get(col), (int, float))]
            labels = [f"记录{i+1}" for i in range(len(values))][:30]
            
            if values:
                chart_data = {
                    "labels": labels,
                    "values": values[:30],
                    "ylabel": col,
                }
                result = generate_and_register_chart(
                    "line", chart_data, title=f"{col} 趋势"
                )
                charts.append({
                    "type": "line",
                    "title": f"{col} 趋势",
                    "embed": result["image_embed"],
                    "download": result["markdown_link"],
                })
        
        # Chart 4: Scatter plot if we have 2+ numeric columns
        if len(numeric_cols) >= 2:
            x_col, y_col = numeric_cols[0], numeric_cols[1]
            x_vals = []
            y_vals = []
            for row in rows:
                x = row.get(x_col)
                y = row.get(y_col)
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    x_vals.append(x)
                    y_vals.append(y)
            
            if len(x_vals) >= 5:
                chart_data = {
                    "x": x_vals[:50],
                    "y": y_vals[:50],
                    "xlabel": x_col,
                    "ylabel": y_col,
                }
                result = generate_and_register_chart(
                    "scatter", chart_data, title=f"{x_col} vs {y_col} 散点图"
                )
                charts.append({
                    "type": "scatter",
                    "title": f"{x_col} vs {y_col} 散点图",
                    "embed": result["image_embed"],
                    "download": result["markdown_link"],
                })
        
        print(f"[insight_dashboard] Generated {len(charts)} charts")
        
        return {
            "success": True,
            "charts": charts,
            "numeric_columns": numeric_cols,
            "categorical_columns": categorical_cols,
        }
    
    except Exception as e:
        print(f"[insight_dashboard] Chart generation error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@router.post("/grid-analysis")
@router.post("/nine-grid")
async def grid_analysis(
    file_path: str = Form(...),
    grid_type: str = Form("nine-box"),  # nine-box, priority, swot
):
    """Generate grid analysis (nine-box, priority matrix, SWOT, etc.)."""
    print(f"[insight_dashboard] Grid analysis: {file_path}, type: {grid_type}")
    
    try:
        data = parse_excel(file_path)
        
        # Prepare analysis based on grid type
        grid_prompts = {
            "nine-box": """请根据数据生成九宫格人才/业务分析：
- 横轴：绩效表现 (低->高)
- 纵轴：潜力/能力 (低->高)
- 识别高绩效高潜力、需要关注等类别
输出格式：描述每个格子的特征和对应的数据点""",
            "priority": """请根据数据生成优先级矩阵分析：
- 横轴：影响程度 (低->高)
- 纵轴：紧急程度 (低->高)
- 分为四个象限：紧急重要、重要不紧急、紧急不重要、不紧急不重要
输出格式：每个象限的建议和数据点分类""",
            "swot": """请根据数据生成SWOT分析：
- 优势 (Strengths)
- 劣势 (Weaknesses)
- 机会 (Opportunities)
- 威胁 (Threats)
输出格式：JSON格式，包含四个字段的列表""",
        }
        
        system_prompt = f"""你是一位专业的战略分析师。请根据提供的数据进行{grid_type}分析。

{grid_prompts.get(grid_type, grid_prompts["nine-box"])}

输出格式（JSON）：
{{
    "analysis": "整体分析结论",
    "quadrants": [
        {{"name": "象限名称", "items": ["项目1", "项目2"], "description": "描述"}}
    ],
    "recommendations": ["建议1", "建议2"]
}}"""

        # Prepare data summary
        rows_as_dicts = _rows_to_dicts(data)
        data_summary = {
            "headers": data["headers"],
            "row_count": data["row_count"],
            "sample_data": rows_as_dicts[:20],
        }
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(data_summary, ensure_ascii=False, indent=2)},
        ]
        
        print(f"[insight_dashboard] Calling LLM for grid analysis...")
        llm_response = await chat_completion(messages)
        
        # Try to parse JSON from LLM response (may be wrapped in markdown code block)
        cleaned = llm_response.strip()
        # Strip markdown code fences if present
        if cleaned.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
            cleaned = cleaned[first_newline + 1:]
            # Remove closing fence
            if cleaned.rstrip().endswith("```"):
                cleaned = cleaned.rstrip()[:-3].rstrip()
        try:
            analysis = json.loads(cleaned)
        except json.JSONDecodeError:
            analysis = {
                "analysis": llm_response,
                "quadrants": [],
                "recommendations": [],
            }
        
        # Build nine_grid structure expected by frontend
        headers = data["headers"]
        nine_grid = {
            "x_axis": headers[0] if len(headers) >= 1 else "X轴",
            "y_axis": headers[1] if len(headers) >= 2 else "Y轴",
            "items_count": data["row_count"],
            "grid": {},
        }
        # Map quadrant items from LLM analysis into grid positions
        position_map = [
            "high_high", "high_mid", "high_low",
            "mid_high", "mid_mid", "mid_low",
            "low_high", "low_mid", "low_low",
        ]
        quadrants = analysis.get("quadrants", [])
        for i, pos in enumerate(position_map):
            if i < len(quadrants):
                q = quadrants[i]
                items = q.get("items", [])
                nine_grid["grid"][pos] = [{"name": str(item)} for item in items]
            else:
                nine_grid["grid"][pos] = []
        
        print(f"[insight_dashboard] Grid analysis complete")
        
        return {
            "success": True,
            "nine_grid": nine_grid,
            "analysis": analysis,
            "grid_type": grid_type,
        }
    
    except Exception as e:
        print(f"[insight_dashboard] Grid analysis error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@router.post("/report")
async def generate_report(
    file_path: str = Form(...),
    report_type: str = Form("comprehensive"),
):
    """Generate comprehensive analysis report."""
    print(f"[insight_dashboard] Generating report: {file_path}, type: {report_type}")
    
    try:
        data = parse_excel(file_path)
        
        # Get insights
        numeric_stats = calculate_numeric_stats(data)
        
        # Generate report content using LLM
        system_prompt = """你是一位专业的数据分析报告撰写专家。请根据数据生成专业的分析报告。

报告结构：
1. 执行摘要（Executive Summary）
2. 数据概况
3. 关键发现
4. 详细分析
5. 趋势与预测
6. 建议与行动计划
7. 风险与注意事项

要求：
- 使用专业的商业分析语言
- 提供具体的、可操作的建议
- 使用中文输出
- 格式清晰，使用Markdown"""

        data_summary = {
            "文件名": Path(file_path).name,
            "总记录数": data["row_count"],
            "字段数": len(data["headers"]),
            "字段列表": data["headers"],
            "数值字段统计": numeric_stats,
            "样本数据": data["rows"][:10],
        }
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请基于以下数据生成{report_type}分析报告：\n\n" + 
                json.dumps(data_summary, ensure_ascii=False, indent=2)},
        ]
        
        print(f"[insight_dashboard] Calling LLM for report...")
        report_content = await chat_completion(messages)
        
        print(f"[insight_dashboard] Report generated")
        
        return {
            "success": True,
            "report": report_content,
            "stats": numeric_stats,
        }
    
    except Exception as e:
        print(f"[insight_dashboard] Report generation error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def identify_numeric_columns(data: dict) -> list:
    """Identify which columns contain numeric data."""
    headers = data["headers"]
    rows = _rows_to_dicts(data)
    
    numeric_cols = []
    
    for col in headers:
        numeric_count = 0
        total_count = 0
        
        for row in rows[:100]:  # Check first 100 rows
            val = row.get(col)
            if val is not None and val != "":
                total_count += 1
                try:
                    float(val)
                    numeric_count += 1
                except (ValueError, TypeError):
                    pass
        
        # If more than 70% are numeric, consider it a numeric column
        if total_count > 0 and numeric_count / total_count > 0.7:
            numeric_cols.append(col)
    
    return numeric_cols


def calculate_numeric_stats(data: dict) -> dict:
    """Calculate statistics for numeric columns."""
    numeric_cols = identify_numeric_columns(data)
    rows = _rows_to_dicts(data)
    
    stats = {}
    
    for col in numeric_cols:
        values = []
        for row in rows:
            val = row.get(col)
            try:
                if val is not None and val != "":
                    values.append(float(val))
            except (ValueError, TypeError):
                pass
        
        if values:
            values.sort()
            n = len(values)
            mean = sum(values) / n
            
            # Calculate median
            if n % 2 == 0:
                median = (values[n//2 - 1] + values[n//2]) / 2
            else:
                median = values[n//2]
            
            # Calculate std deviation
            variance = sum((x - mean) ** 2 for x in values) / n
            std_dev = variance ** 0.5
            
            stats[col] = {
                "count": n,
                "min": min(values),
                "max": max(values),
                "mean": round(mean, 2),
                "median": round(median, 2),
                "std_dev": round(std_dev, 2),
            }
    
    return stats


# Chat mode handler
async def handle_chat(messages: list[dict], *, config: dict | None = None) -> dict:
    """
    Handle chat mode requests.
    
    Supports:
    - Analyzing uploaded Excel files
    - Generating data insights
    - Creating charts and visualizations
    - Grid analysis (nine-box, priority matrix, SWOT)
    """
    print(f"[insight_dashboard] handle_chat called | messages_count={len(messages)}")
    
    # Get the last user message
    user_msg = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_msg = msg
            break
    
    if not user_msg:
        return {"content": "请发送一条消息或上传Excel文件进行分析。"}
    
    user_text = user_msg.get("content", "").strip()
    files = user_msg.get("files", [])
    
    print(f"[insight_dashboard] User input: {truncate_text(user_text, 100)} | files: {len(files)}")
    
    # Handle file upload in chat mode
    if files:
        print(f"[insight_dashboard] File upload detected: {[f.get('name') for f in files]}")
        file_info = files[0]
        file_path = file_info.get("path", "")
        file_name = file_info.get("name", "unknown")

        if not file_path or not Path(file_path).exists():
            return {
                "content": f"❌ **文件未找到**\n\n文件 `{file_name}` 不存在或路径无效，请重新上传。"
            }

        try:
            data = parse_excel(file_path)
            numeric_stats = calculate_numeric_stats(data)
            data_summary = {
                "文件名": file_name,
                "总记录数": data["row_count"],
                "字段列表": data["headers"],
                "数值字段统计": numeric_stats,
                "样本数据": data["rows"][:10],
            }

            analysis_prompt = user_text if user_text else "请对这份数据进行全面分析，包括数据概览、关键发现、趋势和建议。"

            messages_for_llm = [
                {"role": "system", "content": "你是一位专业的数据分析师。请根据用户上传的数据和问题进行分析。使用中文回答，格式清晰，使用Markdown。"},
                {"role": "user", "content": f"数据摘要:\n{json.dumps(data_summary, ensure_ascii=False, indent=2)}\n\n用户问题: {analysis_prompt}"},
            ]

            llm_response = await chat_completion(messages_for_llm)
            return {"content": llm_response}
        except Exception as e:
            print(f"[insight_dashboard] Chat file analysis error: {e}")
            return {
                "content": f"❌ **分析失败**\n\n处理文件 `{file_name}` 时出错: {str(e)}\n\n请确认文件格式为 .xlsx / .xls / .csv"
            }
    
    # Handle text-based queries without file
    if not files and user_text:
        # Check if user is asking about file upload
        upload_keywords = ["上传", "文件", "excel", "表格", "导入"]
        if any(keyword in user_text.lower() for keyword in upload_keywords):
            return {
                "content": "📊 **Insight Dashboard - 数据分析仪表盘**\n\n我可以帮您：\n\n1. **上传Excel文件** - 点击输入框旁的 📎 按钮上传文件\n2. **数据洞察分析** - 自动识别数据特征和趋势\n3. **生成可视化图表** - 柱状图、折线图、饼图、散点图\n4. **九宫格分析** - 人才盘点、业务分析\n5. **优先级矩阵** - 任务分类和优先级排序\n6. **SWOT分析** - 战略分析框架\n7. **生成分析报告** - 专业的数据分析报告\n\n请上传您的Excel文件开始分析！"
            }
        
        # General help response
        return {
            "content": "欢迎使用 Insight Dashboard！\n\n请上传Excel文件，我将为您：\n- 📈 生成数据洞察和趋势分析\n- 📊 创建可视化图表\n- 🎯 进行九宫格/矩阵分析\n- 📄 输出专业分析报告\n\n点击输入框旁的 📎 按钮上传文件。"
        }
    
    return {"content": "请上传Excel文件进行分析，或告诉我您想了解什么功能。"}