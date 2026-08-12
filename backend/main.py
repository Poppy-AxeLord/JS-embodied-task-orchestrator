# -*- coding: utf-8 -*-
"""
应用入口（技术契约 SPEC §10 / §8）
------------------------------------------------------------------
运行方式（在 backend 目录下）：
    uvicorn main:app --reload --port 8000

职责：
  1. 创建 FastAPI 应用并启用 CORS（允许前端开发服务器 5173）；
  2. startup 启动事件按 SPEC §10 初始化：
       init_db → 若 skills 表空则 seed_skills → 若 tasks 表空则 seed_demo → 打印中文启动横幅；
  3. 用 include_router 挂载 task/skills/settings/execution/dashboard/feedback 六个路由，
     统一前缀 /api（各 api 文件内部路由不再带 /api）；
  4. 提供 /api/health 健康检查。

说明：各 api 模块均导出名为 `router` 的 APIRouter 实例。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
import database
from database import get_conn, init_db, seed_skills, count_rows

# 六个业务路由（每个文件导出 router）
from api import task, skills, settings as settings_api, execution, dashboard, feedback
# 历史数据种子（mock 模块）
from mock import mock_data


# ------------------------------------------------------------------
# 启动横幅
# ------------------------------------------------------------------
def _print_banner(skills_seeded: int, tasks_seeded: int) -> None:
    """打印中文启动横幅：监听地址、是否 Mock、LLM provider 等。"""
    mock = settings.is_mock_mode()
    mode_text = "Mock 模式（未配置真实 API Key，使用本地拆解）" if mock else f"真实大模型（{settings.LLM_PROVIDER}）"
    line = "=" * 60
    print("\n" + line)
    print("  具身智能自然语言任务编排平台 —— 后端服务已启动")
    print(line)
    print(f"  监听地址      : http://localhost:{settings.BACKEND_PORT}")
    print(f"  接口文档      : http://localhost:{settings.BACKEND_PORT}/docs")
    print(f"  运行模式      : {mode_text}")
    print(f"  大模型厂商    : {settings.LLM_PROVIDER}")
    print(f"  大模型模型名  : {settings.LLM_MODEL}")
    print(f"  采样温度      : {settings.LLM_TEMPERATURE}")
    print(f"  数据库文件    : {settings.DB_PATH}")
    if skills_seeded:
        print(f"  技能库初始化  : 已写入 {skills_seeded} 个原子技能")
    if tasks_seeded:
        print(f"  历史数据初始化: 已生成约 {tasks_seeded} 条历史任务（看板开箱即用）")
    print(line + "\n")


# ------------------------------------------------------------------
# 生命周期：startup 初始化流程（SPEC §10）
# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 建表
    init_db()

    # 2. 若 skills 表为空 → 从 demo_data.json 写入技能库
    skills_seeded = 0
    if count_rows("skills") == 0:
        skills_seeded = seed_skills()

    # 3. 若 tasks 表为空 → 生成约 150 条历史任务（确定性 seed=42）
    tasks_seeded = 0
    if count_rows("tasks") == 0:
        conn = get_conn()
        try:
            mock_data.seed_demo(conn)
        finally:
            conn.close()
        tasks_seeded = count_rows("tasks")

    # 4. 打印启动横幅
    _print_banner(skills_seeded, tasks_seeded)

    yield
    # 关闭事件（无需特别清理，sqlite 连接已逐次关闭）


# ------------------------------------------------------------------
# 创建应用
# ------------------------------------------------------------------
app = FastAPI(
    title="具身智能自然语言任务编排平台",
    description="自然语言任务编排 + 执行模拟 + 数据闭环（Mock 模式开箱即用）",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS：允许前端开发服务器跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# 健康检查 /api/health 由 api/settings.py 的 router 统一提供（去重，避免双重注册）。
# settings 版读 settings 表，能反映用户在「系统设置」页保存后的最新 Mock 状态，
# 与「保存即生效」的交互一致。
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# 挂载六个业务路由，统一前缀 /api
# ------------------------------------------------------------------
app.include_router(task.router, prefix="/api")
app.include_router(skills.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(execution.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")


# ------------------------------------------------------------------
# 允许 `python main.py` 直接启动（等价于 uvicorn main:app）
# ------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.BACKEND_PORT,
        reload=True,
    )
