<script setup>
/**
 * Sim2D.vue —— 2D 俯视仿真组件
 * --------------------------------------------------------------------------
 * 职责（SPEC §13）：
 *   用 SVG 画一个房间俯视图，直观体现机器人执行任务的过程。
 *   不追求物理精度，目标是让使用者直观看到任务逐步执行：
 *     - 房间边界、桌子、收纳盒/货架
 *     - 几个彩色物品（杯子 / 方块 / 盒子）
 *     - 机器人（圆形本体 + 朝向小三角）
 *   机器人位置随 stepIndex 变化，用 CSS transition 平滑移动；
 *   抓取（Grasp）时被抓物品跟随机器人，放置（Place）时归位到目标点。
 *
 * 设计说明：
 *   1. 我们不依赖真实坐标系，而是根据"当前步骤用的技能"推断一个语义化的
 *      目标位置（如 MoveTo→桌子、Place→收纳盒）。这样即便拆解结果千变万化，
 *      画面也能讲出一个连贯的故事。
 *   2. 所有可移动元素都通过响应式 computed 计算坐标，配合 SVG <g> 上的
 *      style transition 实现补间动画。
 */
import { computed } from 'vue'

// ------------------------------ Props ------------------------------
const props = defineProps({
  // 当前正在执行（或已完成）的步骤对象，形如 §3 的 step；可能为 null
  step: { type: Object, default: null },
  // 当前步骤序号（从 0 开始的数组下标；-1 表示尚未开始）
  stepIndex: { type: Number, default: -1 },
  // 已解析任务（ParsedTask），主要用于读取 task_type 渲染场景标题
  parsed: { type: Object, default: null },
  // 全部步骤数组（用于判断进度、推断物品状态）
  steps: { type: Array, default: () => [] },
  // 是否正在运行（用于机器人"呼吸"高亮效果）
  running: { type: Boolean, default: false }
})

// ------------------------------ 场景固定布局 ------------------------------
// 房间内坐标系：viewBox 0 0 600 400。以下为各关键家具/区域的中心点。
const LAYOUT = {
  home: { x: 80, y: 330 }, // 机器人起始点 / 充电点（左下角）
  table: { x: 300, y: 150 }, // 桌子中心
  shelf: { x: 520, y: 110 }, // 货架（右上）
  storage: { x: 520, y: 300 }, // 收纳盒（右下）
  window: { x: 300, y: 30 } // 窗户（上方墙）
}

// 三个彩色物品的"初始归位坐标"（散落在桌面上）
// id 用于渲染 key；color 决定填充色；shape 决定形状（杯子/方块/盒子）
const INIT_ITEMS = [
  { id: 'cup', name: '杯子', shape: 'cup', color: '#E8684A', home: { x: 250, y: 130 } },
  { id: 'block', name: '方块', shape: 'block', color: '#2563EB', home: { x: 320, y: 165 } },
  { id: 'box', name: '盒子', shape: 'box', color: '#5AD8A6', home: { x: 360, y: 130 } }
]

// ------------------------------ 语义推断辅助 ------------------------------
/**
 * 根据一个步骤推断机器人应当移动到的"目标位置"。
 * 这是纯展示逻辑：把抽象技能映射到场景里的一个点。
 * @param {Object} s 步骤对象
 * @returns {{x:number,y:number}} 目标坐标
 */
function targetOfStep(s) {
  if (!s) return LAYOUT.home
  const code = s.skill_code || ''
  // 优先看参数里的目标文字，命中关键词就去对应区域
  const paramText = JSON.stringify(s.params || {})
  if (/货架|上层|shelf/i.test(paramText)) return LAYOUT.shelf
  if (/收纳|盒|storage|box|区|A区|B区/i.test(paramText)) return LAYOUT.storage
  if (/窗|window/i.test(paramText)) return LAYOUT.window
  if (/桌|table|desk/i.test(paramText)) return LAYOUT.table

  // 再按技能编码兜底映射
  switch (code) {
    case 'ReturnHome':
      return LAYOUT.home
    case 'Place':
      return LAYOUT.storage // 放置类默认去收纳区
    case 'Pour':
      return LAYOUT.window // 倾倒/浇水：靠近窗边植物
    case 'Open':
      return LAYOUT.window // 开窗
    case 'Patrol':
    case 'Navigate':
    case 'Scan':
      return LAYOUT.shelf // 巡检/扫描：绕到货架附近
    default:
      return LAYOUT.table // 其余默认在桌子附近作业
  }
}

/**
 * 计算机器人当前坐标。
 * 逻辑：取"截至当前 stepIndex 的最后一个有效目标"。
 * 若尚未开始（stepIndex < 0）则停在起始点。
 */
const robotPos = computed(() => {
  if (props.stepIndex < 0 || !props.step) return LAYOUT.home
  return targetOfStep(props.step)
})

/**
 * 计算机器人朝向角度（度）。让小三角指向"上一位置→当前位置"的方向，
 * 这样移动时看起来像真的转身走过去。无前一位置时朝右。
 */
const robotAngle = computed(() => {
  const cur = robotPos.value
  // 取上一步目标作为来向
  const prevStep = props.stepIndex > 0 ? props.steps[props.stepIndex - 1] : null
  const prev = prevStep ? targetOfStep(prevStep) : LAYOUT.home
  const dx = cur.x - prev.x
  const dy = cur.y - prev.y
  if (dx === 0 && dy === 0) return 0
  return (Math.atan2(dy, dx) * 180) / Math.PI
})

/**
 * 判断当前步骤是否处于"抓着某物"的状态。
 * 规则：当前技能是 Grasp 时认为已抓起；Place 时认为正在放下（仍跟随到目标）。
 * 返回被操作物品 id，或 null。
 */
const heldItemId = computed(() => {
  const s = props.step
  if (!s) return null
  if (s.skill_code === 'Grasp' || s.skill_code === 'Place' || s.skill_code === 'Push') {
    // 根据参数里的物体名匹配三个物品之一，匹配不到就默认抓"杯子"
    const text = JSON.stringify(s.params || {}) + (s.description || '')
    if (/方块|block|蓝/i.test(text)) return 'block'
    if (/盒|box|绿/i.test(text)) return 'box'
    return 'cup'
  }
  return null
})

/**
 * 计算每个物品的当前坐标。
 * - 被抓住的物品：跟随机器人（略微偏移，像被托在身前）。
 * - 已被 Place 放置过的物品：留在收纳区（用一个简单的已放置集合近似）。
 * - 其余：停在初始归位坐标。
 *
 * 注意：这里用 stepIndex 做"已放置"判断——遍历 0..stepIndex 的步骤，
 * 若某物品出现过 Place，则视为已放置到目标点。
 */
const itemsPos = computed(() => {
  const result = {}
  // 先全部置为初始位置
  INIT_ITEMS.forEach((it) => (result[it.id] = { ...it.home }))

  // 遍历到当前步，记录已放置物品的落点
  for (let i = 0; i <= props.stepIndex && i < props.steps.length; i++) {
    const s = props.steps[i]
    if (!s) continue
    if (s.skill_code === 'Place') {
      // 推断这步放的是哪个物品
      const text = JSON.stringify(s.params || {}) + (s.description || '')
      let id = 'cup'
      if (/方块|block|蓝/i.test(text)) id = 'block'
      else if (/盒|box|绿/i.test(text)) id = 'box'
      // 放置落点：用该步的语义目标 + 小幅错位避免完全重叠
      const t = targetOfStep(s)
      const offset = id === 'cup' ? -22 : id === 'block' ? 0 : 22
      result[id] = { x: t.x + offset, y: t.y }
    }
  }

  // 当前正被抓着的物品：覆盖为"跟随机器人"
  const held = heldItemId.value
  if (held) {
    const r = robotPos.value
    result[held] = { x: r.x, y: r.y - 26 } // 托在机器人前上方
  }
  return result
})

// 顶部场景标题：体现任务类型，纯展示
const sceneTitle = computed(() => {
  const t = props.parsed?.task_type
  return t ? `仿真场景 · ${t}任务` : '仿真场景 · 房间俯视图'
})
</script>

<template>
  <div class="sim2d">
    <div class="sim2d__title">{{ sceneTitle }}</div>

    <!-- 房间 SVG：固定 viewBox，外层用 CSS 自适应宽度，Retina 下矢量清晰 -->
    <svg class="sim2d__svg" viewBox="0 0 600 400" preserveAspectRatio="xMidYMid meet">
      <!-- ====================== 静态背景 ====================== -->
      <!-- 地板 -->
      <rect x="0" y="0" width="600" height="400" rx="14" fill="#F2F5FA" />
      <!-- 房间边界墙 -->
      <rect
        x="14"
        y="14"
        width="572"
        height="372"
        rx="10"
        fill="none"
        stroke="#C3CCDA"
        stroke-width="4"
      />
      <!-- 地砖网格（淡淡的，增加纵深感） -->
      <g stroke="#E2E8F2" stroke-width="1">
        <line x1="14" y1="100" x2="586" y2="100" />
        <line x1="14" y1="200" x2="586" y2="200" />
        <line x1="14" y1="300" x2="586" y2="300" />
        <line x1="150" y1="14" x2="150" y2="386" />
        <line x1="300" y1="14" x2="300" y2="386" />
        <line x1="450" y1="14" x2="450" y2="386" />
      </g>

      <!-- 窗户（上墙开口） -->
      <g>
        <rect x="250" y="12" width="100" height="8" fill="#8EC5FC" />
        <text x="300" y="40" text-anchor="middle" class="sim2d__label">窗户 / 植物</text>
        <!-- 窗边植物（小图标） -->
        <circle cx="262" cy="34" r="7" fill="#5AD8A6" />
        <rect x="259" y="38" width="6" height="8" fill="#A87B4F" />
      </g>

      <!-- 桌子 -->
      <g>
        <rect
          x="220"
          y="105"
          width="160"
          height="90"
          rx="8"
          fill="#D8B894"
          stroke="#B8946A"
          stroke-width="2"
        />
        <text x="300" y="215" text-anchor="middle" class="sim2d__label">桌子</text>
      </g>

      <!-- 货架（右上） -->
      <g>
        <rect
          x="478"
          y="60"
          width="84"
          height="100"
          rx="6"
          fill="#CBB5E8"
          stroke="#9270CA"
          stroke-width="2"
        />
        <line x1="478" y1="93" x2="562" y2="93" stroke="#9270CA" stroke-width="2" />
        <line x1="478" y1="126" x2="562" y2="126" stroke="#9270CA" stroke-width="2" />
        <text x="520" y="178" text-anchor="middle" class="sim2d__label">货架</text>
      </g>

      <!-- 收纳盒（右下） -->
      <g>
        <rect
          x="478"
          y="262"
          width="84"
          height="76"
          rx="6"
          fill="#A9D8C2"
          stroke="#5AD8A6"
          stroke-width="2"
        />
        <text x="520" y="356" text-anchor="middle" class="sim2d__label">收纳盒</text>
      </g>

      <!-- 起始 / 充电点（左下） -->
      <g>
        <circle cx="80" cy="330" r="26" fill="none" stroke="#94A3B8" stroke-width="2" stroke-dasharray="5 4" />
        <text x="80" y="372" text-anchor="middle" class="sim2d__label">起始点</text>
      </g>

      <!-- ====================== 可移动物品 ====================== -->
      <!-- 用 <g> 包裹并对 transform 设置 transition，实现平滑移动 -->
      <g
        v-for="it in INIT_ITEMS"
        :key="it.id"
        class="sim2d__item"
        :style="{ transform: `translate(${itemsPos[it.id].x}px, ${itemsPos[it.id].y}px)` }"
      >
        <!-- 杯子：圆形 + 顶部开口 -->
        <template v-if="it.shape === 'cup'">
          <ellipse cx="0" cy="0" rx="11" ry="11" :fill="it.color" />
          <ellipse cx="0" cy="-3" rx="7" ry="4" fill="#ffffff" opacity="0.5" />
        </template>
        <!-- 方块：正方形 -->
        <template v-else-if="it.shape === 'block'">
          <rect x="-11" y="-11" width="22" height="22" rx="3" :fill="it.color" />
        </template>
        <!-- 盒子：带盖矩形 -->
        <template v-else>
          <rect x="-13" y="-9" width="26" height="18" rx="2" :fill="it.color" />
          <rect x="-13" y="-9" width="26" height="5" fill="#ffffff" opacity="0.35" />
        </template>
        <!-- 被抓起时高亮一个光环 -->
        <circle
          v-if="heldItemId === it.id"
          cx="0"
          cy="0"
          r="18"
          fill="none"
          stroke="#2563EB"
          stroke-width="2"
          stroke-dasharray="3 3"
        >
          <animateTransform
            attributeName="transform"
            type="rotate"
            from="0"
            to="360"
            dur="3s"
            repeatCount="indefinite"
          />
        </circle>
      </g>

      <!-- ====================== 机器人 ====================== -->
      <!-- 外层 <g> 平移到机器人坐标，内层 <g> 旋转到朝向角度 -->
      <g
        class="sim2d__robot"
        :style="{ transform: `translate(${robotPos.x}px, ${robotPos.y}px)` }"
      >
        <!-- 运行时的呼吸光环 -->
        <circle
          v-if="running"
          cx="0"
          cy="0"
          r="24"
          fill="#2563EB"
          opacity="0.15"
        >
          <animate attributeName="r" values="20;28;20" dur="1.6s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.22;0.05;0.22" dur="1.6s" repeatCount="indefinite" />
        </circle>
        <!-- 机器人本体 -->
        <circle cx="0" cy="0" r="16" fill="#2563EB" stroke="#1E40AF" stroke-width="2" />
        <!-- 朝向小三角（随角度旋转） -->
        <g :style="{ transform: `rotate(${robotAngle}deg)` }" class="sim2d__robot-dir">
          <polygon points="14,0 4,-6 4,6" fill="#ffffff" />
        </g>
        <text x="0" y="33" text-anchor="middle" class="sim2d__robot-label">机器人</text>
      </g>
    </svg>

    <!-- 当前步骤说明条：把"机器人正在做什么"用文字讲出来 -->
    <div class="sim2d__caption">
      <template v-if="step">
        <span class="sim2d__caption-idx">第 {{ stepIndex + 1 }} 步</span>
        <span class="sim2d__caption-skill">{{ step.skill_name }}（{{ step.skill_code }}）</span>
        <span class="sim2d__caption-desc">{{ step.description || '执行中…' }}</span>
      </template>
      <template v-else>
        <span class="sim2d__caption-desc sim2d__caption-idle">等待开始执行…</span>
      </template>
    </div>
  </div>
</template>

<style scoped>
.sim2d {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.sim2d__title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
  margin-bottom: 8px;
}

.sim2d__svg {
  width: 100%;
  /* 保持房间比例 3:2，自适应容器宽度 */
  aspect-ratio: 3 / 2;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
}

/* 物品与机器人统一的平滑过渡 —— 这是"动画感"的核心 */
.sim2d__item,
.sim2d__robot {
  transition: transform 0.9s cubic-bezier(0.45, 0.05, 0.25, 1);
}

/* 朝向三角旋转单独过渡，让转身更自然 */
.sim2d__robot-dir {
  transition: transform 0.6s ease;
}

.sim2d__label {
  font-size: 11px;
  fill: #64748b;
}

.sim2d__robot-label {
  font-size: 11px;
  font-weight: 600;
  fill: #1e40af;
}

.sim2d__caption {
  margin-top: 10px;
  padding: 8px 12px;
  background: #f0f5ff;
  border-radius: 8px;
  font-size: 13px;
  color: #1f2d3d;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-height: 20px;
}

.sim2d__caption-idx {
  font-weight: 700;
  color: #2563eb;
}

.sim2d__caption-skill {
  font-weight: 600;
}

.sim2d__caption-desc {
  color: #475569;
}

.sim2d__caption-idle {
  color: #94a3b8;
}
</style>
