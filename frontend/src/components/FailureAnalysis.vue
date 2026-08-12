<script setup>
/**
 * FailureAnalysis.vue —— 失败归因分析组件（数据闭环的核心洞察区）
 * ----------------------------------------------------------------------------
 * 产品意图：
 *   「为什么失败」是数据闭环里最有价值的信息。本组件把后端 getFailures()
 *   的三类数据可视化，帮助 PM/运营快速定位主要失败模式，进而驱动优化：
 *     ① 失败原因 Top10 横向柱状图  —— 看「具体哪些原因最高频」
 *     ② 5 类失败占比饼图           —— 看「失败结构」（感知/理解/规划/执行/环境）
 *     ③ 5 类失败分类趋势堆叠面积图 —— 看「失败结构随时间的演化」
 *   交互：点击饼图某一分类（或图例），弹出该分类下的失败案例列表，
 *         实现「从宏观结构 → 下钻到具体任务」的分析动线。
 *
 * Props（数据来自 SPEC §8 GET /api/dashboard/failures）：
 *   failures = {
 *     top_reasons:   [{ reason, count }... 最多10],
 *     category_pie:  [{ category, count, color }... 5类],
 *     category_trend:{ dates:["MM-DD"...], series:[{ category, data:[...] }... 5类] }
 *   }
 *
 * 失败案例下钻：本组件不直接发请求，而是通过 getTasks 过滤拿到对应分类的案例，
 *   以保持组件「纯展示 + 自取下钻数据」的低耦合。父组件无需关心。
 */
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { getTasks } from '../api'

/**
 * 5 类失败分类配色表（来自 SPEC §5，前后端统一）。
 * 这里在组件内内联定义，使本组件不强依赖 utils/format 的具体导出名，
 * 保证「中文分类名 → 颜色」始终可用、颜色权威一致。
 */
const FAILURE_CATEGORIES = [
  { key: 'perception', name: '感知失败', color: '#5B8FF9' },
  { key: 'understanding', name: '理解失败', color: '#5AD8A6' },
  { key: 'planning', name: '规划失败', color: '#F6BD16' },
  { key: 'execution', name: '执行失败', color: '#E8684A' },
  { key: 'environment', name: '环境异常', color: '#9270CA' },
]

// 接收父组件传入的失败分析数据
const props = defineProps({
  failures: {
    type: Object,
    default: () => ({
      top_reasons: [],
      category_pie: [],
      category_trend: { dates: [], series: [] },
    }),
  },
})

/* -------------------------------------------------------------------------- */
/* 一、ECharts 实例与 DOM 引用                                                  */
/* -------------------------------------------------------------------------- */
// 三个图表容器的 DOM 引用
const reasonRef = ref(null) // 失败原因 Top10 横向柱状
const pieRef = ref(null) // 5 类占比饼图
const trendRef = ref(null) // 5 类分类趋势堆叠面积

// 三个 ECharts 实例（在 onMounted 初始化，onBeforeUnmount 销毁）
let reasonChart = null
let pieChart = null
let trendChart = null

/**
 * 5 类失败分类的「中文名 → 配色」映射（来自 SPEC §5，前后端统一）。
 * 后端 category_pie 已带 color 字段，但 trend 系列没有，这里做兜底映射，
 * 保证两张图同一分类颜色一致，专业且不误导。
 */
const CATEGORY_COLOR = FAILURE_CATEGORIES.reduce((map, item) => {
  map[item.name] = item.color
  return map
}, {})

// 统一 tooltip 样式：白底细边框圆角（规范 v1，三图共用）
const TOOLTIP = {
  backgroundColor: '#fff',
  borderColor: '#e5e7eb',
  borderWidth: 1,
  textStyle: { color: '#1f2937', fontSize: 12 },
  extraCssText: 'box-shadow: 0 4px 12px rgba(16,24,40,.10); border-radius: 8px;',
}

/* -------------------------------------------------------------------------- */
/* 二、失败案例下钻弹窗状态                                                       */
/* -------------------------------------------------------------------------- */
const drawerVisible = ref(false) // 弹窗显隐
const drawerCategory = ref('') // 当前下钻的分类中文名
const drawerLoading = ref(false) // 案例加载中
const caseList = ref([]) // 该分类的失败案例列表

/**
 * 打开失败案例下钻弹窗：
 *   通过 getTasks({ status:'failed' }) 拉取全部失败任务，再按 failure_category 过滤，
 *   避免后端额外接口；案例量级在演示场景下完全可接受。
 * @param {string} category 失败分类中文名（如「感知失败」）
 */
async function openCaseDrawer(category) {
  if (!category) return
  drawerCategory.value = category
  drawerVisible.value = true
  drawerLoading.value = true
  try {
    // 仅取失败任务，前端再按分类过滤
    const list = await getTasks({ status: 'failed' })
    caseList.value = (list || []).filter(
      (t) => t.failure_category === category
    )
  } catch (e) {
    // 拦截器已统一弹错误提示，这里兜底清空
    caseList.value = []
  } finally {
    drawerLoading.value = false
  }
}

/* -------------------------------------------------------------------------- */
/* 三、三个图表的 option 构造与渲染                                              */
/* -------------------------------------------------------------------------- */

/**
 * ① 失败原因 Top10 —— 横向条形图。
 *    横向更适合长文本原因标签；按 count 从小到大排列让最高频沉到顶部更醒目。
 */
function renderReasonChart() {
  if (!reasonChart) return
  // 后端可能已倒序，这里统一升序，使最大值显示在最上方
  const sorted = [...(props.failures.top_reasons || [])].sort(
    (a, b) => a.count - b.count
  )
  const names = sorted.map((i) => i.reason)
  const values = sorted.map((i) => i.count)

  reasonChart.setOption({
    tooltip: {
      ...TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      // 中文提示框
      formatter: (p) => `${p[0].name}<br/>失败次数：<b>${p[0].value}</b> 次`,
    },
    grid: { left: 8, right: 24, top: 10, bottom: 10, containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#6b7280' },
      splitLine: { lineStyle: { color: '#f0f2f5' } },
    },
    yAxis: {
      type: 'category',
      data: names,
      axisLabel: {
        color: '#374151',
        // 过长原因截断，hover 看完整 tooltip
        formatter: (v) => (v.length > 14 ? v.slice(0, 14) + '…' : v),
      },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
    },
    series: [
      {
        type: 'bar',
        data: values,
        barWidth: '55%',
        // 主色渐变柱，专业统一
        itemStyle: {
          borderRadius: [0, 6, 6, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: '#93c5fd' },
            { offset: 1, color: '#2563eb' },
          ]),
        },
        label: {
          show: true,
          position: 'right',
          color: '#6b7280',
          fontSize: 12,
        },
      },
    ],
  })
}

/**
 * ② 5 类失败占比 —— 环形饼图。
 *    使用 SPEC §5 的统一配色；点击扇区下钻该分类案例。
 */
function renderPieChart() {
  if (!pieChart) return
  const pieData = (props.failures.category_pie || []).map((i) => ({
    name: i.category,
    value: i.count,
    // 优先用后端给的颜色，兜底用本地映射
    itemStyle: { color: i.color || CATEGORY_COLOR[i.category] || '#909399' },
  }))

  pieChart.setOption({
    tooltip: {
      ...TOOLTIP,
      trigger: 'item',
      formatter: '{b}<br/>{c} 次（{d}%）',
    },
    legend: {
      orient: 'vertical',
      right: 8,
      top: 'center',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: '#374151', fontSize: 12 },
    },
    series: [
      {
        name: '失败分类占比',
        type: 'pie',
        // 环形：内外半径，留出中心便于阅读
        radius: ['42%', '68%'],
        center: ['38%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#fff', borderWidth: 2 },
        label: {
          show: true,
          formatter: '{d}%',
          color: '#374151',
          fontSize: 12,
        },
        labelLine: { length: 10, length2: 8 },
        data: pieData,
      },
    ],
  })

  // 点击扇区 → 下钻该分类案例
  pieChart.off('click')
  pieChart.on('click', (params) => openCaseDrawer(params.name))
}

/**
 * ③ 5 类失败分类趋势 —— 堆叠面积图。
 *    横轴为日期，每条系列一个失败分类，堆叠面积体现「总失败量 + 结构」随时间变化。
 */
function renderTrendChart() {
  if (!trendChart) return
  const trend = props.failures.category_trend || { dates: [], series: [] }
  const series = (trend.series || []).map((s) => ({
    name: s.category,
    type: 'line',
    stack: '失败总量', // 堆叠
    smooth: true,
    showSymbol: false,
    // 面积填充，分类配色半透明
    areaStyle: { opacity: 0.25 },
    lineStyle: { width: 2 },
    itemStyle: { color: CATEGORY_COLOR[s.category] || '#909399' },
    data: s.data,
  }))

  trendChart.setOption({
    tooltip: {
      ...TOOLTIP,
      trigger: 'axis',
      axisPointer: { type: 'line' },
    },
    legend: {
      top: 0,
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { color: '#374151', fontSize: 12 },
      data: series.map((s) => s.name),
    },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: trend.dates,
      axisLabel: { color: '#6b7280', fontSize: 11 },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
    },
    yAxis: {
      type: 'value',
      name: '失败次数',
      nameTextStyle: { color: '#9ca3af', fontSize: 11 },
      axisLabel: { color: '#6b7280' },
      splitLine: { lineStyle: { color: '#f0f2f5' } },
    },
    series,
  })

  // 点击趋势图图例区某系列也支持下钻（点击线上的点）
  trendChart.off('click')
  trendChart.on('click', (params) => openCaseDrawer(params.seriesName))
}

/** 统一渲染三张图 */
function renderAll() {
  renderReasonChart()
  renderPieChart()
  renderTrendChart()
}

/* -------------------------------------------------------------------------- */
/* 四、生命周期：初始化 / resize / 销毁（三个实例都要管理好）                       */
/* -------------------------------------------------------------------------- */

/** 窗口尺寸变化时让三张图自适应 */
function handleResize() {
  reasonChart && reasonChart.resize()
  pieChart && pieChart.resize()
  trendChart && trendChart.resize()
}

onMounted(async () => {
  // 等待 DOM 真正挂载后再初始化，避免容器宽高为 0
  await nextTick()
  reasonChart = echarts.init(reasonRef.value)
  pieChart = echarts.init(pieRef.value)
  trendChart = echarts.init(trendRef.value)
  renderAll()
  window.addEventListener('resize', handleResize)
})

// 数据变化时重渲染（父组件异步拿到数据后会更新 props）
watch(
  () => props.failures,
  () => renderAll(),
  { deep: true }
)

onBeforeUnmount(() => {
  // 移除监听并销毁三个实例，杜绝内存泄漏
  window.removeEventListener('resize', handleResize)
  reasonChart && reasonChart.dispose()
  pieChart && pieChart.dispose()
  trendChart && trendChart.dispose()
  reasonChart = pieChart = trendChart = null
})
</script>

<template>
  <div class="failure-analysis">
    <!-- 上半区：左侧失败原因 Top10、右侧 5 类占比饼图 -->
    <div class="failure-analysis__row">
      <div class="failure-analysis__panel">
        <div class="failure-analysis__panel-title">
          失败原因 Top10
          <span class="failure-analysis__panel-sub">高频失败原因排行</span>
        </div>
        <div ref="reasonRef" class="failure-analysis__chart"></div>
      </div>

      <div class="failure-analysis__panel">
        <div class="failure-analysis__panel-title">
          5 类失败占比
          <span class="failure-analysis__panel-sub">点击扇区查看案例</span>
        </div>
        <div ref="pieRef" class="failure-analysis__chart"></div>
      </div>
    </div>

    <!-- 下半区：5 类失败分类趋势（堆叠面积）-->
    <div class="failure-analysis__panel failure-analysis__panel--full">
      <div class="failure-analysis__panel-title">
        失败分类趋势
        <span class="failure-analysis__panel-sub"
          >近 30 天各类失败的演化（堆叠）</span
        >
      </div>
      <div ref="trendRef" class="failure-analysis__chart failure-analysis__chart--wide"></div>
    </div>

    <!-- 失败案例下钻弹窗 -->
    <el-drawer
      v-model="drawerVisible"
      :title="`「${drawerCategory}」失败案例`"
      direction="rtl"
      size="46%"
    >
      <div v-loading="drawerLoading" class="case-drawer">
        <el-empty
          v-if="!drawerLoading && caseList.length === 0"
          description="该分类暂无失败案例"
        />
        <div
          v-for="item in caseList"
          :key="item.id"
          class="case-item"
        >
          <div class="case-item__head">
            <el-tag size="small" type="info">#{{ item.id }}</el-tag>
            <el-tag size="small">{{ item.task_type }}</el-tag>
            <span class="case-item__time">{{ item.created_at }}</span>
          </div>
          <div class="case-item__instruction">{{ item.instruction }}</div>
          <div class="case-item__meta">
            <span>策略：{{ item.strategy === 'llm' ? '大模型' : '规则' }}</span>
            <span>步骤：{{ item.step_count }}</span>
            <span>耗时：{{ item.total_duration_ms }} ms</span>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.failure-analysis {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 上半区两列等宽 */
.failure-analysis__row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

/* 单个图表面板：嵌套在区块卡片内，用细边框区分层级（避免阴影套阴影） */
.failure-analysis__panel {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  padding: 16px;
}
.failure-analysis__panel--full {
  width: 100%;
}

.failure-analysis__panel-title {
  font-size: 15px;
  font-weight: 600;
  color: #1f2d3d;
  margin-bottom: 8px;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.failure-analysis__panel-sub {
  font-size: 12px;
  font-weight: 400;
  color: #9ca3af;
}

/* 图表高度 */
.failure-analysis__chart {
  width: 100%;
  height: 280px;
}
.failure-analysis__chart--wide {
  height: 300px;
}

/* 案例弹窗 */
.case-drawer {
  min-height: 200px;
}
.case-item {
  padding: 12px 14px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  margin-bottom: 10px;
  transition: box-shadow 0.2s ease;
}
.case-item:hover {
  box-shadow: var(--shadow-hover);
}
.case-item__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.case-item__time {
  margin-left: auto;
  font-size: 12px;
  color: #9ca3af;
}
.case-item__instruction {
  font-size: 14px;
  color: #1f2d3d;
  margin-bottom: 6px;
  line-height: 1.5;
}
.case-item__meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #6b7280;
}
</style>
