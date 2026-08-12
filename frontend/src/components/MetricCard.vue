<script setup>
/**
 * MetricCard.vue —— 专业指标卡组件
 * ----------------------------------------------------------------------------
 * 产品意图：
 *   看板顶部用 4 张指标卡承载「最关键的 4 个数字」（总任务数 / 总成功率 /
 *   平均执行时长 / 用户满意度）。指标卡是 B 端数据看板的「第一视觉焦点」，
 *   需要做到：大数字一眼可见、单位清晰、图标辅助语义、可选趋势小标体现环比。
 *
 * Props（与 SPEC §13 一致）：
 *   - title  指标名称，如「总任务数」
 *   - value  指标数值（已由父组件格式化好的字符串或数字）
 *   - unit   单位，如「次」「%」「ms」「分」，可为空
 *   - icon   图标，传入 emoji 字符串（如 "📊"），矢量友好、Retina 清晰
 *   - trend  可选趋势对象 { type:'up'|'down'|'flat', text:'较上周 +12%' }
 *            其中 type 决定颜色（涨绿、跌红、平灰），text 为展示文案
 */
defineProps({
  // 指标标题
  title: { type: String, required: true },
  // 主数值（父组件已格式化，组件内不再做数学运算，保持纯展示）
  value: { type: [String, Number], required: true },
  // 单位（可选）
  unit: { type: String, default: '' },
  // 图标 emoji（可选）
  icon: { type: String, default: '📈' },
  // 趋势小标（可选）：{ type, text }
  trend: {
    type: Object,
    default: null,
    // 形如 { type: 'up' | 'down' | 'flat', text: '较上周 +5.2%' }
  },
})
</script>

<template>
  <!-- 指标卡：白底、圆角、阴影，主色点缀左侧色条 -->
  <div class="metric-card">
    <!-- 左侧主色装饰条，强化企业级专业感 -->
    <div class="metric-card__accent"></div>

    <div class="metric-card__body">
      <!-- 头部：标题 + 右上角图标 -->
      <div class="metric-card__header">
        <span class="metric-card__title">{{ title }}</span>
        <span class="metric-card__icon">{{ icon }}</span>
      </div>

      <!-- 主数值区：大号数字 + 单位 -->
      <div class="metric-card__value-row">
        <span class="metric-card__value">{{ value }}</span>
        <span v-if="unit" class="metric-card__unit">{{ unit }}</span>
      </div>

      <!-- 趋势小标（可选）：根据 trend.type 着色 -->
      <div
        v-if="trend"
        class="metric-card__trend"
        :class="`metric-card__trend--${trend.type}`"
      >
        <!-- 趋势箭头：涨↑ 跌↓ 平→ -->
        <span class="metric-card__trend-arrow">
          {{ trend.type === 'up' ? '↑' : trend.type === 'down' ? '↓' : '→' }}
        </span>
        <span class="metric-card__trend-text">{{ trend.text }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 卡片容器：白底圆角阴影，hover 时轻微抬升，体现可交互的高级质感 */
.metric-card {
  position: relative;
  display: flex;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  /* 轻阴影 token，Retina 下边缘干净 */
  box-shadow: var(--shadow-card);
  overflow: hidden;
  transition: all 0.2s ease;
}
.metric-card:hover {
  box-shadow: var(--shadow-hover);
  transform: translateY(-1px);
}

/* 左侧主色装饰条 */
.metric-card__accent {
  width: 4px;
  background: linear-gradient(180deg, #2563eb 0%, #60a5fa 100%);
  flex-shrink: 0;
}

/* 卡片内容主体 */
.metric-card__body {
  flex: 1;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 头部行：标题靠左、图标靠右 */
.metric-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.metric-card__title {
  font-size: 14px;
  color: #6b7280;
  font-weight: 500;
  letter-spacing: 0.2px;
}
.metric-card__icon {
  font-size: 22px;
  line-height: 1;
  /* 浅主色圆形底衬，让 emoji 看起来像专业图标 */
  background: var(--brand-soft);
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
}

/* 主数值行：数字与单位基线对齐 */
.metric-card__value-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.metric-card__value {
  font-size: 30px;
  font-weight: 700;
  color: #1f2d3d;
  line-height: 1.1;
  /* 数字使用等宽倾向字体，避免跳动 */
  font-variant-numeric: tabular-nums;
}
.metric-card__unit {
  font-size: 14px;
  color: #9ca3af;
  font-weight: 500;
}

/* 趋势小标 */
.metric-card__trend {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 500;
  width: fit-content;
}
.metric-card__trend-arrow {
  font-weight: 700;
}
/* 上涨为绿色（业务正向） */
.metric-card__trend--up {
  color: var(--success);
}
/* 下跌为红色 */
.metric-card__trend--down {
  color: var(--danger);
}
/* 持平为灰色 */
.metric-card__trend--flat {
  color: #9ca3af;
}
</style>
