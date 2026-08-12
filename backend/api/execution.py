"""
执行模拟 API 路由（第 2 组）。

提供两个端点：
- POST /execution/run     ：模拟执行一次任务并落库，返回含 task_id 的 ExecutionResult。
- POST /execution/compare ：对 "llm" 与 "rule" 两种策略各模拟一次，返回 results 数组用于策略对比。

注意（命名约定）：
- 本文件路由路径不再带 `/api` 前缀；前缀由 main.py 在 include_router 时统一加上。
- 返回形状严格遵守 SPEC §8 的 ExecutionResult 与 compare 契约，不自行增删字段。
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Any

# 服务层依赖：
# - executor.simulate_execution：纯模拟执行，产出 ExecutionResult（不含 task_id）。
# - data_loop.record_task     ：把任务与逐步日志写入数据库，返回 task_id。
from services import executor
from services import data_loop

# 导出名必须为 router，供 main.py 挂载。
router = APIRouter()


# ----------------------------------------------------------------------------
# 请求体模型（Pydantic）
#
# 这里把 parsed（ParsedTask）声明为宽松的 dict，原因：
# ParsedTask 形状由 §3 定义，字段较多且 steps 内部结构嵌套，
# 前端传入的就是 task_parser 产出的原样对象。我们不在路由层做强校验，
# 避免因为某个可选字段缺失而误判 422；真正的形状约束在服务层按契约消费。
# ----------------------------------------------------------------------------
class RunRequest(BaseModel):
    """POST /execution/run 的请求体。"""

    # parsed：拆解后的任务对象（ParsedTask，见 SPEC §3）。
    parsed: dict[str, Any] = Field(..., description="拆解后的任务对象 ParsedTask")
    # strategy：执行策略，"llm" 或 "rule"，默认 "llm"。
    strategy: str = Field("llm", description='执行策略："llm" 或 "rule"')


class CompareRequest(BaseModel):
    """POST /execution/compare 的请求体（compare 模式不需要传 strategy，固定对比两种）。"""

    parsed: dict[str, Any] = Field(..., description="拆解后的任务对象 ParsedTask")


# ----------------------------------------------------------------------------
# POST /execution/run
# ----------------------------------------------------------------------------
@router.post("/execution/run")
def run_execution(req: RunRequest) -> dict[str, Any]:
    """
    模拟执行一次任务，并把结果落库（数据闭环的第一环：采集真实执行数据）。

    产品逻辑串联（务必按此顺序）：
    1) executor.simulate_execution(parsed, strategy)
       —— 逐步“执行”任务，按技能类别给基准耗时并加随机抖动，
          按概率判定每步成功/失败，必要时触发 1~2 次重试；
          产出 ExecutionResult（不含 task_id）。
    2) data_loop.record_task(parsed, exec_result, strategy)
       —— 把任务主记录写入 tasks 表、逐步日志写入 task_steps 表，
          并按规则决定是否标记 needs_review（人工介入）；返回 task_id。
    3) 把 task_id 回填进 ExecutionResult 后返回。

    返回形状严格按 SPEC §8 ExecutionResult：
    {
      "task_id", "status", "success",
      "total_duration_ms", "step_count", "retry_count",
      "failure_category", "failure_reason",
      "steps": [ { "index","skill_code","skill_name","params",
                   "status","duration_ms","error" } ... ]
    }
    """
    # 1) 模拟执行：拿到不含 task_id 的执行结果。
    exec_result = executor.simulate_execution(req.parsed, req.strategy)

    # 2) 落库：写入 tasks / task_steps，返回主键 task_id。
    task_id = data_loop.record_task(req.parsed, exec_result, req.strategy)

    # 3) 回填 task_id。直接在结果对象上补字段，保持其余字段原样。
    exec_result["task_id"] = task_id

    # 兜底：确保契约要求的字段都存在（防止 executor 偶发缺字段导致前端解析异常）。
    # 这些字段在 executor 里本应已生成，这里只是防御性补默认值，不改变正常路径行为。
    exec_result.setdefault("status", "success" if exec_result.get("success") else "failed")
    exec_result.setdefault("success", exec_result.get("status") == "success")
    exec_result.setdefault("total_duration_ms", 0)
    exec_result.setdefault("step_count", len(exec_result.get("steps", [])))
    exec_result.setdefault("retry_count", 0)
    exec_result.setdefault("failure_category", None)
    exec_result.setdefault("failure_reason", None)
    exec_result.setdefault("steps", [])

    return exec_result


# ----------------------------------------------------------------------------
# POST /execution/compare
# ----------------------------------------------------------------------------
@router.post("/execution/compare")
def compare_execution(req: CompareRequest) -> dict[str, Any]:
    """
    策略对比：对同一个拆解任务，分别用 "llm" 与 "rule" 各模拟一次，
    用于前端并排展示两条策略的步骤数 / 耗时 / 成功与否，辅助“拿数据说话”地选策略。

    产品逻辑：
    - compare 模式不强制落库（落与不落都不影响返回）。本实现保持“轻量、可重复”，
      不写库，避免对比操作污染统计数据；真正的采集发生在 /execution/run。
    - 对每种策略调用 executor.simulate_execution，并裁剪为契约要求的对比字段。

    返回形状严格按 SPEC §8：
    {
      "results": [
        { "strategy", "success", "total_duration_ms",
          "step_count", "retry_count", "steps": [...] },
        ...
      ]
    }
    其中两个元素分别对应 "llm" 与 "rule"。
    """
    results: list[dict[str, Any]] = []

    # 固定对比这两种策略，顺序：先 llm 后 rule（与前端展示一致）。
    for strategy in ("llm", "rule"):
        # 每种策略各模拟一次（executor 内部含随机性，二者结果天然不同）。
        exec_result = executor.simulate_execution(req.parsed, strategy)

        # 仅保留契约定义的对比字段，避免把 task_id / failure_* 等无关字段带出去。
        results.append(
            {
                "strategy": strategy,
                "success": exec_result.get("success", exec_result.get("status") == "success"),
                "total_duration_ms": exec_result.get("total_duration_ms", 0),
                "step_count": exec_result.get("step_count", len(exec_result.get("steps", []))),
                "retry_count": exec_result.get("retry_count", 0),
                "steps": exec_result.get("steps", []),
            }
        )

    return {"results": results}
