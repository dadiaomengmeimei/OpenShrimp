"""
Database Distribution Analyzer
==============================
A standalone web application for analyzing database data distributions.

Upload a database configuration file, connect to your database, and visualize
data distributions across all columns with intelligent chart generation.

Supported databases:
- MySQL (via aiomysql)
- PostgreSQL (via asyncpg)
- SQLite (via aiosqlite)
"""

__version__ = "1.0.0"
__author__ = "AppShrimp AI Platform"