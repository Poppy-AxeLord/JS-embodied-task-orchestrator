<script setup>
/**
 * Dashboard.vue —— 数据看板页（项目最能体现 PM 能力的页面）
 * ============================================================================
 * 产品意图：
 *   这是「数据闭环系统」的驾驶舱。它把任务编排平台运行后沉淀的数据，按
 *   「指标体系分层 → 趋势 → 失败归因 → 任务分析 → 策略对比 → 优化建议」
 *   的逻辑层层展开，回答四个核心问题：
 *     1) 现在做得怎么样？（顶部 4 张指标卡 + 指标体系分层）
 *     2) 趋势好不好？      （近 30 天任务量 + 成功率 双 Y 轴图）
 *     3) 为什么会失败？    （FailureAnalysis 失败归因）
 *     4) 哪里能优化？      （任务分析 + 策略对比 + 优化建议清单）
 *   每一块都直接对应一个后端聚合接口（SPEC §8），形成「数据 → 洞察 → 行动」闭环。
 *
 * 技术要点（SPEC §13）：
 *   - 所有 ECharts 用 ref + onMounted 初始化；window resize 时 chart.resize()；
 *     组件卸载时 dispose()，统一在 chartRegistry 里集中管理，杜绝内存泄漏。
 *   - 配色专业统一，主色 #2563EB；中文图例与中文提示框。
 *   - 不固定 devicePixelRatio，让 ECharts 自适应 Retina。
 */
import { ref, reactive, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts'
import { Refresh } from '@element-plus/icons-vue'
import MetricCard from '../components/MetricCard.vue'
import FailureAnalysis from '../components/FailureAnalysis.vue'
import {
  getOverview,
  getFailures,
  getTasksAnalysis,
  getStrategyCompare,
  getSuggestions,
} from '../api'

/* ========================================================================== */
/* 一、统一的图表生命周期管理                                                    */
/* ========================================================================== */
/**
 * chartRegistry：集中登记本页所有 ECharts 实例。
 * 这样 resize / dispose 只需遍历一次，避免漏管理某个实例造成泄漏或不自适应。
 * key 为图表语义名，value 为 echarts 实例。
 */
const chartRegistry = {}

/** 注册并初始化一个图表实例 */
function initChart(key, domEl) {
  if (!domEl) return null
  // 若已存在先释放，避免热更新时重复 init
  if (chartRegistry[key]) {
    chartRegistry[key].dispose()
  }
  const inst = echarts.init(domEl)
  chartRegistry[key] = inst
  return inst
}

/** 窗口尺寸变化 → 所有图表自适应 */
function handleResize() {
  Object.values(chartRegistry).forEach((c) => c && c.resize())
}

/* ========================================================================== */
/* 二、各区块响应式数据                                                          */
/* ========================================================================== */
// 加载态（首屏整页 loading）
const loading = ref(true)

// ① 顶部指标卡数据（来自 getOverview().cards）
const cards = reactive({
  total_tasks: 0,
  success_rate: 0,
  avg_duration_ms: 0,
  satisfaction: 0,
})

// ① 指标体系分层（来自 getOverview().metrics）：北极星 / 过程 / 结果
const metrics = reactive({
  polaris: { name: '任务成功率', value: 0, unit: '%' },
  process: [],
  result: [],
})

// ⑤ 优化建议列表（来自 getSuggestions）
const suggestions = ref([])

// DOM 引用：每张图一个 ref（onMounted 后初始化）
const trendRef = ref(null) // ① 近30天趋势：任务量柱 + 成功率折线（双Y轴）
const topTasksRef = ref(null) // ③ 高频任务 Top20 横向条形
const typeSuccessRef = ref(null) // ③ 各 type 成功率柱状
const difficultyRef = ref(null) // ③ 难度分布饼图
const strategySuccessRef = ref(null) // ④ 策略成功率柱状
const strategyDurationRef = ref(null) // ④ 策略平均耗时柱状
const strategyRadarRef = ref(null) // ④ 策略多维雷达

// FailureAnalysis 子组件的数据（② 区块，来自 getFailures）
const failures = ref({
  top_reasons: [],
  category_pie: [],
  category_trend: { dates: [], series: [] },
})

/* ========================================================================== */
/* 三、统一配色与小工具                                                          */
/* ========================================================================== */
// 主色与配套色板，保证全页图表视觉统一、专业
const COLOR = {
  primary: '#2563EB', // 企业蓝主色
  primaryLight: '#93C5FD',
  green: '#10B981', // 成功正向（语义色 token）
  amber: '#F59E0B',
  axis: '#6b7280',
  split: '#f3f4f6',
}
// 统一 tooltip 样式：白底细边框圆角（规范 v1，各图共用）
const TOOLTIP = {
  backgroundColor: '#fff',
  borderColor: '#e5e7eb',
  borderWidth: 1,
  textStyle: { color: '#1f2937', fontSize: 12 },
  extraCssText: 'box-shadow: 0 4px 12px rgba(16,24,40,.10); border-radius: 8px;',
}
// 难度分布饼图配色（简单/中等/困难，由浅到深体现难度递增）
const DIFFICULTY_COLOR = { 简单: '#5AD8A6', 中等: '#F6BD16', 困难: '#E8684A' }

/** 毫秒 → 友好显示（秒，保留 1 位）用于指标卡 */
function msToSec(ms) {
  return (Number(ms || 0) / 1000).toFixed(1)
}
/** 0-1 小数 → 百分比字符串（1 位小数） */
function toPercent(rate) {
  return (Number(rate || 0) * 100).toFixed(1)
}

/* ========================================================================== */
/* 四、各图表 option 渲染函数                                                     */
/* ========================================================================== */

/**
 * ① 近 30 天趋势：双 Y 轴。
 *    左轴 = 任务量（柱状）；右轴 = 成功率（折线，0-100%）。
 *    这是看板最重要的一张图：同时回答「量在涨吗」和「质在升吗」。
 */
function renderTrend(trend) {
  const inst = initChart('trend', trendRef.value)
  if (!inst) return
  // 成功率转百分比展示
  const rates = (trend.success_rates || []).map((r) => +(r * 100).toFixed(1))
  inst.setOption({
    tooltip: {
      ...TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      // 中文提示框：分别展示任务量与成功率
      formatter: (params) => {
        const date = params[0].axisValue
        let html = `${date}<br/>`
        params.forEach((p) => {
          const val =
            p.seriesName === '成功率' ? `${p.value}%` : `${p.value} 个`
          html += `${p.marker}${p.seriesName}：<b>${val}</b><br/>`
        })
        return html
      },
    },
    legend: {
      data: ['任务量', '成功率'],
      top: 0,
      textStyle: { color: '#374151' },
    },
    grid: { left: 8, right: 8, top: 40, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: trend.dates || [],
      axisLabel: { color: COLOR.axis, fontSize: 11 },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
    },
    yAxis: [
      {
        // 左轴：任务量
        type: 'value',
        name: '任务量',
        nameTextStyle: { color: '#9ca3af', fontSize: 11 },
        axisLabel: { color: COLOR.axis },
        splitLine: { lineStyle: { color: COLOR.split } },
      },
      {
        // 右轴：成功率（固定 0-100，便于跨日期对比）
        type: 'value',
        name: '成功率',
        min: 0,
        max: 100,
        nameTextStyle: { color: '#9ca3af', fontSize: 11 },
        axisLabel: { color: COLOR.axis, formatter: '{value}%' },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '任务量',
        type: 'bar',
        yAxisIndex: 0,
        barWidth: '50%',
        data: trend.task_counts || [],
        itemStyle: {
          borderRadius: [4, 4, 0, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: COLOR.primary },
            { offset: 1, color: COLOR.primaryLight },
          ]),
        },
      },
      {
        name: '成功率',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        data: rates,
        lineStyle: { width: 3, color: COLOR.green },
        itemStyle: { color: COLOR.green },
        // 折线下方淡淡面积，强调趋势
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(16,185,129,0.16)' },
            { offset: 1, color: 'rgba(16,185,129,0.02)' },
          ]),
        },
      },
    ],
  })
}

/**
 * ③-a 高频任务 Top20 —— 横向条形图（柱长=出现次数，颜色按成功率梯度）。
 *      让 PM 一眼看到「最常被下达的指令」及其成功率好坏。
 */
function renderTopTasks(list) {
  const inst = initChart('topTasks', topTasksRef.value)
  if (!inst) return
  // 升序，最高频在顶部
  const sorted = [...(list || [])].sort((a, b) => a.count - b.count)
  inst.setOption({
    tooltip: {
      ...TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (p) => {
        const d = sorted[p[0].dataIndex]
        return `${d.instruction}<br/>出现：<b>${d.count}</b> 次<br/>成功率：<b>${toPercent(
          d.success_rate
        )}%</b>`
      },
    },
    grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: { color: COLOR.axis },
      splitLine: { lineStyle: { color: COLOR.split } },
    },
    yAxis: {
      type: 'category',
      data: sorted.map((i) => i.instruction),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
      axisLabel: {
        color: '#374151',
        fontSize: 11,
        // 指令较长，截断显示，完整看 tooltip
        formatter: (v) => (v.length > 16 ? v.slice(0, 16) + '…' : v),
      },
    },
    series: [
      {
        type: 'bar',
        barWidth: '60%',
        data: sorted.map((i) => ({
          value: i.count,
          // 成功率高→绿，低→红，体现质量差异
          itemStyle: {
            borderRadius: [0, 4, 4, 0],
            color:
              i.success_rate >= 0.8
                ? '#5AD8A6'
                : i.success_rate >= 0.6
                ? '#F6BD16'
                : '#E8684A',
          },
        })),
      },
    ],
  })
}

/**
 * ③-b 各任务类型成功率 —— 柱状图（含总数 tooltip）。
 *      帮助定位「哪类任务最不稳定」，指导能力补强方向。
 */
function renderTypeSuccess(list) {
  const inst = initChart('typeSuccess', typeSuccessRef.value)
  if (!inst) return
  const types = (list || []).map((i) => i.task_type)
  const rates = (list || []).map((i) => +(i.success_rate * 100).toFixed(1))
  inst.setOption({
    tooltip: {
      ...TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (p) => {
        const d = list[p[0].dataIndex]
        return `${d.task_type}<br/>成功率：<b>${p[0].value}%</b><br/>样本数：${d.total} 个`
      },
    },
    grid: { left: 8, right: 8, top: 16, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: types,
      axisLabel: { color: COLOR.axis },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: COLOR.axis, formatter: '{value}%' },
      splitLine: { lineStyle: { color: COLOR.split } },
    },
    series: [
      {
        type: 'bar',
        barWidth: '45%',
        data: rates,
        itemStyle: {
          borderRadius: [4, 4, 0, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: COLOR.primary },
            { offset: 1, color: COLOR.primaryLight },
          ]),
        },
        label: {
          show: true,
          position: 'top',
          formatter: '{c}%',
          color: COLOR.axis,
          fontSize: 11,
        },
      },
    ],
  })
}

/**
 * ③-c 难度分布 —— 环形饼图（简单/中等/困难）。
 *      反映样本难度结构，结合成功率可解读「难度是否拖累整体表现」。
 */
function renderDifficulty(list) {
  const inst = initChart('difficulty', difficultyRef.value)
  if (!inst) return
  inst.setOption({
    tooltip: { ...TOOLTIP, trigger: 'item', formatter: '{b}<br/>{c} 个（{d}%）' },
    legend: {
      bottom: 0,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: '#374151', fontSize: 12 },
    },
    series: [
      {
        name: '难度分布',
        type: 'pie',
        radius: ['40%', '66%'],
        center: ['50%', '44%'],
        itemStyle: { borderColor: '#fff', borderWidth: 2 },
        label: { formatter: '{b}\n{d}%', color: '#374151', fontSize: 12 },
        data: (list || []).map((i) => ({
          name: i.difficulty,
          value: i.count,
          itemStyle: { color: DIFFICULTY_COLOR[i.difficulty] || '#909399' },
        })),
      },
    ],
  })
}

/**
 * ④-a 策略成功率对比 —— 柱状图（llm vs rule）。
 */
function renderStrategySuccess(list) {
  const inst = initChart('strategySuccess', strategySuccessRef.value)
  if (!inst) return
  inst.setOption({
    tooltip: {
      ...TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (p) => `${p[0].name}<br/>成功率：<b>${p[0].value}%</b>`,
    },
    grid: { left: 8, right: 8, top: 16, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: (list || []).map((i) => strategyLabel(i.strategy)),
      axisLabel: { color: COLOR.axis },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: COLOR.axis, formatter: '{value}%' },
      splitLine: { lineStyle: { color: COLOR.split } },
    },
    series: [
      {
        type: 'bar',
        barWidth: '40%',
        data: (list || []).map((i, idx) => ({
          value: +(i.success_rate * 100).toFixed(1),
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: idx === 0 ? COLOR.primary : '#5AD8A6',
          },
        })),
        label: {
          show: true,
          position: 'top',
          formatter: '{c}%',
          color: COLOR.axis,
        },
      },
    ],
  })
}

/**
 * ④-b 策略平均耗时对比 —— 柱状图（毫秒）。
 */
function renderStrategyDuration(list) {
  const inst = initChart('strategyDuration', strategyDurationRef.value)
  if (!inst) return
  inst.setOption({
    tooltip: {
      ...TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (p) => `${p[0].name}<br/>平均耗时：<b>${p[0].value} ms</b>`,
    },
    grid: { left: 8, right: 8, top: 16, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: (list || []).map((i) => strategyLabel(i.strategy)),
      axisLabel: { color: COLOR.axis },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
    },
    yAxis: {
      type: 'value',
      name: 'ms',
      nameTextStyle: { color: '#9ca3af', fontSize: 11 },
      axisLabel: { color: COLOR.axis },
      splitLine: { lineStyle: { color: COLOR.split } },
    },
    series: [
      {
        type: 'bar',
        barWidth: '40%',
        data: (list || []).map((i, idx) => ({
          value: i.avg_duration_ms,
          itemStyle: {
            borderRadius: [4, 4, 0, 0],
            color: idx === 0 ? COLOR.primary : '#5AD8A6',
          },
        })),
        label: {
          show: true,
          position: 'top',
          formatter: '{c}',
          color: COLOR.axis,
        },
      },
    ],
  })
}

/**
 * ④-c 策略多维雷达 —— 成功率 / 速度 / 稳定性 / 步骤精简度 / 满意度。
 *      一张图横向比较两种拆解策略的「综合能力画像」，是策略选型的关键依据。
 */
function renderStrategyRadar(radar) {
  const inst = initChart('strategyRadar', strategyRadarRef.value)
  if (!inst) return
  const indicators = radar.indicators || []
  const series = radar.series || []
  inst.setOption({
    tooltip: { ...TOOLTIP, trigger: 'item' },
    legend: {
      data: series.map((s) => strategyLabel(s.strategy)),
      bottom: 0,
      textStyle: { color: '#374151' },
    },
    radar: {
      indicator: indicators,
      radius: '62%',
      center: ['50%', '46%'],
      axisName: { color: '#6b7280', fontSize: 12 },
      splitLine: { lineStyle: { color: '#e5e7eb' } },
      splitArea: { areaStyle: { color: ['#fafbfc', '#fff'] } },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
    },
    series: [
      {
        type: 'radar',
        data: series.map((s, idx) => ({
          name: strategyLabel(s.strategy),
          value: s.data,
          symbolSize: 4,
          lineStyle: { width: 2 },
          areaStyle: { opacity: 0.18 },
          itemStyle: { color: idx === 0 ? COLOR.primary : '#5AD8A6' },
        })),
      },
    ],
  })
}

/** 策略英文 → 中文标签 */
function strategyLabel(s) {
  return s === 'llm' ? '大模型策略' : s === 'rule' ? '规则策略' : s
}

/** 优化建议优先级 → Element Plus 标签类型（彩色） */
function priorityTagType(p) {
  return p === '高' ? 'danger' : p === '中' ? 'warning' : 'info'
}

/* ========================================================================== */
/* 五、数据加载与初始化                                                          */
/* ========================================================================== */
/**
 * 并行拉取 5 个看板接口，拿到数据后再统一初始化图表。
 * 注意：图表 DOM 在 v-loading 撤掉后才真正有宽高，
 *       故先 loading=false → nextTick → 再 init，避免容器宽高为 0。
 */
async function loadAll() {
  loading.value = true
  try {
    // 并行请求，提升首屏速度（拦截器已统一处理错误提示）
    const [ov, fa, ta, sc, sg] = await Promise.all([
      getOverview(),
      getFailures(),
      getTasksAnalysis(),
      getStrategyCompare(),
      getSuggestions(),
    ])

    // ① 顶部卡片 + 指标体系
    Object.assign(cards, ov.cards || {})
    Object.assign(metrics, ov.metrics || {})

    // ② 失败分析数据（透传给子组件）
    failures.value = fa || failures.value

    // ⑤ 优化建议
    suggestions.value = sg || []

    // 关闭 loading 让容器获得真实尺寸，再渲染图表
    loading.value = false
    await nextTick()

    // ① 趋势图
    renderTrend(ov.trend || {})
    // ③ 任务分析三图
    renderTopTasks(ta.top_tasks)
    renderTypeSuccess(ta.type_success)
    renderDifficulty(ta.difficulty_dist)
    // ④ 策略对比三图
    renderStrategySuccess(sc.success)
    renderStrategyDuration(sc.duration)
    renderStrategyRadar(sc.radar || { indicators: [], series: [] })
  } catch (e) {
    // 接口失败时关闭 loading，错误提示由 axios 拦截器统一弹出
    loading.value = false
  }
}

onMounted(() => {
  loadAll()
  // 窗口尺寸变化时所有图自适应（Retina 由 echarts 自身处理，不固定 dpr）
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  // 移除监听并销毁所有图表实例，防止内存泄漏
  window.removeEventListener('resize', handleResize)
  Object.keys(chartRegistry).forEach((k) => {
    chartRegistry[k] && chartRegistry[k].dispose()
    delete chartRegistry[k]
  })
})
</script>

<template>
  <div class="dashboard" v-loading="loading">
    <!-- 页头 -->
    <div class="dashboard__page-head">
      <div>
        <h2 class="dashboard__title">数据看板</h2>
        <p class="dashboard__subtitle">
          任务编排数据闭环驾驶舱 · 指标体系 → 趋势 → 失败归因 → 任务分析 →
          策略对比 → 优化建议
        </p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新数据</el-button>
    </div>

    <!-- ===================== ① 顶部 4 张指标卡 ===================== -->
    <div class="dashboard__cards">
      <MetricCard
        title="总任务数"
        :value="cards.total_tasks"
        unit="个"
        icon="📊"
      />
      <MetricCard
        title="总成功率"
        :value="toPercent(cards.success_rate)"
        unit="%"
        icon="✅"
      />
      <MetricCard
        title="平均执行时长"
        :value="msToSec(cards.avg_duration_ms)"
        unit="秒"
        icon="⏱️"
      />
      <MetricCard
        title="用户满意度"
        :value="Number(cards.satisfaction || 0).toFixed(2)"
        unit="/ 5"
        icon="⭐"
      />
    </div>

    <!-- ===================== 指标体系分层 ===================== -->
    <el-card shadow="never" class="dashboard__section">
      <template #header>
        <div class="dashboard__section-head">
          <span class="dashboard__section-title">指标体系分层</span>
          <span class="dashboard__section-sub"
            >北极星指标驱动过程指标与结果指标，构成可迭代的度量闭环</span
          >
        </div>
      </template>

      <div class="metrics-layers">
        <!-- 北极星指标：单独高亮 -->
        <div class="metrics-layers__polaris">
          <div class="metrics-layers__polaris-label">北极星指标</div>
          <div class="metrics-layers__polaris-name">{{ metrics.polaris.name }}</div>
          <div class="metrics-layers__polaris-value">
            {{ Number(metrics.polaris.value || 0) }}
            <span class="metrics-layers__polaris-unit">{{ metrics.polaris.unit }}</span>
          </div>
        </div>

        <!-- 过程指标 + 结果指标 两组 -->
        <div class="metrics-layers__groups">
          <div class="metrics-layers__group">
            <div class="metrics-layers__group-title metrics-layers__group-title--process">
              过程指标
            </div>
            <div class="metrics-layers__chips">
              <div
                v-for="(m, i) in metrics.process"
                :key="'p' + i"
                class="metric-chip"
              >
                <span class="metric-chip__name">{{ m.name }}</span>
                <span class="metric-chip__value">{{ m.value }}{{ m.unit }}</span>
              </div>
            </div>
          </div>

          <div class="metrics-layers__group">
            <div class="metrics-layers__group-title metrics-layers__group-title--result">
              结果指标
            </div>
            <div class="metrics-layers__chips">
              <div
                v-for="(m, i) in metrics.result"
                :key="'r' + i"
                class="metric-chip"
              >
                <span class="metric-chip__name">{{ m.name }}</span>
                <span class="metric-chip__value">{{ m.value }}{{ m.unit }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- ===================== ① 近 30 天趋势 ===================== -->
    <el-card shadow="never" class="dashboard__section">
      <template #header>
        <div class="dashboard__section-head">
          <span class="dashboard__section-title">近 30 天趋势</span>
          <span class="dashboard__section-sub"
            >任务量（柱）与成功率（折线）双 Y 轴 · 同时关注「量」与「质」</span
          >
        </div>
      </template>
      <div ref="trendRef" class="chart chart--trend"></div>
    </el-card>

    <!-- ===================== ② 失败归因分析 ===================== -->
    <el-card shadow="never" class="dashboard__section">
      <template #header>
        <div class="dashboard__section-head">
          <span class="dashboard__section-title">失败归因分析</span>
          <span class="dashboard__section-sub"
            >Top10 失败原因 · 5 类失败结构 · 失败趋势 · 点击下钻案例</span
          >
        </div>
      </template>
      <FailureAnalysis :failures="failures" />
    </el-card>

    <!-- ===================== ③ 任务分析 ===================== -->
    <el-card shadow="never" class="dashboard__section">
      <template #header>
        <div class="dashboard__section-head">
          <span class="dashboard__section-title">任务分析</span>
          <span class="dashboard__section-sub"
            >高频指令 · 各类型成功率 · 难度结构</span
          >
        </div>
      </template>
      <div class="tasks-analysis">
        <!-- 高频任务 Top20 占整行较宽，单独一栏 -->
        <div class="tasks-analysis__main">
          <div class="chart-title">高频任务 Top20</div>
          <div ref="topTasksRef" class="chart chart--tall"></div>
        </div>
        <!-- 右侧上下两图：类型成功率 + 难度分布 -->
        <div class="tasks-analysis__side">
          <div class="tasks-analysis__side-item">
            <div class="chart-title">各任务类型成功率</div>
            <div ref="typeSuccessRef" class="chart chart--mid"></div>
          </div>
          <div class="tasks-analysis__side-item">
            <div class="chart-title">任务难度分布</div>
            <div ref="difficultyRef" class="chart chart--mid"></div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- ===================== ④ 策略对比 ===================== -->
    <el-card shadow="never" class="dashboard__section">
      <template #header>
        <div class="dashboard__section-head">
          <span class="dashboard__section-title">策略对比</span>
          <span class="dashboard__section-sub"
            >大模型策略 vs 规则策略 · 成功率 / 耗时 / 综合能力画像</span
          >
        </div>
      </template>
      <div class="strategy-compare">
        <div class="strategy-compare__item">
          <div class="chart-title">成功率对比</div>
          <div ref="strategySuccessRef" class="chart chart--mid"></div>
        </div>
        <div class="strategy-compare__item">
          <div class="chart-title">平均耗时对比</div>
          <div ref="strategyDurationRef" class="chart chart--mid"></div>
        </div>
        <div class="strategy-compare__item">
          <div class="chart-title">综合能力雷达</div>
          <div ref="strategyRadarRef" class="chart chart--mid"></div>
        </div>
      </div>
    </el-card>

    <!-- ===================== ⑤ 优化建议 ===================== -->
    <el-card shadow="never" class="dashboard__section">
      <template #header>
        <div class="dashboard__section-head">
          <span class="dashboard__section-title">优化建议</span>
          <span class="dashboard__section-sub"
            >由数据自动生成 · 带优先级与数据支撑 · 驱动下一轮迭代</span
          >
        </div>
      </template>

      <el-empty
        v-if="suggestions.length === 0"
        description="暂无优化建议（数据积累后自动生成）"
      />
      <div v-else class="suggestions">
        <div
          v-for="(s, i) in suggestions"
          :key="i"
          class="suggestion-card"
          :class="`suggestion-card--${priorityTagType(s.priority)}`"
        >
          <div class="suggestion-card__head">
            <el-tag
              :type="priorityTagType(s.priority)"
              effect="dark"
              size="small"
            >
              {{ s.priority }}优先级
            </el-tag>
            <span class="suggestion-card__title">{{ s.title }}</span>
            <el-tag
              v-if="s.metric"
              size="small"
              type="info"
              effect="plain"
              class="suggestion-card__metric"
            >
              {{ s.metric }}
            </el-tag>
          </div>
          <div class="suggestion-card__detail">{{ s.detail }}</div>
          <div v-if="s.evidence" class="suggestion-card__evidence">
            <span class="suggestion-card__evidence-label">数据支撑</span>
            {{ s.evidence }}
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 16px;
  /* 浅灰底由全局给出，此处仅排布卡片 */
}

/* 页头 */
.dashboard__page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}
.dashboard__title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}
.dashboard__subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: #6b7280;
}

/* 顶部指标卡四列网格 */
.dashboard__cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

/* 区块卡片：圆角与阴影统一走全局设计 token（global.css 的 .el-card 覆盖） */
.dashboard__section {
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
}
.dashboard__section-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.dashboard__section-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f2d3d;
  position: relative;
  padding-left: 12px;
}
/* 标题前的主色竖条 */
.dashboard__section-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 2px;
  bottom: 2px;
  width: 4px;
  border-radius: 2px;
  background: #2563eb;
}
.dashboard__section-sub {
  font-size: 12px;
  color: #9ca3af;
}

/* ----- 指标体系分层 ----- */
.metrics-layers {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 20px;
  align-items: stretch;
}
.metrics-layers__polaris {
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
  border-radius: 12px;
  padding: 18px 20px;
  color: #fff;
  display: flex;
  flex-direction: column;
  justify-content: center;
  box-shadow: 0 6px 18px rgba(37, 99, 235, 0.25);
}
.metrics-layers__polaris-label {
  font-size: 12px;
  opacity: 0.85;
  letter-spacing: 1px;
}
.metrics-layers__polaris-name {
  font-size: 16px;
  font-weight: 600;
  margin-top: 6px;
}
.metrics-layers__polaris-value {
  font-size: 34px;
  font-weight: 800;
  margin-top: 8px;
  font-variant-numeric: tabular-nums;
}
.metrics-layers__polaris-unit {
  font-size: 16px;
  font-weight: 500;
  opacity: 0.9;
}

.metrics-layers__groups {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.metrics-layers__group-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  padding-left: 10px;
  position: relative;
}
.metrics-layers__group-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 1px;
  bottom: 1px;
  width: 3px;
  border-radius: 2px;
}
.metrics-layers__group-title--process {
  color: #2563eb;
}
.metrics-layers__group-title--process::before {
  background: #2563eb;
}
.metrics-layers__group-title--result {
  color: var(--success);
}
.metrics-layers__group-title--result::before {
  background: var(--success);
}
.metrics-layers__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.metric-chip {
  background: #f7f9fc;
  border: 1px solid #eef0f4;
  border-radius: 8px;
  padding: 8px 14px;
  display: flex;
  flex-direction: column;
  min-width: 120px;
}
.metric-chip__name {
  font-size: 12px;
  color: #6b7280;
}
.metric-chip__value {
  font-size: 18px;
  font-weight: 700;
  color: #1f2d3d;
  margin-top: 2px;
  font-variant-numeric: tabular-nums;
}

/* ----- 图表通用尺寸 ----- */
.chart {
  width: 100%;
}
.chart--trend {
  height: 320px;
}
.chart--tall {
  height: 460px;
}
.chart--mid {
  height: 260px;
}
.chart-title {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 6px;
}

/* ----- 任务分析布局：左宽右窄(两图堆叠) ----- */
.tasks-analysis {
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: 18px;
}
.tasks-analysis__side {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ----- 策略对比三列 ----- */
.strategy-compare {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}

/* ----- 优化建议卡片 ----- */
.suggestions {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 14px;
}
.suggestion-card {
  background: #fff;
  border: 1px solid #eef0f4;
  border-left-width: 4px;
  border-radius: 10px;
  padding: 14px 16px;
  transition: box-shadow 0.2s;
}
.suggestion-card:hover {
  box-shadow: 0 4px 14px rgba(31, 45, 61, 0.08);
}
/* 左侧色条按优先级着色 */
.suggestion-card--danger {
  border-left-color: #f56c6c;
}
.suggestion-card--warning {
  border-left-color: #e6a23c;
}
.suggestion-card--info {
  border-left-color: #909399;
}
.suggestion-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.suggestion-card__title {
  font-size: 15px;
  font-weight: 600;
  color: #1f2d3d;
}
.suggestion-card__metric {
  margin-left: auto;
}
.suggestion-card__detail {
  font-size: 13px;
  color: #4b5563;
  line-height: 1.6;
  margin-bottom: 8px;
}
.suggestion-card__evidence {
  font-size: 12px;
  color: #6b7280;
  background: #f7f9fc;
  border-radius: 6px;
  padding: 8px 10px;
  line-height: 1.5;
}
.suggestion-card__evidence-label {
  display: inline-block;
  font-weight: 600;
  color: #2563eb;
  margin-right: 6px;
}

/* 响应式：窄屏时网格降列，保证密度与可读性 */
@media (max-width: 1280px) {
  .dashboard__cards {
    grid-template-columns: repeat(2, 1fr);
  }
  .strategy-compare {
    grid-template-columns: 1fr;
  }
  .tasks-analysis {
    grid-template-columns: 1fr;
  }
  .metrics-layers {
    grid-template-columns: 1fr;
  }
}
</style>
