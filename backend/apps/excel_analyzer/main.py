"""
Excel Analyzer sub-app.
Upload Excel files → AI analysis → chart generation.
Supports CJK (Chinese) font rendering and chart history.
"""
from __future__ import annotations

import base64
import io
import json
import uuid
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.llm_service import chat_completion

router = APIRouter(prefix="/api/apps/excel_analyzer", tags=["excel_analyzer"])

# ────────────────────────────────────────
# CJK Font Configuration
# ────────────────────────────────────────
def _configure_cjk_fonts():
    """Configure matplotlib to display CJK (Chinese/Japanese/Korean) characters properly."""
    # Preferred CJK fonts in order (macOS, Linux, Windows)
    cjk_fonts = [
        "PingFang SC",          # macOS
        "Heiti SC",             # macOS
        "STHeiti",              # macOS
        "Microsoft YaHei",     # Windows
        "SimHei",              # Windows
        "WenQuanYi Micro Hei", # Linux
        "Noto Sans CJK SC",    # Linux (Google)
        "Source Han Sans SC",  # Linux (Adobe)
        "Arial Unicode MS",   # Cross-platform fallback
    ]

    available = {f.name for f in fm.fontManager.ttflist}
    chosen = None
    for font in cjk_fonts:
        if font in available:
            chosen = font
            break

    if chosen:
        plt.rcParams["font.sans-serif"] = [chosen] + plt.rcParams.get("font.sans-serif", [])
    else:
        # Last resort: try to find any font with "CJK", "Hei", "Song", "Ming" in name
        for f in fm.fontManager.ttflist:
            if any(k in f.name for k in ("CJK", "Hei", "Song", "Ming", "Gothic", "PingFang")):
                plt.rcParams["font.sans-serif"] = [f.name] + plt.rcParams.get("font.sans-serif", [])
                break

    plt.rcParams["axes.unicode_minus"] = False  # Fix minus sign display

_configure_cjk_fonts()


# ────────────────────────────────────────
# In-memory stores
# ────────────────────────────────────────
_sessions: dict[str, pd.DataFrame] = {}

# Chart history: session_id -> list of chart records
_chart_history: dict[str, list[dict]] = {}


# ────────────────────────────────────────
# Request / Response models
# ────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    session_id: str
    question: str
    history: list[dict] = []  # Multi-turn chat history [{role, content}]


class ChartRequest(BaseModel):
    session_id: str
    instruction: str


class PresetChartRequest(BaseModel):
    session_id: str
    chart_type: str  # bar, line, pie, radar, scatter, heatmap
    x_column: Optional[str] = None
    y_column: Optional[str] = None
    columns: Optional[list[str]] = None  # Multi-select columns for radar / heatmap
    title: Optional[str] = None


# ────────────────────────────────────────
# Helpers
# ────────────────────────────────────────
def _save_chart_to_history(session_id: str, image_b64: str, code: str, instruction: str, chart_type: str = "custom") -> dict:
    """Save a chart to history and return the record."""
    record = {
        "id": uuid.uuid4().hex[:8],
        "image": image_b64,
        "code": code,
        "instruction": instruction,
        "chart_type": chart_type,
        "timestamp": int(time.time()),
    }
    if session_id not in _chart_history:
        _chart_history[session_id] = []
    _chart_history[session_id].append(record)
    return record


def _render_figure_to_b64(fig) -> str:
    """Render a matplotlib figure to base64 PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close("all")
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.read()).decode()}"


def _style_ax(ax, title: str = ""):
    """Apply a consistent dark style to axes."""
    ax.set_facecolor("#1e293b")
    ax.figure.set_facecolor("#0f172a")
    ax.title.set_color("white")
    ax.xaxis.label.set_color("#94a3b8")
    ax.yaxis.label.set_color("#94a3b8")
    ax.tick_params(colors="#94a3b8")
    for spine in ax.spines.values():
        spine.set_color("#334155")
    if title:
        ax.set_title(title, fontsize=14, fontweight="bold", color="white", pad=12)


# ────────────────────────────────────────
# Routes
# ────────────────────────────────────────

@router.post("/upload")
async def upload_excel(file: UploadFile = File(...)):
    """Upload an Excel / CSV file and return a session_id + preview."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = Path(file.filename).suffix.lower()
    content = await file.read()
    buf = io.BytesIO(content)

    try:
        if ext in (".xlsx", ".xls"):
            df = pd.read_excel(buf)
        elif ext == ".csv":
            df = pd.read_csv(buf)
        else:
            raise HTTPException(400, f"Unsupported file type: {ext}")
    except Exception as e:
        raise HTTPException(400, f"Failed to parse file: {e}")

    session_id = uuid.uuid4().hex[:12]
    _sessions[session_id] = df

    preview = df.head(10).to_dict(orient="records")

    # Analyze columns for smart chart suggestions
    numeric_cols = list(df.select_dtypes(include=["number"]).columns)
    categorical_cols = list(df.select_dtypes(include=["object", "category"]).columns)
    datetime_cols = list(df.select_dtypes(include=["datetime"]).columns)

    return {
        "session_id": session_id,
        "filename": file.filename,
        "rows": len(df),
        "columns": list(df.columns),
        "numeric_columns": numeric_cols,
        "categorical_columns": categorical_cols,
        "datetime_columns": datetime_cols,
        "preview": preview,
    }


# ────────────────────────────────────────
# Code Interpreter: safe exec sandbox
# ────────────────────────────────────────
def _safe_exec_pandas(code: str, df: pd.DataFrame) -> str:
    """Execute pandas/numpy code in a restricted namespace and capture printed output + final expression."""
    import numpy as np
    import io as _io
    import contextlib

    # Capture stdout
    buf = _io.StringIO()
    exec_globals = {
        "__builtins__": {
            "print": print, "len": len, "range": range, "list": list, "dict": dict,
            "str": str, "int": int, "float": float, "bool": bool, "tuple": tuple,
            "set": set, "enumerate": enumerate, "zip": zip, "map": map,
            "filter": filter, "sorted": sorted, "min": min, "max": max,
            "sum": sum, "abs": abs, "round": round, "type": type,
            "isinstance": isinstance, "hasattr": hasattr, "getattr": getattr,
            "ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError,
            "IndexError": IndexError, "Exception": Exception,
            "True": True, "False": False, "None": None,
        },
        "pd": pd,
        "np": np,
        "df": df.copy(),  # Work on a copy to avoid mutation
    }

    with contextlib.redirect_stdout(buf):
        try:
            # Try exec first (for statements)
            exec(code, exec_globals)
        except Exception as e:
            return f"Error executing code: {type(e).__name__}: {e}"

    output = buf.getvalue()

    # If the code assigned a 'result' variable, append it
    if "result" in exec_globals and exec_globals["result"] is not None:
        res = exec_globals["result"]
        if isinstance(res, pd.DataFrame):
            output += "\n" + res.to_string(max_rows=50)
        elif isinstance(res, pd.Series):
            output += "\n" + res.to_string()
        else:
            output += "\n" + str(res)

    # Truncate if too long
    if len(output) > 8000:
        output = output[:8000] + "\n... [output truncated]"

    return output.strip() if output.strip() else "(Code executed successfully, no output)"


_CODE_INTERPRETER_SYSTEM = """You are a data analysis assistant with code execution capability.
The user has uploaded a dataset as a pandas DataFrame named `df`.

When answering questions:
1. If the question requires computation/filtering/aggregation, write Python code using pandas/numpy.
2. Wrap your code in a ```python code block.
3. Use `print()` to output results, or assign the final result to a variable named `result`.
4. Available: `df` (DataFrame), `pd` (pandas), `np` (numpy).
5. After the code block, provide a brief natural language explanation of the results.
6. If the question is simple (e.g. "what columns are there?"), you can answer directly without code.
7. Reply in the same language the user uses.

Dataset info:
{dataset_info}
"""


@router.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """Code Interpreter: LLM generates pandas code → backend executes → returns result. Supports multi-turn."""
    df = _sessions.get(req.session_id)
    if df is None:
        raise HTTPException(404, "Session not found – upload a file first")

    # Build dataset info summary
    dataset_info = (
        f"Columns: {list(df.columns)}\n"
        f"Shape: {df.shape}\n"
        f"Dtypes:\n{df.dtypes.to_string()}\n\n"
        f"First 5 rows:\n{df.head().to_string()}\n\n"
        f"Basic stats:\n{df.describe(include='all').to_string()}"
    )

    system_msg = {"role": "system", "content": _CODE_INTERPRETER_SYSTEM.format(dataset_info=dataset_info)}

    # Build multi-turn messages
    messages = [system_msg]
    for h in req.history:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": req.question})

    # Step 1: Ask LLM to generate analysis (may include code)
    llm_response = await chat_completion(messages)

    # Step 2: Extract and execute any Python code blocks
    import re
    code_blocks = re.findall(r"```python\s*\n(.*?)```", llm_response, re.DOTALL)

    exec_results = []
    if code_blocks:
        for code_block in code_blocks:
            result = _safe_exec_pandas(code_block.strip(), df)
            exec_results.append(result)

    # Step 3: If code was executed, ask LLM to summarize with actual results
    if exec_results:
        exec_output = "\n---\n".join(exec_results)
        # Build final answer with code + execution result
        final_answer = llm_response + "\n\n**Execution Result:**\n```\n" + exec_output + "\n```"

        # Optional: ask LLM to provide a clean summary based on execution results
        summary_messages = messages + [
            {"role": "assistant", "content": llm_response},
            {"role": "user", "content": f"The code was executed and produced this output:\n```\n{exec_output}\n```\nPlease provide a concise summary of the results in natural language. Use the same language as the user's question."}
        ]
        try:
            summary = await chat_completion(summary_messages)
            final_answer = llm_response + "\n\n**Execution Result:**\n```\n" + exec_output + "\n```\n\n" + summary
        except Exception:
            pass  # Use the un-summarized version

        return {"answer": final_answer, "code": code_blocks, "exec_results": exec_results}
    else:
        return {"answer": llm_response, "code": [], "exec_results": []}


@router.post("/chart")
async def generate_chart(req: ChartRequest):
    """Use AI to generate a matplotlib chart dynamically based on user query and return as base64 PNG."""
    df = _sessions.get(req.session_id)
    if df is None:
        raise HTTPException(404, "Session not found – upload a file first")

    col_info = json.dumps(
        {
            "columns": list(df.columns),
            "dtypes": {c: str(d) for c, d in df.dtypes.items()},
            "shape": list(df.shape),
            "sample_values": {c: df[c].dropna().head(3).tolist() for c in df.columns},
        },
        ensure_ascii=False,
    )

    messages = [
        {"role": "system", "content": (
            "You are a Python data-visualization expert. "
            "Given dataset column info and the user's instruction, "
            "write ONLY executable Python code that uses `df` (a pandas DataFrame already in scope) "
            "and matplotlib to draw the chart.\n\n"
            "Important rules:\n"
            "- `plt` (matplotlib.pyplot), `pd` (pandas), `np` (numpy) are already imported.\n"
            "- Do NOT create a new figure with plt.figure() or plt.subplots(). "
            "Use the existing `fig` and `ax` variables directly.\n"
            "- Plot on `ax`, e.g. `ax.bar(...)`, `ax.plot(...)`, `df.plot(ax=ax, ...)`.\n"
            "- Apply dark theme: ax.set_facecolor('#1e293b'), fig.set_facecolor('#0f172a'), "
            "use white/light colors for text and bright colors for data.\n"
            "- Set title, labels via `ax.set_title(...)`, `ax.set_xlabel(...)`, etc.\n"
            "- Use color='white' or color='#94a3b8' for axis labels and title.\n"
            "- For tick params: ax.tick_params(colors='#94a3b8')\n"
            "- For spines: [s.set_color('#334155') for s in ax.spines.values()]\n"
            "- End with `plt.tight_layout()`.\n"
            "- Do NOT call `plt.show()` or `plt.savefig()`.\n"
            "- For radar charts, use matplotlib polar projection: create with "
            "`ax.remove()` then `ax = fig.add_subplot(111, polar=True)`.\n"
            "- Chinese text is supported, feel free to use Chinese labels and titles.\n"
            "- Output ONLY the code, no markdown fences, no explanation."
        )},
        {"role": "user", "content": f"Columns info:\n{col_info}\n\nInstruction: {req.instruction}"},
    ]
    code = await chat_completion(messages, temperature=0.2)

    # Clean potential markdown fences
    code = code.strip()
    if code.startswith("```"):
        code = "\n".join(code.split("\n")[1:])
    if code.endswith("```"):
        code = code[:-3]
    code = code.strip()

    # Close all pre-existing figures to avoid leaks
    plt.close("all")

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.set_facecolor("#0f172a")
    ax.set_facecolor("#1e293b")

    import builtins
    import numpy as np
    exec_globals = {"__builtins__": builtins, "np": np, "pd": pd, "plt": plt}
    exec_locals = {"df": df, "ax": ax, "fig": fig}
    try:
        exec(code, exec_globals, exec_locals)
    except Exception as e:
        plt.close("all")
        raise HTTPException(400, f"Chart generation failed: {e}\n\nGenerated code:\n{code}")

    current_fig = plt.gcf()
    img_b64 = _render_figure_to_b64(current_fig)

    # Save to history
    record = _save_chart_to_history(req.session_id, img_b64, code, req.instruction, "ai-custom")

    return {"image": img_b64, "code": code, "chart_id": record["id"]}


@router.post("/chart/preset")
async def generate_preset_chart(req: PresetChartRequest):
    """Generate a preset chart type (bar, line, pie, radar, scatter, heatmap)."""
    df = _sessions.get(req.session_id)
    if df is None:
        raise HTTPException(404, "Session not found – upload a file first")

    numeric_cols = list(df.select_dtypes(include=["number"]).columns)
    categorical_cols = list(df.select_dtypes(include=["object", "category"]).columns)

    x_col = req.x_column
    y_col = req.y_column

    # Auto-select columns if not specified
    if not x_col and categorical_cols:
        x_col = categorical_cols[0]
    elif not x_col and len(df.columns) > 0:
        x_col = df.columns[0]

    if not y_col and numeric_cols:
        y_col = numeric_cols[0]
    elif not y_col and len(df.columns) > 1:
        y_col = df.columns[1]

    plt.close("all")

    chart_type = req.chart_type.lower()
    title = req.title or f"{chart_type.capitalize()} Chart"
    colors = ["#818cf8", "#34d399", "#f472b6", "#fbbf24", "#22d3ee", "#fb923c", "#a78bfa", "#f87171"]

    try:
        if chart_type == "radar":
            fig = plt.figure(figsize=(8, 8))
            fig.set_facecolor("#0f172a")
            ax = fig.add_subplot(111, polar=True)
            ax.set_facecolor("#1e293b")

            # Use user-selected columns or fall back to all numeric
            selected = req.columns if req.columns and len(req.columns) >= 2 else numeric_cols[:8]
            # Filter to only valid numeric columns
            selected = [c for c in selected if c in numeric_cols]
            if selected and len(selected) >= 2:
                categories = selected
                values = df[categories].mean().values.tolist()
                # Normalize to 0-1
                max_val = max(values) if max(values) > 0 else 1
                values_norm = [v / max_val for v in values]
                values_norm.append(values_norm[0])  # close the polygon

                import numpy as np
                angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
                angles.append(angles[0])

                ax.plot(angles, values_norm, 'o-', color="#818cf8", linewidth=2)
                ax.fill(angles, values_norm, alpha=0.25, color="#818cf8")
                ax.set_xticks(angles[:-1])
                ax.set_xticklabels(categories, color="#94a3b8", fontsize=10)
                ax.tick_params(colors="#94a3b8")
                ax.set_title(title, fontsize=14, fontweight="bold", color="white", pad=20)
                ax.spines["polar"].set_color("#334155")
                ax.set_yticklabels([])
            else:
                raise HTTPException(400, "Radar chart requires numeric columns")

        elif chart_type == "pie":
            fig, ax = plt.subplots(figsize=(8, 8))
            fig.set_facecolor("#0f172a")
            ax.set_facecolor("#1e293b")

            if x_col and y_col:
                data = df.groupby(x_col)[y_col].sum().head(8)
            elif x_col:
                data = df[x_col].value_counts().head(8)
            else:
                raise HTTPException(400, "Pie chart requires at least one column")

            wedges, texts, autotexts = ax.pie(
                data.values, labels=data.index, autopct="%1.1f%%",
                colors=colors[:len(data)], textprops={"color": "white", "fontsize": 10}
            )
            for t in autotexts:
                t.set_color("white")
            ax.set_title(title, fontsize=14, fontweight="bold", color="white", pad=12)

        elif chart_type == "heatmap":
            fig, ax = plt.subplots(figsize=(10, 8))
            fig.set_facecolor("#0f172a")
            ax.set_facecolor("#1e293b")

            # Use user-selected columns or fall back to all numeric
            heatmap_cols = req.columns if req.columns and len(req.columns) >= 2 else numeric_cols
            heatmap_cols = [c for c in heatmap_cols if c in numeric_cols]
            corr = df[heatmap_cols].corr() if len(heatmap_cols) > 1 else df.head(10)
            import numpy as np
            im = ax.imshow(corr.values, cmap="coolwarm", aspect="auto")
            ax.set_xticks(range(len(corr.columns)))
            ax.set_yticks(range(len(corr.columns)))
            ax.set_xticklabels(corr.columns, rotation=45, ha="right", color="#94a3b8", fontsize=9)
            ax.set_yticklabels(corr.columns, color="#94a3b8", fontsize=9)
            fig.colorbar(im, ax=ax)
            _style_ax(ax, title)

        elif chart_type == "scatter":
            fig, ax = plt.subplots(figsize=(10, 6))
            fig.set_facecolor("#0f172a")
            ax.set_facecolor("#1e293b")

            if x_col and y_col:
                ax.scatter(df[x_col], df[y_col], c="#818cf8", alpha=0.6, edgecolors="#4f46e5", s=50)
                ax.set_xlabel(str(x_col), color="#94a3b8")
                ax.set_ylabel(str(y_col), color="#94a3b8")
            else:
                raise HTTPException(400, "Scatter chart requires x and y columns")
            _style_ax(ax, title)

        elif chart_type == "line":
            fig, ax = plt.subplots(figsize=(10, 6))
            fig.set_facecolor("#0f172a")
            ax.set_facecolor("#1e293b")

            if x_col and y_col:
                sorted_df = df.sort_values(x_col)
                ax.plot(sorted_df[x_col], sorted_df[y_col], color="#818cf8", linewidth=2, marker="o", markersize=4)
                ax.fill_between(sorted_df[x_col], sorted_df[y_col], alpha=0.1, color="#818cf8")
                ax.set_xlabel(str(x_col), color="#94a3b8")
                ax.set_ylabel(str(y_col), color="#94a3b8")
            elif y_col:
                ax.plot(df[y_col].values, color="#818cf8", linewidth=2)
                ax.set_ylabel(str(y_col), color="#94a3b8")
            else:
                raise HTTPException(400, "Line chart requires at least y column")
            _style_ax(ax, title)

        else:  # bar (default)
            fig, ax = plt.subplots(figsize=(10, 6))
            fig.set_facecolor("#0f172a")
            ax.set_facecolor("#1e293b")

            if x_col and y_col:
                data = df.groupby(x_col)[y_col].sum().head(15)
                bar_colors = colors * (len(data) // len(colors) + 1)
                ax.bar(range(len(data)), data.values, color=bar_colors[:len(data)], edgecolor="none")
                ax.set_xticks(range(len(data)))
                ax.set_xticklabels(data.index, rotation=45, ha="right")
                ax.set_xlabel(str(x_col), color="#94a3b8")
                ax.set_ylabel(str(y_col), color="#94a3b8")
            elif y_col:
                ax.bar(range(len(df.head(20))), df[y_col].head(20), color="#818cf8")
                ax.set_ylabel(str(y_col), color="#94a3b8")
            else:
                raise HTTPException(400, "Bar chart requires at least y column")
            _style_ax(ax, title)

        plt.tight_layout()
        img_b64 = _render_figure_to_b64(fig)

        code_desc = f"Preset {chart_type} chart: x={x_col}, y={y_col}"
        record = _save_chart_to_history(req.session_id, img_b64, code_desc, title, chart_type)

        return {"image": img_b64, "code": code_desc, "chart_id": record["id"], "chart_type": chart_type}

    except HTTPException:
        raise
    except Exception as e:
        plt.close("all")
        raise HTTPException(400, f"Preset chart generation failed: {e}")


@router.get("/chart/history/{session_id}")
async def get_chart_history(session_id: str):
    """Get all generated charts for a session (for history dropdown)."""
    history = _chart_history.get(session_id, [])
    # Return metadata without full image to keep response small
    return [
        {
            "id": h["id"],
            "instruction": h["instruction"],
            "chart_type": h["chart_type"],
            "timestamp": h["timestamp"],
        }
        for h in reversed(history)  # newest first
    ]


@router.get("/chart/history/{session_id}/{chart_id}")
async def get_chart_by_id(session_id: str, chart_id: str):
    """Get a specific chart from history by ID."""
    history = _chart_history.get(session_id, [])
    for h in history:
        if h["id"] == chart_id:
            return h
    raise HTTPException(404, "Chart not found")


@router.get("/chart/export/{session_id}/{chart_id}")
async def export_chart(session_id: str, chart_id: str):
    """Export a chart as a downloadable PNG file."""
    history = _chart_history.get(session_id, [])
    for h in history:
        if h["id"] == chart_id:
            img_data = h["image"]
            # Remove data URI prefix
            if "," in img_data:
                img_data = img_data.split(",", 1)[1]
            raw = base64.b64decode(img_data)
            return Response(
                content=raw,
                media_type="image/png",
                headers={"Content-Disposition": f"attachment; filename=chart_{chart_id}.png"},
            )
    raise HTTPException(404, "Chart not found")


@router.post("/chart/suggest")
async def suggest_charts(req: AnalyzeRequest):
    """Suggest chart types based on the data shape. Uses session_id from AnalyzeRequest."""
    df = _sessions.get(req.session_id)
    if df is None:
        raise HTTPException(404, "Session not found")

    numeric_cols = list(df.select_dtypes(include=["number"]).columns)
    categorical_cols = list(df.select_dtypes(include=["object", "category"]).columns)
    suggestions = []

    if categorical_cols and numeric_cols:
        suggestions.append({
            "chart_type": "bar",
            "label": "柱状图",
            "description": f"{categorical_cols[0]} vs {numeric_cols[0]}",
            "x_column": categorical_cols[0],
            "y_column": numeric_cols[0],
        })
        suggestions.append({
            "chart_type": "pie",
            "label": "饼图",
            "description": f"{categorical_cols[0]} distribution of {numeric_cols[0]}",
            "x_column": categorical_cols[0],
            "y_column": numeric_cols[0],
        })

    if len(numeric_cols) >= 2:
        suggestions.append({
            "chart_type": "scatter",
            "label": "散点图",
            "description": f"{numeric_cols[0]} vs {numeric_cols[1]}",
            "x_column": numeric_cols[0],
            "y_column": numeric_cols[1],
        })
        suggestions.append({
            "chart_type": "line",
            "label": "折线图",
            "description": f"{numeric_cols[0]} trend",
            "x_column": numeric_cols[0],
            "y_column": numeric_cols[1],
        })

    if len(numeric_cols) >= 3:
        suggestions.append({
            "chart_type": "radar",
            "label": "雷达图",
            "description": f"Multi-metric comparison across {len(numeric_cols)} metrics",
            "x_column": None,
            "y_column": None,
        })
        suggestions.append({
            "chart_type": "heatmap",
            "label": "热力图",
            "description": f"Correlation heatmap of {len(numeric_cols)} numeric columns",
            "x_column": None,
            "y_column": None,
        })

    return {"suggestions": suggestions}


# Chat handler (called by platform router)
async def handle_chat(messages: list[dict], *, config: Optional[dict] = None) -> str:
    system_msg = {
        "role": "system",
        "content": "You are an Excel data analysis assistant. Help users understand and analyze their data. Reply in the same language the user uses.",
    }
    return await chat_completion([system_msg] + messages)
