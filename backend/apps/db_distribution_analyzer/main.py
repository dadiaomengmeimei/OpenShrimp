"""
Database Distribution Analyzer - Web Application
===============================================
A standalone web app that analyzes database distributions.
Upload a DB config file, connect to your database, and visualize data distributions.
"""

import json
import asyncio
from pathlib import Path
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from collections import Counter
import traceback

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from backend.core.file_toolkit import (
    register_download,
    get_download_url,
    make_download_link,
    make_image_embed,
)
from backend.core.llm_service import chat_completion

# Router setup
router = APIRouter(prefix="/api/apps/db_distribution_analyzer", tags=["Database Distribution Analyzer"])

# ============================================================================
# Pydantic Models
# ============================================================================

class DBConfig(BaseModel):
    db_type: str  # mysql, postgresql, sqlite, mssql
    host: Optional[str] = None
    port: Optional[int] = None
    database: str
    username: Optional[str] = None
    password: Optional[str] = None
    connection_string: Optional[str] = None

class ColumnInfo(BaseModel):
    name: str
    data_type: str
    sample_values: List[Any]
    null_count: int
    unique_count: int
    total_count: int

class TableInfo(BaseModel):
    name: str
    row_count: int
    columns: List[ColumnInfo]

class DistributionResult(BaseModel):
    column_name: str
    chart_type: str  # bar, pie, line, histogram
    labels: List[str]
    values: List[int]
    chart_token: Optional[str] = None
    preview_url: Optional[str] = None

# ============================================================================
# Database Connectors
# ============================================================================

class DatabaseConnector:
    """Base class for database connectors."""
    
    def __init__(self, config: DBConfig):
        self.config = config
        self.connection = None
    
    async def connect(self):
        raise NotImplementedError
    
    async def disconnect(self):
        raise NotImplementedError
    
    async def get_tables(self) -> List[str]:
        raise NotImplementedError
    
    async def get_columns(self, table: str) -> List[Dict]:
        raise NotImplementedError
    
    async def get_column_data(self, table: str, column: str, limit: int = 1000) -> List[Any]:
        raise NotImplementedError
    
    async def get_row_count(self, table: str) -> int:
        raise NotImplementedError


class MySQLConnector(DatabaseConnector):
    """MySQL database connector."""
    
    async def connect(self):
        try:
            import aiomysql
            self.connection = await aiomysql.connect(
                host=self.config.host,
                port=self.config.port or 3306,
                user=self.config.username,
                password=self.config.password,
                db=self.config.database,
            )
            print(f"[DB Analyzer] MySQL connected to {self.config.host}:{self.config.port}")
        except Exception as e:
            print(f"[DB Analyzer] MySQL connection error: {e}")
            raise HTTPException(status_code=400, detail=f"MySQL connection failed: {str(e)}")
    
    async def disconnect(self):
        if self.connection:
            self.connection.close()
    
    async def get_tables(self) -> List[str]:
        async with self.connection.cursor() as cur:
            await cur.execute("SHOW TABLES")
            tables = await cur.fetchall()
            return [t[0] for t in tables]
    
    async def get_columns(self, table: str) -> List[Dict]:
        async with self.connection.cursor() as cur:
            await cur.execute(
                "SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_COMMENT "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                "ORDER BY ORDINAL_POSITION",
                (self.config.database, table)
            )
            columns = await cur.fetchall()
            return [{"name": c[0], "type": c[1], "comment": c[2] or ""} for c in columns]
    
    async def get_column_data(self, table: str, column: str, limit: int = 1000) -> List[Any]:
        async with self.connection.cursor() as cur:
            await cur.execute(f"SELECT `{column}` FROM `{table}` LIMIT {limit}")
            rows = await cur.fetchall()
            return [r[0] for r in rows if r[0] is not None]
    
    async def get_row_count(self, table: str) -> int:
        async with self.connection.cursor() as cur:
            await cur.execute(f"SELECT COUNT(*) FROM `{table}`")
            result = await cur.fetchone()
            return result[0] if result else 0


class PostgreSQLConnector(DatabaseConnector):
    """PostgreSQL database connector."""
    
    async def connect(self):
        try:
            import asyncpg
            dsn = f"postgresql://{self.config.username}:{self.config.password}@{self.config.host}:{self.config.port or 5432}/{self.config.database}"
            self.connection = await asyncpg.connect(dsn)
            print(f"[DB Analyzer] PostgreSQL connected to {self.config.host}")
        except Exception as e:
            print(f"[DB Analyzer] PostgreSQL connection error: {e}")
            raise HTTPException(status_code=400, detail=f"PostgreSQL connection failed: {str(e)}")
    
    async def disconnect(self):
        if self.connection:
            await self.connection.close()
    
    async def get_tables(self) -> List[str]:
        rows = await self.connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        return [r["tablename"] for r in rows]
    
    async def get_columns(self, table: str) -> List[Dict]:
        rows = await self.connection.fetch(
            """
            SELECT c.column_name, c.data_type,
                   COALESCE(pgd.description, '') AS column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_catalog.pg_statio_all_tables st
                ON c.table_schema = st.schemaname AND c.table_name = st.relname
            LEFT JOIN pg_catalog.pg_description pgd
                ON pgd.objoid = st.relid AND pgd.objsubid = c.ordinal_position
            WHERE c.table_name = $1
            ORDER BY c.ordinal_position
            """,
            table
        )
        return [{"name": r["column_name"], "type": r["data_type"], "comment": r["column_comment"]} for r in rows]
    
    async def get_column_data(self, table: str, column: str, limit: int = 1000) -> List[Any]:
        rows = await self.connection.fetch(
            f'SELECT "{column}" FROM "{table}" LIMIT {limit}'
        )
        return [r[column] for r in rows if r[column] is not None]
    
    async def get_row_count(self, table: str) -> int:
        result = await self.connection.fetchval(f'SELECT COUNT(*) FROM "{table}"')
        return result or 0


class SQLiteConnector(DatabaseConnector):
    """SQLite database connector."""
    
    async def connect(self):
        try:
            import aiosqlite
            db_path = self.config.database
            if not db_path.endswith('.db') and not db_path.endswith('.sqlite'):
                db_path = db_path + '.db'
            self.connection = await aiosqlite.connect(db_path)
            print(f"[DB Analyzer] SQLite connected to {db_path}")
        except Exception as e:
            print(f"[DB Analyzer] SQLite connection error: {e}")
            raise HTTPException(status_code=400, detail=f"SQLite connection failed: {str(e)}")
    
    async def disconnect(self):
        if self.connection:
            await self.connection.close()
    
    async def get_tables(self) -> List[str]:
        async with self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]
    
    async def get_columns(self, table: str) -> List[Dict]:
        async with self.connection.execute(f"PRAGMA table_info({table})") as cursor:
            rows = await cursor.fetchall()
            return [{"name": r[1], "type": r[2], "comment": ""} for r in rows]
    
    async def get_column_data(self, table: str, column: str, limit: int = 1000) -> List[Any]:
        async with self.connection.execute(
            f'SELECT "{column}" FROM "{table}" LIMIT ?', (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows if r[0] is not None]
    
    async def get_row_count(self, table: str) -> int:
        async with self.connection.execute(
            f'SELECT COUNT(*) FROM "{table}"'
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else 0


def create_connector(config: DBConfig) -> DatabaseConnector:
    """Factory function to create the appropriate connector."""
    db_type = config.db_type.lower()
    if db_type == "mysql":
        return MySQLConnector(config)
    elif db_type in ["postgresql", "postgres"]:
        return PostgreSQLConnector(config)
    elif db_type == "sqlite":
        return SQLiteConnector(config)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported database type: {config.db_type}")


# ============================================================================
# Distribution Analyzer
# ============================================================================

class DistributionAnalyzer:
    """Analyzes data distributions and generates insights."""
    
    @staticmethod
    def is_date_column(column_name: str, data_type: str) -> bool:
        """Check if a column is likely a date/datetime column."""
        date_keywords = ['date', 'time', 'created', 'updated', 'timestamp', 'birthday', 'hire']
        date_types = ['date', 'datetime', 'timestamp', 'timestamptz']
        return (
            any(keyword in column_name.lower() for keyword in date_keywords) or
            any(dtype in data_type.lower() for dtype in date_types)
        )
    
    @staticmethod
    def is_numeric_column(data_type: str) -> bool:
        """Check if a column is numeric."""
        numeric_types = ['int', 'float', 'double', 'decimal', 'numeric', 'real', 'bigint', 'smallint']
        return any(dtype in data_type.lower() for dtype in numeric_types)
    
    @staticmethod
    def is_category_column(column_name: str, data_type: str, unique_ratio: float) -> bool:
        """Check if a column is likely a category column."""
        category_keywords = ['status', 'type', 'category', 'gender', 'role', 'level', 'department', 'region', 'city', 'country']
        is_low_cardinality = unique_ratio < 0.3  # Less than 30% unique values
        return (
            any(keyword in column_name.lower() for keyword in category_keywords) or
            is_low_cardinality
        )
    
    @staticmethod
    def analyze_date_distribution(values: List[Any]) -> Dict:
        """Analyze distribution of date values."""
        # Convert to years for distribution
        years = []
        for v in values:
            try:
                if isinstance(v, (datetime, date)):
                    years.append(v.year)
                elif isinstance(v, str):
                    # Try to parse year from string
                    year = int(v[:4]) if len(v) >= 4 and v[:4].isdigit() else None
                    if year and 1900 < year < 2100:
                        years.append(year)
            except:
                continue
        
        if not years:
            return None
        
        year_counts = Counter(years)
        sorted_years = sorted(year_counts.items())
        
        return {
            "chart_type": "bar",
            "labels": [str(y[0]) for y in sorted_years],
            "values": [y[1] for y in sorted_years],
            "title": f"按年份分布"
        }
    
    @staticmethod
    def analyze_numeric_distribution(values: List[Any]) -> Dict:
        """Analyze distribution of numeric values using histogram."""
        numeric_values = []
        for v in values:
            try:
                numeric_values.append(float(v))
            except:
                continue
        
        if len(numeric_values) < 2:
            return None
        
        # Create histogram bins
        min_val = min(numeric_values)
        max_val = max(numeric_values)
        
        if min_val == max_val:
            return None
        
        # Determine number of bins
        num_bins = min(20, max(5, len(numeric_values) // 10))
        bin_width = (max_val - min_val) / num_bins
        
        bins = [0] * num_bins
        for v in numeric_values:
            bin_idx = min(int((v - min_val) / bin_width), num_bins - 1)
            bins[bin_idx] += 1
        
        labels = [f"{min_val + i * bin_width:.1f}" for i in range(num_bins)]
        
        return {
            "chart_type": "histogram",
            "labels": labels,
            "values": bins,
            "title": f"数值分布 (范围: {min_val:.1f} - {max_val:.1f})"
        }
    
    @staticmethod
    def analyze_category_distribution(values: List[Any]) -> Dict:
        """Analyze distribution of categorical values."""
        if not values:
            return None
        
        value_counts = Counter(str(v) for v in values if v is not None)
        
        # Limit to top categories
        top_counts = value_counts.most_common(15)
        
        return {
            "chart_type": "pie" if len(top_counts) <= 8 else "bar",
            "labels": [item[0][:30] for item in top_counts],  # Truncate long labels
            "values": [item[1] for item in top_counts],
            "title": f"类别分布 (Top {len(top_counts)})"
        }
    
    @staticmethod
    def analyze_column(column_name: str, data_type: str, values: List[Any], total_count: int) -> Optional[DistributionResult]:
        """Analyze a column and determine the best distribution visualization."""
        if not values:
            return None
        
        unique_count = len(set(str(v) for v in values))
        unique_ratio = unique_count / len(values) if values else 1
        
        result_data = None
        
        # Determine analysis type
        if DistributionAnalyzer.is_date_column(column_name, data_type):
            result_data = DistributionAnalyzer.analyze_date_distribution(values)
        elif DistributionAnalyzer.is_numeric_column(data_type):
            # For numeric with low cardinality, treat as category
            if unique_ratio < 0.1 and unique_count <= 20:
                result_data = DistributionAnalyzer.analyze_category_distribution(values)
            else:
                result_data = DistributionAnalyzer.analyze_numeric_distribution(values)
        elif DistributionAnalyzer.is_category_column(column_name, data_type, unique_ratio):
            result_data = DistributionAnalyzer.analyze_category_distribution(values)
        else:
            # Default: treat as category if low cardinality, else skip
            if unique_ratio < 0.3 and unique_count <= 50:
                result_data = DistributionAnalyzer.analyze_category_distribution(values)
        
        if result_data:
            return DistributionResult(
                column_name=column_name,
                chart_type=result_data["chart_type"],
                labels=result_data["labels"],
                values=result_data["values"],
            )
        
        return None


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/upload-config")
async def upload_config(file: UploadFile = File(...)):
    """Upload and parse database configuration file."""
    print(f"[DB Analyzer] Uploading config file: {file.filename}")
    
    try:
        content = await file.read()
        content_str = content.decode('utf-8')
        
        # Try to parse as JSON
        try:
            config_data = json.loads(content_str)
        except json.JSONDecodeError:
            # Try to parse as key=value pairs
            config_data = {}
            for line in content_str.split('\n'):
                if '=' in line and not line.strip().startswith('#'):
                    key, value = line.split('=', 1)
                    config_data[key.strip()] = value.strip().strip('"\'')
        
        # Validate and normalize config
        db_config = DBConfig(
            db_type=config_data.get('db_type', config_data.get('type', 'mysql')),
            host=config_data.get('host'),
            port=int(config_data['port']) if 'port' in config_data and config_data['port'] else None,
            database=config_data.get('database', config_data.get('db', config_data.get('dbname'))),
            username=config_data.get('username', config_data.get('user')),
            password=config_data.get('password', config_data.get('pass')),
            connection_string=config_data.get('connection_string'),
        )
        
        print(f"[DB Analyzer] Config parsed successfully: {db_config.db_type}://{db_config.host}/{db_config.database}")
        
        return {
            "success": True,
            "config": db_config.dict(),
            "message": "配置上传成功"
        }
    
    except Exception as e:
        print(f"[DB Analyzer] Config upload error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"配置解析失败: {str(e)}")


@router.post("/connect")
async def connect_database(config: DBConfig):
    """Test database connection."""
    # Trim whitespace from string fields to avoid connection errors
    if config.host:
        config.host = config.host.strip()
    if config.username:
        config.username = config.username.strip()
    if config.password:
        config.password = config.password.strip()
    if config.database:
        config.database = config.database.strip()
    if config.connection_string:
        config.connection_string = config.connection_string.strip()
    
    print(f"[DB Analyzer] Connecting to {config.db_type} database: {config.database}")
    
    connector = create_connector(config)
    
    try:
        await connector.connect()
        tables = await connector.get_tables()
        await connector.disconnect()
        
        print(f"[DB Analyzer] Connection successful. Found {len(tables)} tables")
        
        return {
            "success": True,
            "tables": tables,
            "message": f"连接成功！发现 {len(tables)} 个数据表"
        }
    except Exception as e:
        print(f"[DB Analyzer] Connection error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/analyze-table/{table_name}")
async def analyze_table(table_name: str, config: DBConfig):
    """Analyze a specific table and generate distribution charts."""
    # Trim whitespace from string fields
    if config.host:
        config.host = config.host.strip()
    if config.username:
        config.username = config.username.strip()
    if config.password:
        config.password = config.password.strip()
    if config.database:
        config.database = config.database.strip()
    if config.connection_string:
        config.connection_string = config.connection_string.strip()
    
    print(f"[DB Analyzer] Analyzing table: {table_name}")
    
    connector = create_connector(config)
    analyzer = DistributionAnalyzer()
    
    try:
        await connector.connect()
        
        # Get table info
        row_count = await connector.get_row_count(table_name)
        columns = await connector.get_columns(table_name)
        
        print(f"[DB Analyzer] Table {table_name}: {row_count} rows, {len(columns)} columns")
        
        results = []
        column_meta = []  # Metadata for all columns (for dashboard)
        
        for col in columns:
            col_name = col["name"]
            col_type = col["type"]
            col_comment = col.get("comment", "") or ""
            
            try:
                # Get sample data
                values = await connector.get_column_data(table_name, col_name, limit=1000)
                
                null_count = row_count - len(values) if row_count > 0 else 0
                unique_count = len(set(str(v) for v in values)) if values else 0
                
                # Collect column metadata
                col_meta = {
                    "name": col_name,
                    "comment": col_comment,
                    "type": col_type,
                    "total_count": row_count,
                    "null_count": null_count,
                    "unique_count": unique_count,
                    "sample_values": [str(v) for v in values[:5]] if values else [],
                    "fill_rate": round((1 - null_count / row_count) * 100, 1) if row_count > 0 else 0,
                }
                column_meta.append(col_meta)
                
                if not values:
                    continue
                
                # Analyze distribution
                distribution = analyzer.analyze_column(col_name, col_type, values, row_count)
                
                if distribution and len(distribution.labels) > 0:
                    results.append({
                        "column_name": distribution.column_name,
                        "comment": col_comment,
                        "chart_type": distribution.chart_type,
                        "labels": distribution.labels,
                        "values": distribution.values,
                    })
                    print(f"[DB Analyzer] Generated distribution for {col_name}: {distribution.chart_type}")
            
            except Exception as e:
                print(f"[DB Analyzer] Error analyzing column {col_name}: {e}")
                continue
        
        await connector.disconnect()
        
        # Generate AI insights
        insights = await generate_insights(table_name, columns, results)
        
        return {
            "success": True,
            "table_name": table_name,
            "row_count": row_count,
            "column_count": len(columns),
            "columns": column_meta,
            "distributions": results,
            "insights": insights,
            "message": f"分析完成！生成 {len(results)} 个分布图表"
        }
    
    except Exception as e:
        print(f"[DB Analyzer] Analysis error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


async def generate_insights(table_name: str, columns: List[Dict], distributions: List[Dict]) -> str:
    """Generate AI-powered insights about the data distributions."""
    try:
        # Prepare summary for LLM
        summary = f"数据表: {table_name}\n"
        summary += f"字段数: {len(columns)}\n"
        summary += "分布情况:\n"
        
        for dist in distributions[:5]:  # Limit to top 5
            summary += f"- {dist['column_name']}: {dist['chart_type']} - {len(dist['labels'])} 个类别/区间\n"
        
        prompt = f"""你是一个数据分析专家。请根据以下数据表分布信息，提供简洁的数据洞察和建议。

{summary}

请用中文提供：
1. 数据特点总结（2-3句话）
2. 潜在的业务洞察（2-3点）
3. 建议进一步分析的方向

保持简洁专业。"""
        
        response = await chat_completion([
            {"role": "system", "content": "你是一个专业的数据分析师，擅长从数据分布中发现业务洞察。"},
            {"role": "user", "content": prompt}
        ])
        
        return response
    
    except Exception as e:
        print(f"[DB Analyzer] Insights generation error: {e}")
        return "洞察生成暂不可用。"


@router.get("/tables")
async def list_tables(config_json: str):
    """List all tables in the database."""
    config = DBConfig.parse_raw(config_json)
    connector = create_connector(config)
    
    try:
        await connector.connect()
        tables = await connector.get_tables()
        await connector.disconnect()
        
        return {"tables": tables}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Web UI Route
# ============================================================================

@router.get("/web", response_class=HTMLResponse)
async def web_ui():
    """Serve the main web application page."""
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# ============================================================================
# Handle Chat (Required by platform)
# ============================================================================

async def handle_chat(messages: list[dict], *, config: dict | None = None) -> str:
    """
    Required by the platform. Since this is a web application,
    redirect users to the web UI.
    """
    return """🗄️ **数据库分布分析器**

这是一个独立的 Web 应用程序，请在新浏览器标签页中打开以使用完整功能。

**功能特点：**
- 📊 上传数据库配置文件，自动连接数据库
- 📈 智能分析各字段数据分布
- 🎨 自动生成可视化图表
- 💡 AI 数据洞察与建议

**支持的数据库：** MySQL, PostgreSQL, SQLite

👉 [点击打开 Web 应用](/api/apps/db_distribution_analyzer/web)

或者在浏览器中直接访问 `/api/apps/db_distribution_analyzer/web`"""


# ============================================================================
# Static file serving
# ============================================================================

# Static files are served automatically by the platform at:
# /api/apps/db_distribution_analyzer/static/{filename}