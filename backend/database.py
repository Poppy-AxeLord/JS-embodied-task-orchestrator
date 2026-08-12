# -*- coding: utf-8 -*-
"""
数据库模块（技术契约 SPEC §2）
------------------------------------------------------------------
- 使用 Python 标准库 sqlite3（不引入任何 ORM），保证 Apple Silicon 纯 Python 零编译依赖。
- 数据库文件：backend/data/app.db（运行时自动生成，不应提交版本库）。
- 提供：
    get_conn()    返回带 row_factory=sqlite3.Row 的连接（结果可按列名取值）
    init_db()     按 SPEC §2 建 tasks / task_steps / skills / feedback / settings 五张表
    query_all()   查询多行
    query_one()   查询单行
    execute()     执行写操作（INSERT/UPDATE/DELETE），返回 lastrowid
    seed_skills() 从 data/demo_data.json 读取 skills 写入 skills 表

约定（SPEC §2 结尾）：
  - 读 JSON 字段处需 json.loads；写处需 json.dumps(ensure_ascii=False)。
"""

import json
import sqlite3
from pathlib import Path

from config import settings

# 数据库与示例数据文件路径，统一从 config 获取
DB_PATH: Path = settings.DB_PATH
DATA_DIR: Path = settings.DATA_DIR
DEMO_DATA_PATH: Path = settings.DEMO_DATA_PATH


# ------------------------------------------------------------------
# 连接获取
# ------------------------------------------------------------------
def get_conn() -> sqlite3.Connection:
    """
    返回一个 SQLite 连接：
      - 确保 data 目录存在；
      - 设置 row_factory=sqlite3.Row，使查询结果支持 row["列名"] 访问；
      - 开启外键约束（task_steps.task_id → tasks.id）。
    调用方负责 commit/close（写操作的辅助函数已封装好）。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ------------------------------------------------------------------
# 建表
# ------------------------------------------------------------------
# 五张表的 DDL，字段与 SPEC §2 完全一致。
_SCHEMA_SQL = """
-- 任务主表
CREATE TABLE IF NOT EXISTS tasks (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    instruction        TEXT,      -- 用户原始自然语言指令
    task_type          TEXT,      -- 整理/分拣/取送/巡检/养护/排序/检查
    strategy           TEXT,      -- "llm" 或 "rule"
    goal               TEXT,      -- 任务目标
    constraints        TEXT,      -- JSON 字符串数组（约束条件）
    steps              TEXT,      -- JSON：step 对象数组（见 SPEC §3）
    exception_handling TEXT,      -- JSON 字符串数组（异常处理）
    status             TEXT,      -- "success" / "failed" / "pending"
    success            INTEGER,   -- 0/1
    failure_category   TEXT,      -- 5 类之一（中文）或 NULL
    failure_reason     TEXT,      -- 具体失败原因文字或 NULL
    total_duration_ms  INTEGER,   -- 总耗时毫秒
    step_count         INTEGER,   -- 步骤数
    retry_count        INTEGER,   -- 重试次数
    rating             INTEGER,   -- 1-5 或 NULL
    feedback_text      TEXT,      -- 用户反馈意见或 NULL
    needs_review       INTEGER,   -- 0/1 是否需人工介入（Human-in-the-loop）
    is_golden          INTEGER,   -- 0/1 是否优质样本
    created_at         TEXT       -- ISO 时间
);

-- 执行步骤日志表（逐步落库，便于历史详情回放）
CREATE TABLE IF NOT EXISTS task_steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER,   -- 外键 → tasks.id
    step_index  INTEGER,   -- 从 1 开始
    skill_code  TEXT,      -- 原子技能英文编码（见 SPEC §4）
    skill_name  TEXT,      -- 中文名
    params      TEXT,      -- JSON
    status      TEXT,      -- "success" / "failed"（落库为最终态）
    duration_ms INTEGER,   -- 该步耗时
    error       TEXT,      -- 失败时错误信息，否则 NULL
    created_at  TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

-- 技能表
CREATE TABLE IF NOT EXISTS skills (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT UNIQUE,  -- 英文编码，如 "MoveTo"
    name         TEXT,         -- 中文名
    category     TEXT,         -- 移动类/操作类/感知类/逻辑类/控制类
    icon         TEXT,         -- emoji
    description  TEXT,
    input_params TEXT,         -- JSON 数组 [{name,type,desc}]
    output       TEXT,         -- JSON {type,desc}
    enabled      INTEGER       -- 0/1
);

-- 反馈表
CREATE TABLE IF NOT EXISTS feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER,
    rating          INTEGER,
    comment         TEXT,
    corrected_steps TEXT,   -- JSON
    created_at      TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

-- 配置表（键值对，value 存 JSON 字符串）
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def init_db() -> None:
    """按 SPEC §2 创建全部表（IF NOT EXISTS，可重复调用）。"""
    conn = get_conn()
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------
# 查询 / 写入辅助函数
# ------------------------------------------------------------------
def query_all(sql: str, params: tuple = ()) -> list[dict]:
    """执行查询，返回 [dict, ...]（每行用列名为键）。"""
    conn = get_conn()
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def query_one(sql: str, params: tuple = ()) -> dict | None:
    """执行查询，返回单行 dict 或 None。"""
    conn = get_conn()
    try:
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()) -> int:
    """
    执行写操作（INSERT/UPDATE/DELETE）并提交。
    返回 lastrowid（INSERT 时为新行 id；其它操作下该值意义有限）。
    """
    conn = get_conn()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ------------------------------------------------------------------
# 技能种子数据
# ------------------------------------------------------------------
def seed_skills() -> int:
    """
    从 data/demo_data.json 读取 skills 列表，批量写入 skills 表。
    - JSON 中每个 skill 形如 SPEC §2 skills 表字段：
        {code, name, category, icon, description, input_params:[...], output:{...}, enabled}
    - input_params / output 在 JSON 里是对象/数组，落库时用
      json.dumps(ensure_ascii=False) 转为字符串。
    - 仅在 skills 表为空时调用（由 main.py 启动流程控制）。
    返回成功写入的技能条数。
    """
    if not DEMO_DATA_PATH.exists():
        # 示例数据文件缺失时不抛错，返回 0，避免影响启动。
        print(f"[警告] 未找到示例数据文件：{DEMO_DATA_PATH}，跳过技能初始化。")
        return 0

    with open(DEMO_DATA_PATH, "r", encoding="utf-8") as f:
        demo = json.load(f)

    skills = demo.get("skills", [])
    if not skills:
        print("[警告] demo_data.json 中没有 skills 字段或为空，跳过技能初始化。")
        return 0

    conn = get_conn()
    try:
        inserted = 0
        for s in skills:
            # input_params / output 可能已是对象，统一序列化为 JSON 字符串
            input_params = s.get("input_params", [])
            output = s.get("output", {})
            input_params_str = (
                input_params
                if isinstance(input_params, str)
                else json.dumps(input_params, ensure_ascii=False)
            )
            output_str = (
                output
                if isinstance(output, str)
                else json.dumps(output, ensure_ascii=False)
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO skills
                    (code, name, category, icon, description, input_params, output, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    s.get("code"),
                    s.get("name"),
                    s.get("category"),
                    s.get("icon"),
                    s.get("description"),
                    input_params_str,
                    output_str,
                    int(s.get("enabled", 1)),
                ),
            )
            inserted += 1
        conn.commit()
        return inserted
    finally:
        conn.close()


def count_rows(table: str) -> int:
    """统计某表行数（仅用于启动流程判断是否为空，表名为内部常量，无注入风险）。"""
    row = query_one(f"SELECT COUNT(*) AS c FROM {table}")
    return int(row["c"]) if row else 0
