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

const taskNames = ['把红色的杯子放到桌子右边', '整理桌面上的书和笔', '分拣蓝色方块到 A 区', '巡检仓库货架并记录缺货位置', '将样品按重量升序摆放']
const tasks = Array.from({ length: 18 }, (_, index) => ({
  id: 100 + index,
  instruction: taskNames[index % taskNames.length],
  task_type: ['取送', '整理', '分拣', '巡检'][index % 4],
  strategy: index % 2 ? 'rule' : 'llm',
  status: index % 5 === 0 ? 'review' : 'success',
  success: index % 5 === 0 ? 0 : 1,
  failure_category: index % 5 === 0 ? '感知类失败' : null,
  total_duration_ms: 3200 + (index % 5) * 410,
  step_count: 5,
  retry_count: index % 3,
  rating: index % 5 === 0 ? 3 : 5,
  is_golden: index % 3 === 0,
  created_at: `2026-06-${String(30 - (index % 18)).padStart(2, '0')}T${String(9 + index % 8).padStart(2, '0')}:20:00`,
}))

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
    task_type: instruction.includes('巡检') ? '巡检' : '取送',
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
    dates: ['06-01', '06-05', '06-09', '06-13', '06-17', '06-21', '06-25', '06-29'],
    task_counts: [18, 21, 16, 24, 27, 23, 29, 32],
    success_rates: [0.68, 0.71, 0.73, 0.70, 0.76, 0.78, 0.75, 0.82],
  },
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
    { category: '感知类能力', count: 18 }, { category: '认知类能力', count: 13 },
    { category: '规划类能力', count: 11 }, { category: '执行类能力', count: 9 }, { category: '环境类能力', count: 5 },
  ],
  category_trend: {
    dates: ['06-01', '06-05', '06-09', '06-13', '06-17', '06-21', '06-25', '06-29'],
    series: [
      { name: '感知类能力', data: [2, 3, 2, 4, 3, 2, 1, 1] },
      { name: '规划类能力', data: [1, 1, 2, 1, 2, 1, 2, 1] },
    ],
  },
}

const suggestions = [
  { priority: '高', title: '补充遮挡场景训练样本', problem: '复杂遮挡下的目标识别覆盖不足', evidence: '感知类能力占 39% 的重点案例', solution: '增加多视角与弱光场景样本', expected_gain: '预计成功率 +6~8%', modules: ['感知', '数据闭环'] },
  { priority: '中', title: '优化长链路任务的子目标拆解', problem: '超过 4 步的任务耗时波动较大', evidence: '长任务平均耗时高于均值 18%', solution: '为规划器增加阶段性确认节点', expected_gain: '平均耗时 -12%', modules: ['规划', '任务编排'] },
]

export const getExamples = () => Promise.resolve(examples)
export const parseTask = (instruction, strategy = 'llm') => Promise.resolve(makeParsed(instruction, strategy))
export const getSkills = (category) => Promise.resolve(category ? skills.filter((item) => item.category === category) : skills)
export const createSkill = (data) => Promise.resolve({ id: Date.now(), ...data, enabled: 1 })
export const updateSkill = (id, data) => Promise.resolve({ ...skills.find((item) => item.id === id), ...data })
export const deleteSkill = () => Promise.resolve({ ok: true })
export const runExecution = (parsed) => Promise.resolve({
  task_id: 901,
  success: true,
  total_duration_ms: parsed.steps.length * 760,
  retry_count: 0,
  steps: parsed.steps.map((step, index) => ({ ...step, status: 'success', duration_ms: 620 + index * 130, error: null })),
})
export const compareExecution = (parsed) => Promise.resolve({ results: [
  { strategy: 'llm', success: true, step_count: parsed.steps.length, total_duration_ms: 3680, retry_count: 0 },
  { strategy: 'rule', success: true, step_count: parsed.steps.length + 1, total_duration_ms: 4260, retry_count: 1 },
] })
export const getTasks = () => Promise.resolve(tasks)
export const getTask = (id) => Promise.resolve({ task: tasks.find((item) => item.id === Number(id)) || tasks[0], steps: makeParsed(tasks[0].instruction).steps, feedback: null })
export const deleteTask = () => Promise.resolve({ ok: true })
export const submitFeedback = () => Promise.resolve({ ok: true })
export const getHitlList = () => Promise.resolve(tasks.filter((item) => item.status === 'review'))
export const resolveHitl = () => Promise.resolve({ ok: true })
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
export const getSettings = () => Promise.resolve({ llm: { provider: 'mock', model: 'mock-local', api_key_set: false, temperature: 0.3 }, sim: { room_width: 10, room_height: 8, robot_speed: 1.2 }, data: { retention_days: 30, auto_cleanup: true } })
export const saveSettings = (data) => Promise.resolve({ ok: true, ...data })
export const getHealth = () => Promise.resolve({ status: 'ok', mock_mode: true, llm_provider: 'mock-local' })

export default { getExamples, parseTask, getSkills, runExecution, compareExecution, getTasks, getTask, getOverview, getFailures, getTasksAnalysis, getStrategyCompare, getSuggestions, getHealth }
