# -*- coding: utf-8 -*-
"""
数据模型模块（Pydantic v2）——（技术契约 SPEC §3 / §8）
------------------------------------------------------------------
定义前后端共享的数据结构，字段与契约严格一致：
  - Step                原子步骤对象（SPEC §3 step 对象）
  - ParseRequest        /api/task/parse 请求体
  - ParsedTask          /api/task/parse 返回（流程图组件消费）
  - ExecutionRunRequest /api/execution/run 请求体
  - ExecutionStep       ExecutionResult 中的步骤（带执行态/耗时/错误）
  - ExecutionResult     /api/execution/run 返回
  - FeedbackRequest     /api/feedback 请求体
  - SkillModel          skills 表行 / 技能增改请求
  - SettingsModel       /api/settings 写入请求

说明：为兼顾「严格契约」与「Mock/真实数据的字段冗余容忍度」，
部分用于「接收外部输入」的模型保留必要的可选字段，便于前端灵活传参。
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ==================================================================
# 一、核心步骤结构（SPEC §3 step 对象）
# ==================================================================
class Step(BaseModel):
    """
    原子步骤对象。对应 SPEC §3：
      { "index":1, "skill_code":"MoveTo", "skill_name":"移动到", "category":"移动类",
        "params":{"target":"桌子"}, "description":"...", "expected_result":"..." }
    """
    index: int = Field(..., description="步骤序号，从 1 开始")
    skill_code: str = Field(..., description="原子技能英文编码，必须来自技能库（SPEC §4）")
    skill_name: str = Field(..., description="技能中文名")
    category: str = Field(default="", description="技能分类：移动类/操作类/感知类/逻辑类/控制类")
    params: dict[str, Any] = Field(default_factory=dict, description="技能参数键值对")
    description: str = Field(default="", description="该步骤的中文说明")
    expected_result: str = Field(default="", description="预期结果")


# ==================================================================
# 二、任务拆解（/api/task/parse）
# ==================================================================
class ParseRequest(BaseModel):
    """POST /api/task/parse 请求体。"""
    instruction: str = Field(..., description="用户自然语言指令")
    strategy: Literal["llm", "rule"] = Field(default="llm", description="拆解策略")


class ParsedTask(BaseModel):
    """
    任务拆解结果（SPEC §3 ParsedTask）。流程图组件直接消费。
    """
    instruction: str = Field(..., description="原始指令")
    task_type: str = Field(default="整理", description="任务归类：整理/分拣/取送/巡检/养护/排序/检查")
    goal: str = Field(default="", description="任务目标")
    constraints: list[str] = Field(default_factory=list, description="约束条件数组")
    steps: list[Step] = Field(default_factory=list, description="步骤对象数组")
    exception_handling: list[str] = Field(default_factory=list, description="异常处理数组")


# ==================================================================
# 三、执行模拟（/api/execution/run）
# ==================================================================
class ExecutionRunRequest(BaseModel):
    """POST /api/execution/run 请求体。"""
    parsed: ParsedTask = Field(..., description="待执行的拆解任务")
    strategy: Literal["llm", "rule"] = Field(default="llm", description="执行所用策略")


class ExecutionStep(BaseModel):
    """
    执行结果中的单步（带执行态、耗时与错误）。对应 SPEC §3 ExecutionResult.steps[]。
    """
    index: int = Field(..., description="步骤序号")
    skill_code: str = Field(..., description="技能编码")
    skill_name: str = Field(..., description="技能中文名")
    params: dict[str, Any] = Field(default_factory=dict, description="技能参数")
    status: Literal["success", "failed"] = Field(..., description="该步最终态")
    duration_ms: int = Field(..., description="该步耗时（毫秒）")
    error: Optional[str] = Field(default=None, description="失败时的错误信息，否则为 null")


class ExecutionResult(BaseModel):
    """
    执行结果（SPEC §3 ExecutionResult）。
    task_id 在落库后由 data_loop 回填；compare 模式下可能为空。
    """
    task_id: Optional[int] = Field(default=None, description="落库后的任务 id")
    status: Literal["success", "failed"] = Field(..., description="整体状态")
    success: bool = Field(..., description="是否成功")
    total_duration_ms: int = Field(..., description="总耗时（毫秒）")
    step_count: int = Field(..., description="步骤数")
    retry_count: int = Field(..., description="重试次数")
    failure_category: Optional[str] = Field(default=None, description="失败分类（中文）或 null")
    failure_reason: Optional[str] = Field(default=None, description="失败原因文字或 null")
    steps: list[ExecutionStep] = Field(default_factory=list, description="逐步执行日志")


class CompareRequest(BaseModel):
    """POST /api/execution/compare 请求体。"""
    parsed: ParsedTask = Field(..., description="待对比执行的拆解任务")


# ==================================================================
# 四、反馈与人工介入（/api/feedback）
# ==================================================================
class FeedbackRequest(BaseModel):
    """
    POST /api/feedback 请求体（SPEC §8 feedback.py）。
    corrected_steps 非空时，对应任务将被标记为优质样本（is_golden=1）。
    """
    task_id: int = Field(..., description="任务 id")
    rating: int = Field(..., ge=1, le=5, description="评分 1-5")
    comment: Optional[str] = Field(default=None, description="文字评价")
    corrected_steps: Optional[list[Step]] = Field(default=None, description="人工修正后的步骤")


class HitlResolveRequest(BaseModel):
    """POST /api/feedback/hitl/{id}/resolve 请求体。"""
    corrected_steps: list[Step] = Field(default_factory=list, description="修正后的步骤")
    failure_category: Optional[str] = Field(default=None, description="可选：修订失败分类")


# ==================================================================
# 五、技能管理（/api/skills）
# ==================================================================
class SkillModel(BaseModel):
    """
    技能模型（SPEC §2 skills 表 / SPEC §8 skills.py）。
    用于新建/更新技能；查询返回时 input_params/output 已被 json.loads 为对象。
    新建时 id 可缺省；更新时按需传部分字段。
    """
    id: Optional[int] = Field(default=None, description="技能 id（新建时缺省）")
    code: str = Field(..., description="英文编码，唯一，如 MoveTo")
    name: str = Field(..., description="中文名")
    category: str = Field(..., description="移动类/操作类/感知类/逻辑类/控制类")
    icon: str = Field(default="", description="emoji 图标")
    description: str = Field(default="", description="技能描述")
    input_params: list[dict[str, Any]] = Field(default_factory=list, description="入参定义 [{name,type,desc}]")
    output: dict[str, Any] = Field(default_factory=dict, description="出参定义 {type,desc}")
    enabled: int = Field(default=1, description="是否启用 0/1")


class SkillUpdate(BaseModel):
    """技能部分更新（PUT /api/skills/{id}）：所有字段可选。"""
    code: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    input_params: Optional[list[dict[str, Any]]] = None
    output: Optional[dict[str, Any]] = None
    enabled: Optional[int] = None


# ==================================================================
# 六、系统设置（/api/settings）
# ==================================================================
class LLMSettings(BaseModel):
    """大模型配置块。api_key 仅用于写入，GET 时不回明文。"""
    provider: Optional[Literal["openai", "qwen", "zhipu", "mock"]] = Field(
        default=None, description="厂商"
    )
    model: Optional[str] = Field(default=None, description="模型名")
    api_key: Optional[str] = Field(default=None, description="API Key（写入用，不回传）")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="采样温度")


class SimSettings(BaseModel):
    """仿真配置块。"""
    room_size: Optional[int] = Field(default=None, description="房间尺寸")
    robot_speed: Optional[float] = Field(default=None, description="机器人速度")


class DataSettings(BaseModel):
    """数据配置块。"""
    retention_days: Optional[int] = Field(default=None, description="数据保留天数")
    auto_clean: Optional[bool] = Field(default=None, description="是否自动清理")


class SettingsModel(BaseModel):
    """
    POST /api/settings 请求体（SPEC §8 settings.py）。
    三块均可选，按需提交部分配置。
    """
    llm: Optional[LLMSettings] = None
    sim: Optional[SimSettings] = None
    data: Optional[DataSettings] = None
