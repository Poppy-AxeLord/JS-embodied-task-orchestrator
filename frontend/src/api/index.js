// 离线体验专用 Mock API：前端不再依赖 FastAPI、SQLite 或任何真实模型服务。
// 保留原有函数名和返回结构，让所有页面、图表和交互可以离线完整演示。

const examples = [
  { instruction: '把红色的杯子放到桌子右边', task_type: '取送', difficulty: '简单' },
  { instruction: '先整理桌面，再去厨房拿一瓶水', task_type: '整理', difficulty: '中等' },
  { instruction: '分拣所有蓝色方块到 A 区，红色的放到 B 区', task_type: '分拣', difficulty: '中等' },
  { instruction: '规划仓库巡检路线，避开有人区域', task_type: '巡检', difficulty: '困难' },
  { instruction: '清理桌面上的书和笔，放到收纳盒里', task_type: '整理', difficulty: '中等' },
  { instruction: '把易碎品轻轻放到上层货架', task_type: '取送', difficulty: '中等' },
  { instruction: '找到遥控器，放到沙发旁边', task_type: '取送', difficulty: '简单' },
  { instruction: '检查货架上的包装是否完整', task_type: '巡检', difficulty: '中等' },
]

const skillSeed = [
  ['MoveTo', '移动到', '移动类', '移动到指定位置或物体附近'],
  ['Navigate', '路径规划', '移动类', '规划避障路径'],
  ['FindObject', '识别物体', '感知类', '识别目标物体的颜色、形状与位置'],
  ['Locate', '精确定位', '感知类', '获取目标的可抓取坐标'],
  ['Grasp', '抓取', '操作类', '控制夹爪完成稳定抓取'],
  ['Place', '放置', '操作类', '将物体放到目标区域'],
  ['Verify', '结果确认', '逻辑类', '确认任务目标是否达成'],
  ['Retry', '异常重试', '控制类', '根据失败原因选择重试策略'],
]
const skills = skillSeed.map(([code, name, category, description], index) => ({
  id: index + 1,
  code,
  name,
  category,
  icon: ['↗', '⌖', '◉', '⌁', '✣', '▣', '✓', '↻'][index],
  description,
  input_params: [{ name: 'target', type: 'string', desc: '目标物体或位置' }],
  output: { type: 'boolean', desc: '动作是否完成' },
  enabled: 1,
}))

const taskSeeds = [
  { instruction: '把红色的杯子放到桌子右边', task_type: '取送' },
  { instruction: '整理桌面上的书和笔', task_type: '整理' },
  { instruction: '分拣蓝色方块到 A 区', task_type: '分拣' },
  { instruction: '巡检仓库货架并记录缺货位置', task_type: '巡检' },
  { instruction: '将样品按重量升序摆放', task_type: '排序' },
]
const taskNames = taskSeeds.map((item) => item.instruction)
// 用 30 天连续的、可复现的数据模拟稳定运营中的平台：所有图表在首次进入时都有
// 完整时间序列，而不是把“最近 30 天”画成零散的几个采样点。
const dayLabels = Array.from({ length: 30 }, (_, index) => `06-${String(index + 1).padStart(2, '0')}`)
const dailyTaskCounts = [12, 14, 13, 15, 16, 18, 17, 19, 18, 21, 20, 22, 24, 23, 25, 24, 27, 26, 28, 30, 29, 31, 30, 33, 32, 35, 34, 36, 38, 40]
const dailySuccessRates = [0.68, 0.69, 0.71, 0.7, 0.72, 0.73, 0.72, 0.74, 0.75, 0.74, 0.76, 0.77, 0.76, 0.78, 0.79, 0.78, 0.8, 0.79, 0.81, 0.82, 0.81, 0.83, 0.82, 0.84, 0.83, 0.85, 0.84, 0.86, 0.85, 0.87]
const reviewReasons = {
  感知失败: '目标被临时遮挡，识别置信度低于安全阈值，已转人工复核。',
  规划失败: '动态障碍改变了原定路径，当前策略未能在时限内完成可靠重规划。',
  执行失败: '夹爪接触力波动超出易碎物体安全范围，系统已中止后续放置动作。',
}

const tasks = Array.from({ length: 48 }, (_, index) => {
  const isReview = index % 7 === 0
  // 已失败与待人工介入是不同状态：前者用于回放失败，后者进入人机协同修正队列。
  const isFailed = !isReview && index % 11 === 0
  const failure_category = (isReview || isFailed) ? ['感知失败', '规划失败', '执行失败'][index % 3] : null
  return {
    id: 100 + index,
    instruction: taskSeeds[index % taskSeeds.length].instruction,
    task_type: taskSeeds[index % taskSeeds.length].task_type,
    strategy: index % 2 ? 'rule' : 'llm',
    status: isReview ? 'needs_review' : (isFailed ? 'failed' : 'success'),
    success: isReview || isFailed ? 0 : 1,
    failure_category,
    failure_reason: failure_category ? reviewReasons[failure_category] : null,
    total_duration_ms: 3200 + (index % 5) * 410,
    step_count: 5,
    retry_count: isFailed ? 2 : index % 3,
    rating: isReview ? 3 : (isFailed ? 2 : (index % 5 === 0 ? 4 : 5)),
    is_golden: !isReview && !isFailed && index % 3 === 0,
    created_at: `2026-06-${String(30 - (index % 30)).padStart(2, '0')}T${String(9 + index % 8).padStart(2, '0')}:20:00`,
  }
})

function makeParsed(instruction, strategy = 'llm') {
  const steps = [
    ['FindObject', '识别目标物体', { target: instruction.includes('杯') ? '红色杯子' : '目标物体' }],
    ['Locate', '定位目标与放置区域', { target: '目标坐标' }],
    ['Grasp', '稳定抓取目标物体', { grip: '自适应力度' }],
    ['MoveTo', '移动至目标区域', { target: '目标位置' }],
    ['Place', '放置并确认结果', { verify: true }],
  ].map(([skill_code, description, params], index) => ({
    index: index + 1,
    skill_code,
    skill_name: skills.find((item) => item.code === skill_code)?.name || skill_code,
    category: skills.find((item) => item.code === skill_code)?.category || '操作类',
    description,
    expected_result: '动作完成并进入下一步',
    params,
    expected_duration_ms: 620 + index * 130,
  }))
  return {
    instruction,
    strategy,
    task_type: instruction.includes('巡检') || instruction.includes('检查') ? '巡检'
      : instruction.includes('分拣') ? '分拣'
        : instruction.includes('整理') ? '整理'
          : instruction.includes('重量') || instruction.includes('排序') ? '排序'
            : '取送',
    difficulty: instruction.length > 16 ? '中等' : '简单',
    goal: `完成：${instruction}`,
    constraints: ['保持目标物体完整', '避开动态障碍', '完成后确认状态'],
    exception_handling: ['目标不可见时重新定位', '抓取失败时降低力度并重试'],
    steps,
  }
}

const overview = {
  cards: { total_tasks: 150, success_rate: 0.76, avg_duration_ms: 4620, satisfaction: 4.6 },
  metrics: {
    polaris: { name: '任务成功率', value: 76, unit: '%' },
    process: [{ name: '平均拆解步骤', value: 5, unit: ' 步' }, { name: '人工反馈覆盖', value: 82, unit: '%' }],
    result: [{ name: '优质样本', value: 42, unit: ' 条' }, { name: '策略迭代次数', value: 12, unit: ' 次' }],
  },
  trend: {
    dates: dayLabels,
    task_counts: dailyTaskCounts,
    success_rates: dailySuccessRates,
  },
}

// 系统设置同样是离线 Demo 的一部分：保存后在当前浏览会话内应能被再次读取，
// 而不是只显示一次成功提示后又回到默认值。
const settings = {
  llm: { provider: 'mock', model: 'mock-local', api_key_set: false, temperature: 0.3 },
  sim: { room_size: 10, robot_speed: 1.2 },
  data: { retention_days: 30, auto_clean: true },
}

const failures = {
  top_reasons: [
    { reason: '目标被遮挡，未能稳定识别', count: 8 },
    { reason: '步骤顺序需要重新规划', count: 6 },
    { reason: '抓取力度与物体材质不匹配', count: 5 },
    { reason: '放置区域定位出现偏差', count: 4 },
    { reason: '缺少必要的前置感知步骤', count: 3 },
  ],
  category_pie: [
    { category: '感知失败', count: 18, color: '#5B8FF9' }, { category: '理解失败', count: 13, color: '#5AD8A6' },
    { category: '规划失败', count: 11, color: '#F6BD16' }, { category: '执行失败', count: 9, color: '#E8684A' }, { category: '环境异常', count: 5, color: '#9270CA' },
  ],
  category_trend: {
    dates: dayLabels,
    series: [
      { category: '感知失败', data: [4, 4, 3, 4, 3, 4, 3, 3, 3, 2, 3, 3, 2, 3, 2, 2, 3, 2, 2, 2, 2, 1, 2, 1, 2, 1, 1, 1, 1, 1] },
      { category: '理解失败', data: [3, 3, 2, 3, 2, 2, 2, 2, 1, 2, 2, 1, 2, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 1, 0] },
      { category: '规划失败', data: [3, 2, 3, 2, 2, 3, 2, 2, 2, 2, 1, 2, 2, 1, 2, 1, 2, 1, 1, 2, 1, 1, 1, 1, 1, 1, 0, 1, 0, 1] },
      { category: '执行失败', data: [2, 2, 2, 2, 2, 1, 2, 2, 1, 2, 1, 2, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 0, 1, 0, 0, 0] },
      { category: '环境异常', data: [1, 1, 1, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0] },
    ],
  },
}

const suggestions = [
  { priority: '高', title: '补充遮挡场景训练样本', metric: '感知稳定性', detail: '为遮挡、反光与弱光工况补齐多视角样本，并让低置信度目标触发二次确认。', evidence: '感知类失败占重点案例 39%，近两周已由 4 次降至 1 次。', expected_gain: '预计成功率 +6~8%', modules: ['感知', '数据闭环'] },
  { priority: '中', title: '优化长链路任务的子目标拆解', metric: '平均执行时长', detail: '为超过 4 步的任务增加阶段性校验点，减少无效回退与重复定位。', evidence: '长任务平均耗时高于平台均值 18%，规则策略重试次数偏高。', expected_gain: '平均耗时 -12%', modules: ['规划', '任务编排'] },
  { priority: '低', title: '固化高评分人工反馈为黄金样本', metric: '优质样本', detail: '将五星反馈与成功执行轨迹自动归档，建立可回归的任务模板库。', evidence: '已有 42 条高质量样本，覆盖取送、整理、分拣与巡检。', expected_gain: '满意度 +0.2', modules: ['反馈', '评测'] },
]

export const getExamples = () => Promise.resolve(examples)
export const parseTask = (instruction, strategy = 'llm') => Promise.resolve(makeParsed(instruction, strategy))
export const getSkills = (category) => Promise.resolve(category ? skills.filter((item) => item.category === category) : skills)
export const createSkill = (data = {}) => Promise.resolve((() => {
  const skill = { id: Math.max(...skills.map((item) => item.id), 0) + 1, ...data, enabled: data.enabled ?? 1 }
  skills.push(skill)
  return { ...skill }
})())
export const updateSkill = (id, data = {}) => Promise.resolve((() => {
  const skill = skills.find((item) => item.id === Number(id))
  if (skill) Object.assign(skill, data)
  return skill ? { ...skill } : null
})())
export const deleteSkill = (id) => Promise.resolve((() => {
  const index = skills.findIndex((item) => item.id === Number(id))
  if (index >= 0) skills.splice(index, 1)
  return { ok: true }
})())
export const runExecution = (parsed, strategy = 'llm') => Promise.resolve((() => {
  const steps = parsed.steps.map((step, index) => ({
    ...step,
    index: index + 1,
    status: 'success',
    duration_ms: 620 + index * 130,
    error: null,
  }))
  const total_duration_ms = steps.reduce((total, step) => total + step.duration_ms, 0)
  const task = {
    id: Math.max(...tasks.map((item) => item.id), 0) + 1,
    instruction: parsed.instruction,
    task_type: parsed.task_type || '取送',
    strategy,
    status: 'success',
    success: 1,
    failure_category: null,
    total_duration_ms,
    step_count: steps.length,
    retry_count: 0,
    rating: null,
    is_golden: false,
    goal: parsed.goal,
    constraints: parsed.constraints,
    exception_handling: parsed.exception_handling,
    executed_steps: steps,
    feedback: [],
    created_at: new Date().toISOString(),
  }
  tasks.unshift(task)
  overview.cards.total_tasks += 1
  return { task_id: task.id, success: true, total_duration_ms, retry_count: 0, steps }
})())
export const compareExecution = (parsed) => Promise.resolve({ results: [
  { strategy: 'llm', success: true, step_count: parsed.steps.length, total_duration_ms: 3680, retry_count: 0 },
  { strategy: 'rule', success: true, step_count: parsed.steps.length + 1, total_duration_ms: 4260, retry_count: 1 },
] })
export const getTasks = (params = {}) => Promise.resolve((() => {
  let result = [...tasks]
  if (params.status) result = result.filter((task) => task.status === params.status)
  if (params.task_type) result = result.filter((task) => task.task_type === params.task_type)
  if (params.sort === 'success') result.sort((a, b) => Number(b.success) - Number(a.success))
  else if (params.sort === 'duration') result.sort((a, b) => b.total_duration_ms - a.total_duration_ms)
  else result.sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
  return result
})())
export const getTask = (id) => Promise.resolve((() => {
  const task = tasks.find((item) => item.id === Number(id)) || tasks[0]
  const parsed = makeParsed(task.instruction, task.strategy)
  const sourceSteps = task.corrected_steps?.length
    ? task.corrected_steps
    : (task.executed_steps?.length ? task.executed_steps : parsed.steps)
  const steps = sourceSteps.map((step, index) => ({
    ...step,
    step_index: index + 1,
    status: step.status || (task.success ? 'success' : (index === 2 ? 'failed' : 'success')),
    duration_ms: step.duration_ms || 620 + index * 130,
    error: step.error ?? (!task.success && index === 2
      ? (task.status === 'needs_review' ? '目标状态置信度不足，已转人工复核' : '关键动作未满足安全阈值，本次执行已终止并归档')
      : null),
  }))
  const feedback = task.feedback?.length
    ? task.feedback
    : (task.rating ? [{ rating: task.rating, comment: task.success ? '执行轨迹稳定，可作为回归样本。' : '已标记关键失败步骤，等待人工修正。', created_at: task.created_at }] : [])
  return {
    task: {
      ...task,
      goal: task.goal || parsed.goal,
      constraints: task.constraints || parsed.constraints,
      exception_handling: task.exception_handling || parsed.exception_handling,
      step_count: steps.length,
    },
    steps,
    feedback,
  }
})())
export const deleteTask = (id) => Promise.resolve((() => {
  const index = tasks.findIndex((task) => task.id === Number(id))
  if (index >= 0) tasks.splice(index, 1)
  return { ok: true }
})())
export const submitFeedback = (payload = {}) => Promise.resolve((() => {
  const task = tasks.find((item) => item.id === Number(payload.task_id))
  if (task) {
    task.rating = payload.rating || task.rating || 5
    task.feedback = task.feedback || []
    task.feedback.unshift({
      rating: task.rating,
      comment: payload.comment?.trim() || '执行轨迹已确认，可作为后续回归参考。',
      created_at: new Date().toISOString(),
    })
    if (task.rating >= 5 && task.success) task.is_golden = true
  }
  return { ok: true }
})())
export const getHitlList = () => Promise.resolve(tasks
  .filter((item) => item.status === 'needs_review')
  .map((item) => ({
    ...item,
    // 人工修正器需要可编辑的原始轨迹；不能只展示一条孤立的失败记录。
    steps: makeParsed(item.instruction, item.strategy).steps,
  })))
export const resolveHitl = (id, payload = {}) => Promise.resolve((() => {
  const task = tasks.find((item) => item.id === Number(id))
  if (task) {
    task.status = 'success'
    task.success = 1
    task.is_golden = 1
    task.corrected_steps = (payload.corrected_steps || []).map((step, index) => ({
      ...step,
      index: index + 1,
    }))
    task.resolved_failure_category = payload.failure_category || task.failure_category
    task.failure_category = null
    task.rating = 5
  }
  return { ok: true }
})())
export const getOverview = () => Promise.resolve(overview)
export const getFailures = () => Promise.resolve(failures)
export const getTasksAnalysis = () => Promise.resolve({
  top_tasks: taskNames.map((instruction, index) => ({ instruction, count: 13 - index, success_rate: 0.68 + index * 0.06 })),
  type_success: ['取送', '整理', '分拣', '巡检'].map((task_type, index) => ({ task_type, total: 20 + index * 5, success_rate: 0.72 + index * 0.05 })),
  difficulty_dist: [{ difficulty: '简单', count: 42 }, { difficulty: '中等', count: 76 }, { difficulty: '困难', count: 32 }],
})
export const getStrategyCompare = () => Promise.resolve({
  success: [{ strategy: 'llm', success_rate: 0.82 }, { strategy: 'rule', success_rate: 0.76 }],
  duration: [{ strategy: 'llm', avg_duration_ms: 4380 }, { strategy: 'rule', avg_duration_ms: 5120 }],
  radar: { indicators: [{ name: '成功率', max: 100 }, { name: '速度', max: 100 }, { name: '稳定性', max: 100 }, { name: '步骤精简度', max: 100 }, { name: '满意度', max: 100 }], series: [{ strategy: 'llm', data: [82, 86, 81, 78, 90] }, { strategy: 'rule', data: [76, 71, 85, 84, 80] }] },
})
export const getSuggestions = () => Promise.resolve(suggestions)
export const getSettings = () => Promise.resolve({
  llm: { ...settings.llm },
  sim: { ...settings.sim },
  data: { ...settings.data },
})
export const saveSettings = (data = {}) => Promise.resolve((() => {
  if (data.llm) {
    const api_key_set = data.llm.api_key ? true : settings.llm.api_key_set
    Object.assign(settings.llm, data.llm, { api_key_set })
    delete settings.llm.api_key
  }
  if (data.sim) Object.assign(settings.sim, data.sim)
  if (data.data) Object.assign(settings.data, data.data)
  return { ok: true, llm: { ...settings.llm }, sim: { ...settings.sim }, data: { ...settings.data } }
})())
export const getHealth = () => Promise.resolve({ status: 'ok', mock_mode: true, llm_provider: settings.llm.provider === 'mock' ? 'mock-local' : `${settings.llm.provider}（演示）` })

export default { getExamples, parseTask, getSkills, runExecution, compareExecution, getTasks, getTask, getOverview, getFailures, getTasksAnalysis, getStrategyCompare, getSuggestions, getHealth }
