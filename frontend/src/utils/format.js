// 前端通用格式化与映射工具集
// 集中维护：失败分类配色（SPEC §5）、时长/百分比/日期格式化、
// 任务类型与策略的中文名映射、技能分类配色等。
// 各页面统一从这里取值，避免散落的魔法字符串。

/* ============================================================
 * 一、失败分类 → 颜色映射（严格对应 SPEC §5）
 * 注意：后端 tasks.failure_category 存的是【中文】（如 "感知失败"），
 *      因此这里同时提供「英文 key」和「中文名」两套映射，方便任意场景查询。
 * ============================================================ */

// 5 类失败的完整定义（key / 中文 / 含义 / 颜色）
export const FAILURE_CATEGORIES = [
  { key: 'perception', name: '感知失败', desc: '识别错误、看不清、遮挡', color: '#5B8FF9' },
  { key: 'understanding', name: '理解失败', desc: '指令理解偏差、歧义', color: '#5AD8A6' },
  { key: 'planning', name: '规划失败', desc: '步骤不合理、顺序错误', color: '#F6BD16' },
  { key: 'execution', name: '执行失败', desc: '动作执行出错、抓取掉落', color: '#E8684A' },
  { key: 'environment', name: '环境异常', desc: '障碍物、物体移动、人员干扰', color: '#9270CA' }
]

// 中文名 → 颜色（前端最常用：直接拿数据库里的中文 category 取色）
export const FAILURE_COLOR_MAP = FAILURE_CATEGORIES.reduce((map, item) => {
  map[item.name] = item.color
  map[item.key] = item.color // 兼容英文 key 传入
  return map
}, {})

// 兜底色：无分类 / 未知分类时使用的中性灰
const FAILURE_FALLBACK_COLOR = '#9ca3af'

/**
 * 根据失败分类（中文名或英文 key）返回对应配色。
 * @param {string} category 例如 "感知失败" 或 "perception"
 * @returns {string} 十六进制颜色
 */
export function failureColor(category) {
  if (!category) return FAILURE_FALLBACK_COLOR
  return FAILURE_COLOR_MAP[category] || FAILURE_FALLBACK_COLOR
}

/**
 * 失败分类对应的 Element Plus el-tag 类型（用于无自定义色场景的兜底视觉）。
 * @param {string} category 中文名或英文 key
 * @returns {'primary'|'success'|'warning'|'danger'|'info'}
 */
export function failureTagType(category) {
  const map = {
    感知失败: 'primary',
    理解失败: 'success',
    规划失败: 'warning',
    执行失败: 'danger',
    环境异常: 'info'
  }
  return map[category] || 'info'
}

/* ============================================================
 * 二、技能分类 → 颜色映射（SPEC §4 的 5 大类）
 * 用于流程图节点、技能库卡片的彩色着色。
 * ============================================================ */

export const SKILL_CATEGORY_COLORS = {
  移动类: '#2563EB', // 主色蓝
  操作类: '#E8684A', // 暖橙
  感知类: '#5AD8A6', // 青绿
  逻辑类: '#F6BD16', // 明黄
  控制类: '#9270CA' // 紫
}

/**
 * 根据技能分类返回配色（流程图/技能卡片用）。
 * @param {string} category 例如 "移动类"
 * @returns {string} 十六进制颜色
 */
export function skillCategoryColor(category) {
  return SKILL_CATEGORY_COLORS[category] || '#2563EB'
}

// 兼容别名：部分组件（如 TaskFlowChart）以 getCategoryColor 引用技能分类配色，
// 与 skillCategoryColor 完全等价，保留以避免命名导入缺失。
export const getCategoryColor = skillCategoryColor

// 技能分类的固定展示顺序（技能库分组、图例排序用）
export const SKILL_CATEGORY_ORDER = ['移动类', '操作类', '感知类', '逻辑类', '控制类']

/* ============================================================
 * 三、任务类型（task_type）选项（SPEC §2 / §6 的 7 类）
 * 用于下拉筛选、表单选择。
 * ============================================================ */

export const TASK_TYPE_OPTIONS = [
  { label: '整理', value: '整理' },
  { label: '分拣', value: '分拣' },
  { label: '取送', value: '取送' },
  { label: '巡检', value: '巡检' },
  { label: '养护', value: '养护' },
  { label: '排序', value: '排序' },
  { label: '检查', value: '检查' }
]

/**
 * 任务类型 → el-tag 颜色类型（让历史列表/看板的类型标签更有辨识度）。
 */
export function taskTypeTagType(taskType) {
  const map = {
    整理: 'primary',
    分拣: 'success',
    取送: 'warning',
    巡检: 'danger',
    养护: 'success',
    排序: 'info',
    检查: 'warning'
  }
  return map[taskType] || 'info'
}

/* ============================================================
 * 四、策略（strategy）中文名与选项
 * ============================================================ */

// strategy 取值 → 中文展示名
export const STRATEGY_NAME_MAP = {
  llm: '大模型拆解',
  rule: '规则拆解'
}

/**
 * 把策略英文标识转为中文名。
 * @param {string} strategy 'llm' | 'rule'
 * @returns {string}
 */
export function strategyName(strategy) {
  return STRATEGY_NAME_MAP[strategy] || strategy || '未知策略'
}

// 策略下拉/单选选项
export const STRATEGY_OPTIONS = [
  { label: '大模型拆解（LLM）', value: 'llm' },
  { label: '规则拆解（Rule）', value: 'rule' }
]

/* ============================================================
 * 五、难度（difficulty）映射
 * ============================================================ */

/**
 * 难度 → el-tag 类型。
 * @param {string} difficulty 简单 | 中等 | 困难
 */
export function difficultyTagType(difficulty) {
  const map = { 简单: 'success', 中等: 'warning', 困难: 'danger' }
  return map[difficulty] || 'info'
}

/* ============================================================
 * 六、状态（status）映射
 * ============================================================ */

// 任务状态 → 中文 + el-tag 类型
export const STATUS_META = {
  success: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  pending: { label: '待执行', type: 'info' }
}

/**
 * 任务状态中文名。
 */
export function statusLabel(status) {
  return STATUS_META[status]?.label || status || '未知'
}

/**
 * 任务状态对应 el-tag 类型。
 */
export function statusTagType(status) {
  return STATUS_META[status]?.type || 'info'
}

/* ============================================================
 * 七、时长 / 百分比 / 日期 格式化
 * ============================================================ */

/**
 * 毫秒 → 可读时长。
 * 规则：<1s 显示「xxx 毫秒」；<60s 显示「x.x 秒」；≥60s 显示「x 分 x 秒」。
 * @param {number} ms 毫秒数
 * @returns {string}
 */
export function formatDuration(ms) {
  if (ms === null || ms === undefined || Number.isNaN(Number(ms))) return '—'
  const n = Number(ms)
  if (n < 1000) return `${Math.round(n)} 毫秒`
  if (n < 60000) return `${(n / 1000).toFixed(1)} 秒`
  const minutes = Math.floor(n / 60000)
  const seconds = Math.round((n % 60000) / 1000)
  return seconds > 0 ? `${minutes} 分 ${seconds} 秒` : `${minutes} 分`
}

/**
 * 把比例（0~1）格式化为百分比文本。
 * @param {number} ratio 例如 0.764
 * @param {number} digits 小数位，默认 1
 * @returns {string} 例如 "76.4%"
 */
export function formatPercent(ratio, digits = 1) {
  if (ratio === null || ratio === undefined || Number.isNaN(Number(ratio))) {
    return '—'
  }
  return `${(Number(ratio) * 100).toFixed(digits)}%`
}

/**
 * 把已经是百分比数值（0~100）的数据格式化（避免重复乘 100）。
 * @param {number} value 例如 76.4
 * @param {number} digits 小数位，默认 1
 */
export function formatPercentValue(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }
  return `${Number(value).toFixed(digits)}%`
}

/**
 * 数字千分位格式化（大数展示更清晰）。
 * @param {number} num
 * @returns {string}
 */
export function formatNumber(num) {
  if (num === null || num === undefined || Number.isNaN(Number(num))) return '—'
  return Number(num).toLocaleString('zh-CN')
}

/**
 * 保留指定小数位（用于评分均值等），无效值返回占位符。
 * @param {number} num
 * @param {number} digits 默认 1
 */
export function formatFixed(num, digits = 1) {
  if (num === null || num === undefined || Number.isNaN(Number(num))) return '—'
  return Number(num).toFixed(digits)
}

/**
 * 日期格式化。支持传入 ISO 字符串或 Date 对象。
 * @param {string|Date} value
 * @param {string} pattern 默认 'YYYY-MM-DD HH:mm'，支持 YYYY/MM/DD/HH/mm/ss 占位
 * @returns {string}
 */
export function formatDate(value, pattern = 'YYYY-MM-DD HH:mm') {
  if (!value) return '—'
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  const pad = (n) => String(n).padStart(2, '0')
  const map = {
    YYYY: d.getFullYear(),
    MM: pad(d.getMonth() + 1),
    DD: pad(d.getDate()),
    HH: pad(d.getHours()),
    mm: pad(d.getMinutes()),
    ss: pad(d.getSeconds())
  }
  return pattern.replace(/YYYY|MM|DD|HH|mm|ss/g, (token) => map[token])
}

/**
 * 仅取日期部分（YYYY-MM-DD）。
 */
export function formatDay(value) {
  return formatDate(value, 'YYYY-MM-DD')
}

// 兼容别名：部分页面（如 History）以 formatDateTime 引用「日期+时间」格式化。
export const formatDateTime = (value) => formatDate(value, 'YYYY-MM-DD HH:mm')

/* ============================================================
 * 八、其它小工具
 * ============================================================ */

/**
 * 安全解析 JSON 字符串；解析失败返回兜底值。
 * 后端某些字段以 JSON 字符串下发时使用。
 * @param {string} str
 * @param {*} fallback 默认 []
 */
export function safeJsonParse(str, fallback = []) {
  try {
    if (typeof str !== 'string') return str ?? fallback
    return JSON.parse(str)
  } catch {
    return fallback
  }
}

/**
 * 评分（1-5）→ 星级文本，便于在无 el-rate 处展示。
 */
export function ratingText(rating) {
  if (!rating) return '未评分'
  return '★'.repeat(rating) + '☆'.repeat(5 - rating)
}

/**
 * 优先级（高/中/低）→ el-tag 类型，供优化建议卡片使用。
 */
export function priorityTagType(priority) {
  const map = { 高: 'danger', 中: 'warning', 低: 'info' }
  return map[priority] || 'info'
}
