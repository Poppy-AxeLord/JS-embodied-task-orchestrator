<script setup>
/**
 * SkillLibrary.vue —— 技能库组件
 *
 * 产品职责（见 SPEC §13）：
 *   1. 调用后端 getSkills() 拉取 25 个原子技能（见 SPEC §4）；
 *   2. 按 5 大分类（移动类/操作类/感知类/逻辑类/控制类）分组展示；
 *   3. 每个技能卡片显示：emoji 图标 + 中文名 + 描述；
 *   4. 提供「添加到流程」按钮，点击后 emit('add-skill', skill)，
 *      由父级 TaskEditor 转交给 TaskFlowChart 完成步骤追加，实现技能库与流程图的联动。
 *
 * 设计说明：
 *   - 用 el-tabs 做 5 个分类页签，比 el-collapse 更紧凑，右栏空间利用率更高；
 *   - 技能数据来自后端 skills 表，input_params/output 已由后端 json.loads 解析；
 *   - 组件保持「无状态」纯展示：不直接改流程，只负责把用户选中的技能事件抛出去。
 */
import { ref, computed, onMounted } from 'vue'
import { getSkills } from '../api/index.js'
// 技能分类配色统一取自 utils/format.js（全站唯一色源，与流程图节点一致）
import { skillCategoryColor } from '../utils/format.js'

// 父组件可监听 add-skill 事件接收被选中的技能对象
const emit = defineEmits(['add-skill'])

// ---------------------------------------------------------------------------
// 分类定义：固定 5 类（SPEC §4）。配色不再本地维护，统一走 skillCategoryColor()。
// ---------------------------------------------------------------------------
const CATEGORIES = [
  { key: '移动类', desc: '机器人位移与导航相关能力' },
  { key: '操作类', desc: '对物体的抓取、放置等操作能力' },
  { key: '感知类', desc: '识别、定位、测量等感知能力' },
  { key: '逻辑类', desc: '条件、循环、排序等逻辑控制' },
  { key: '控制类', desc: '等待、重试、人工确认等流程控制' }
]

// 全部技能（后端返回的原始数组）
const skills = ref([])
// 加载态，用于骨架/禁用按钮
const loading = ref(false)
// 当前激活的分类页签
const activeCategory = ref(CATEGORIES[0].key)

/**
 * 按分类把技能分组，返回 { 分类key: [skill, ...] }。
 * 用 computed 保证 skills 变化时自动重算。
 */
const groupedSkills = computed(() => {
  const map = {}
  // 先为每个分类建空数组，保证即使某类暂时为空，页签也能正常渲染
  CATEGORIES.forEach((c) => {
    map[c.key] = []
  })
  skills.value.forEach((s) => {
    if (map[s.category]) {
      map[s.category].push(s)
    } else {
      // 容错：若后端出现未知分类，归到「控制类」兜底，避免技能丢失
      map['控制类'].push(s)
    }
  })
  return map
})

/**
 * 取某分类的主题色，供页签色点与卡片左侧色条使用（统一色源 format.js）。
 */
function categoryColor(key) {
  return skillCategoryColor(key)
}

/**
 * 把技能的 input_params（[{name,type,desc}]）拼成一段可读的中文摘要，
 * 在卡片上以小字提示该技能的主要参数，方便用户判断是否需要添加。
 */
function paramSummary(skill) {
  const params = skill.input_params || []
  if (!params.length) return '无参数'
  return params.map((p) => p.name).join(' / ')
}

/**
 * 点击「添加到流程」：把当前技能抛给父组件。
 * 这里不直接构造 step 对象，由 TaskFlowChart 统一负责把 skill 转成标准 step，
 * 以保证 step 结构（SPEC §3）只有一处生成逻辑，避免重复发明字段。
 * 成功提示由 TaskFlowChart.addSkillStep 统一弹出，这里不重复提示。
 */
function handleAdd(skill) {
  emit('add-skill', skill)
}

/**
 * 拉取技能列表。失败时 axios 拦截器已统一弹错，这里仅兜底设空数组。
 */
async function loadSkills() {
  loading.value = true
  try {
    const data = await getSkills()
    skills.value = Array.isArray(data) ? data : []
  } catch (e) {
    skills.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadSkills)

// 暴露刷新方法，便于父组件在新增/删除技能后主动刷新技能库
defineExpose({ reload: loadSkills })
</script>

<template>
  <div class="skill-library" v-loading="loading">
    <!-- 顶部标题区 -->
    <div class="lib-header">
      <span class="lib-title">技能库</span>
      <span class="lib-subtitle">点击「添加」把原子技能加入动作序列</span>
    </div>

    <!-- 5 个分类页签 -->
    <el-tabs v-model="activeCategory" class="lib-tabs">
      <el-tab-pane
        v-for="cat in CATEGORIES"
        :key="cat.key"
        :name="cat.key"
      >
        <!-- 自定义页签标题：带分类色点 + 数量徽标 -->
        <template #label>
          <span class="tab-label">
            <i class="dot" :style="{ background: categoryColor(cat.key) }"></i>
            {{ cat.key }}
            <el-badge
              :value="groupedSkills[cat.key] ? groupedSkills[cat.key].length : 0"
              type="info"
              class="tab-badge"
            />
          </span>
        </template>

        <!-- 分类说明 -->
        <div class="cat-desc">{{ cat.desc }}</div>

        <!-- 技能卡片列表 -->
        <div class="skill-list">
          <div
            v-for="skill in groupedSkills[cat.key]"
            :key="skill.code || skill.id"
            class="skill-card"
            :style="{ borderLeftColor: categoryColor(skill.category) }"
          >
            <div class="skill-main">
              <span class="skill-icon">{{ skill.icon }}</span>
              <div class="skill-text">
                <div class="skill-name">
                  {{ skill.name }}
                  <span class="skill-code">{{ skill.code }}</span>
                </div>
                <div class="skill-desc">{{ skill.description }}</div>
                <div class="skill-params">参数：{{ paramSummary(skill) }}</div>
              </div>
            </div>
            <el-button
              size="small"
              type="primary"
              plain
              class="add-btn"
              @click="handleAdd(skill)"
            >
              添加到流程
            </el-button>
          </div>

          <!-- 空态 -->
          <el-empty
            v-if="!groupedSkills[cat.key] || !groupedSkills[cat.key].length"
            description="该分类暂无技能"
            :image-size="60"
          />
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.skill-library {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  padding: 16px;
  box-sizing: border-box;
  overflow: hidden;
}

.lib-header {
  display: flex;
  flex-direction: column;
  margin-bottom: 6px;
}
/* 标题：左侧主色竖条，与全站分区标题一致 */
.lib-title {
  position: relative;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  padding-left: 12px;
}
.lib-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 15px;
  background: var(--brand);
  border-radius: 2px;
}
.lib-subtitle {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 2px;
}

.lib-tabs {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
/* 让页签内容区可滚动，技能多时不撑破布局 */
.lib-tabs :deep(.el-tabs__content) {
  flex: 1;
  overflow-y: auto;
}

.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.tab-label .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.tab-badge {
  margin-left: 2px;
}

.cat-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 4px 0 10px;
  padding: 6px 8px;
  background: var(--bg-page);
  border-radius: var(--radius-sm);
}

.skill-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.skill-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  background: #fafbfc;
  border: 1px solid var(--border-light);
  border-left: 4px solid var(--brand);
  border-radius: var(--radius-sm);
  transition: all 0.2s ease;
}
.skill-card:hover {
  box-shadow: var(--shadow-hover);
  transform: translateY(-1px);
}

.skill-main {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}
.skill-icon {
  font-size: 22px;
  line-height: 1.2;
}
.skill-text {
  min-width: 0;
}
.skill-name {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
  display: flex;
  align-items: center;
  gap: 6px;
}
.skill-code {
  font-size: 11px;
  font-weight: 400;
  color: #9ca3af;
  background: #f0f2f5;
  padding: 0 5px;
  border-radius: 4px;
}
.skill-desc {
  font-size: 12px;
  color: #6b7280;
  margin-top: 2px;
  white-space: normal;
}
.skill-params {
  font-size: 11px;
  color: #9ca3af;
  margin-top: 3px;
}

.add-btn {
  flex-shrink: 0;
}
</style>
