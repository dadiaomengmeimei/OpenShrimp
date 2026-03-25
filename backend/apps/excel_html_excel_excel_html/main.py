"""
Excel to HTML Charts App
根据上传的Excel文件生成自适应分布图的HTML网页
"""
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import HTMLResponse

from backend.core.file_toolkit import (
    parse_excel,
    generate_chart,
    generate_and_register_excel,
    register_existing_file,
    make_download_link,
    make_image_embed,
)

router = APIRouter(prefix="/api/apps/excel_html_excel_excel_html", tags=["Excel转HTML图表"])
logger = logging.getLogger(__name__)


async def handle_chat(messages: List[Dict[str, Any]], *, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    处理用户消息，根据上传的Excel文件生成HTML网页
    
    messages: 聊天消息列表
    config: 可选配置
    """
    print(f"[excel_html] handle_chat called | messages_count={len(messages)}")
    
    # 获取用户消息
    user_msg = messages[-1] if messages else {}
    user_text = user_msg.get("content", "")
    files = user_msg.get("files") or []  # Handle both missing key and explicit None
    
    print(f"[excel_html] user_text: {user_text[:100] if user_text else 'empty'}")
    print(f"[excel_html] files_count: {len(files)}")
    
    # 检查是否有上传的文件
    if not files:
        return {
            "content": "请上传一个Excel文件（.xlsx或.xlsx格式），我将根据文件数据生成包含自适应分布图的HTML网页。\n\n您可以上传包含数值数据的Excel文件，我会自动分析并生成适合的图表展示。"
        }
    
    # 处理上传的Excel文件
    excel_file = files[0]
    file_path = excel_file.get("path")
    file_name = excel_file.get("name", "data.xlsx")
    
    print(f"[excel_html] Processing file: {file_name} at {file_path}")
    
    if not file_path or not file_path.endswith(('.xlsx', '.xls')):
        return {
            "content": "请上传Excel文件（.xlsx或.xlsx格式）。"
        }
    
    try:
        # 解析Excel文件
        print(f"[excel_html] Parsing Excel file...")
        excel_data = parse_excel(file_path)
        
        headers = excel_data.get("headers", [])
        rows = excel_data.get("rows", [])
        row_count = excel_data.get("row_count", 0)
        
        print(f"[excel_html] Excel parsed: {row_count} rows, {len(headers)} columns")
        print(f"[excel_html] Headers: {headers}")
        
        if row_count == 0 or not headers:
            return {
                "content": "Excel文件为空或格式不正确，请确保文件包含有效的数据。"
            }
        
        # 生成HTML文件
        html_path = await generate_html_from_excel(headers, rows, file_name)
        print(f"[excel_html] HTML generated: {html_path}")
        
        # 注册下载链接
        result = register_existing_file(html_path, filename=f"{Path(file_name).stem}_charts.html")
        download_link = result["markdown_link"]
        
        return {
            "content": f"✅ HTML网页已生成！\n\n📊 数据概览：\n- 行数：{row_count}\n- 列数：{len(headers)}\n- 列名：{', '.join(headers[:10])}{'...' if len(headers) > 10 else ''}\n\n📥 下载HTML文件：{download_link}\n\n网页包含自适应分布图，可直接在浏览器中打开查看。"
        }
        
    except Exception as e:
        print(f"[excel_html] ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return {
            "content": f"处理Excel文件时出错：{str(e)}"
        }


async def generate_html_from_excel(headers: List[str], rows: List[List[Any]], source_filename: str) -> Path:
    """
    根据Excel数据生成HTML网页
    
    Args:
        headers: 表头列表
        rows: 数据行列表
        source_filename: 源文件名
    
    Returns:
        生成的HTML文件路径
    """
    import base64
    
    # 生成图表
    charts_html = []
    
    # 分析数据类型
    numeric_cols = []
    categorical_cols = []
    
    for i, header in enumerate(headers):
        if i < len(rows) and rows:
            # 检查前几行数据判断列类型
            sample_values = [row[i] for row in rows[:10] if i < len(row)]
            try:
                # 检查是否为数值列：所有值都能转换为浮点数（排除日期字符串）
                numeric_count = 0
                for v in sample_values:
                    if v is not None:
                        v_str = str(v)
                        # 排除日期格式（YYYY-MM-DD等）
                        if '-' in v_str and len(v_str) in [8, 10] and v_str[:4].isdigit():
                            continue  # 可能是日期，跳过
                        try:
                            float(v_str)
                            numeric_count += 1
                        except (ValueError, TypeError):
                            pass
                
                if numeric_count > len(sample_values) * 0.5:
                    numeric_cols.append((i, header))
                else:
                    categorical_cols.append((i, header))
            except Exception:
                categorical_cols.append((i, header))
    
    # 为数值列生成图表
    for col_idx, col_name in numeric_cols[:5]:  # 最多5个数值列
        values = [row[col_idx] for row in rows if col_idx < len(row) and row[col_idx] is not None]
        if len(values) < 2:
            continue
        
        # 安全转换为数值，忽略无法转换的值
        numeric_values = []
        for v in values:
            try:
                numeric_values.append(float(v))
            except (ValueError, TypeError):
                # 跳过无法转换为浮点数的值（如日期字符串）
                print(f"[excel_html] Skipping non-numeric value in column {col_name}: {v}")
                continue
        
        if len(numeric_values) < 2:
            print(f"[excel_html] Column {col_name} has insufficient numeric values, skipping chart")
            continue
        
        # 准备数据
        data = {
            "labels": [f"项{i+1}" for i in range(len(numeric_values))],
            "values": numeric_values
        }
        
        try:
            # 生成图表图片
            chart_path = generate_chart("bar", data, title=col_name)
            
            # 读取图表并转为base64
            with open(chart_path, "rb") as f:
                chart_base64 = base64.b64encode(f.read()).decode()
            
            charts_html.append(f"""
            <div class="chart-container">
                <h3>{col_name}</h3>
                <img src="data:image/png;base64,{chart_base64}" alt="{col_name}" />
            </div>
            """)
        except Exception as e:
            print(f"[excel_html] Error generating chart for {col_name}: {e}")
    
    # 为分类列生成饼图
    for col_idx, col_name in categorical_cols[:3]:  # 最多3个分类列
        # 统计各类别数量
        category_count = {}
        for row in rows:
            if col_idx < len(row) and row[col_idx] is not None:
                val = str(row[col_idx])
                category_count[val] = category_count.get(val, 0) + 1
        
        if len(category_count) > 1 and len(category_count) <= 20:
            data = {
                "labels": list(category_count.keys()),
                "values": list(category_count.values())
            }
            
            try:
                chart_path = generate_chart("pie", data, title=col_name)
                
                with open(chart_path, "rb") as f:
                    chart_base64 = base64.b64encode(f.read()).decode()
                
                charts_html.append(f"""
                <div class="chart-container">
                    <h3>{col_name} (分布)</h3>
                    <img src="data:image/png;base64,{chart_base64}" alt="{col_name}" />
                </div>
                """)
            except Exception as e:
                print(f"[excel_html] Error generating pie chart for {col_name}: {e}")
    
    # 生成数据表格HTML
    table_rows_html = ""
    for row in rows[:100]:  # 最多显示100行
        cells = [f"<td>{row[i] if i < len(row) else ''}</td>" for i in range(len(headers))]
        table_rows_html += f"<tr>{''.join(cells)}</tr>\n"
    
    # 生成完整HTML
    html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>数据可视化 - {source_filename}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        header {{
            background: white;
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }}
        
        h1 {{
            color: #333;
            font-size: 2em;
            margin-bottom: 10px;
        }}
        
        .info {{
            color: #666;
            font-size: 0.95em;
        }}
        
        .section {{
            background: white;
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        }}
        
        .section h2 {{
            color: #444;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
        }}
        
        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 30px;
        }}
        
        .chart-container {{
            background: #f8f9fa;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        
        .chart-container h3 {{
            color: #555;
            margin-bottom: 15px;
            font-size: 1.1em;
        }}
        
        .chart-container img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
        }}
        
        .table-wrapper {{
            overflow-x: auto;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}
        
        th, td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #e0e0e0;
        }}
        
        th {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-weight: 600;
            position: sticky;
            top: 0;
        }}
        
        tr:hover {{
            background: #f5f5f5;
        }}
        
        tr:nth-child(even) {{
            background: #fafafa;
        }}
        
        .footer {{
            text-align: center;
            color: white;
            margin-top: 20px;
            opacity: 0.9;
        }}
        
        /* 响应式布局 */
        @media (max-width: 768px) {{
            .charts-grid {{
                grid-template-columns: 1fr;
            }}
            
            h1 {{
                font-size: 1.5em;
            }}
            
            .section {{
                padding: 20px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 数据可视化报告</h1>
            <p class="info">数据来源: {source_filename} | 共 {len(rows)} 行, {len(headers)} 列</p>
        </header>
        
        <section class="section">
            <h2>📈 分布图表</h2>
            <div class="charts-grid">
                {''.join(charts_html) if charts_html else '<p style="color:#666;">暂无足够的数值数据生成图表</p>'}
            </div>
        </section>
        
        <section class="section">
            <h2>📋 数据表格</h2>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            {''.join(f'<th>{h}</th>' for h in headers)}
                        </tr>
                    </thead>
                    <tbody>
                        {table_rows_html}
                    </tbody>
                </table>
            </div>
            {'<p style="color:#888;margin-top:10px;">* 仅显示前100行数据</p>' if len(rows) > 100 else ''}
        </section>
        
        <div class="footer">
            <p>由 AppShrimp AI App Store 自动生成</p>
        </div>
    </div>
</body>
</html>'''
    
    # 保存HTML文件
    output_dir = Path("/Users/morphe/Desktop/proj/tme/AppShrimp/backend/apps/excel_html_excel_excel_html/output")
    output_dir.mkdir(exist_ok=True)
    
    html_path = output_dir / f"{Path(source_filename).stem}_charts.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    return html_path


@router.post("/upload")
async def upload_excel(file: UploadFile = File(...)):
    """直接上传Excel文件并返回HTML"""
    import tempfile
    
    # 保存上传的文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        # 解析Excel
        excel_data = parse_excel(tmp_path)
        headers = excel_data.get("headers", [])
        rows = excel_data.get("rows", [])
        
        # 生成HTML
        html_path = await generate_html_from_excel(headers, rows, file.filename)
        
        # 返回HTML内容
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        
        return HTMLResponse(content=html_content)
    finally:
        Path(tmp_path).unlink(missing_ok=True)