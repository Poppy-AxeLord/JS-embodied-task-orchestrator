<script setup>
/**
 * TaskFlowChart.vue —— 任务流程图组件（拆解结果可视化与编辑）
 *
 * 产品职责（见 SPEC §13）：
 *   以「四区」结构展示并编辑一条 ParsedTask（数据结构见 SPEC §3）：
 *     ① 任务目标 Goal           —— 一句话目标
 *     ② 约束条件 Constraints    —— el-tag 标签数组，可增删
 *     ③ 动作序列 Action Steps   —— 核心：纵向彩色步骤卡片，按 §4「技能分类」着色
 *     ④ 异常处理 Exception      —— el-tag 标签数组，可增删
 *
 *   动作序列支持：
 *     - 上移 / 下移（调整步骤顺序）
 *     - 删除步骤
 *     - 编辑步骤（弹窗修改 description 与 params）
 *     - 从技能库添加步骤（由父组件把技能事件转交进来调用 addSkillStep）
 *
 * 数据流：
 *   - 通过 props.parsed 接收拆解结果；
 *   - 任何修改都基于一份内部深拷贝 local，改完后 emit('update:parsed', local)，
 *     从而支持父组件 v-model:parsed 双向绑定（SPEC §13 要求 v-model/emit 更新）。
 *
 * 着色约定：
 *   - 步骤卡片颜色取自该步骤所属「技能分类」（§4 的 5 类），统一调用 utils/format.js
 *     的 getCategoryColor()，保证全站配色一致、不在组件里硬编码色值。
 */
import { ref, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowUp, ArrowDown, EditPen, Close } from '@element-plus/icons-vue'
// format.js 提供技能分类配色等格式化工具（全站统一来源）
import { getCategoryColor } from '../utils/format.js'

const props = defineProps({
  // 待展示/编辑的拆解结果（ParsedTask），允许为空（未拆解时）
  parsed: {
    type: Object,
    default: null
  }
})

// 支持 v-model:parsed
const emit = defineEmits(['update:parsed'])

// ---------------------------------------------------------------------------
// 内部可编辑副本：避免直接改 props（单向数据流原则）。
// 每次 props.parsed 变化都同步重建一份深拷贝。
// ---------------------------------------------------------------------------
const local = ref(null)

/**
 * 把传入的 parsed 深拷贝到 local，并补齐缺省字段，保证模板渲染安全。
 */
function syncFromProps(val) {
  if (!val) {
    local.value = null
    return
  }
  // 结构化克隆，切断与 props 的引用关系
  const clone = JSON.parse(JSON.stringify(val))
  // 字段兜底，防止后端/上游缺字段导致渲染报错
  clone.goal = clone.goal || ''
  clone.task_type = clone.task_type || ''
  clone.instruction = clone.instruction || ''
  clone.constraints = Array.isArray(clone.constraints) ? clone.constraints : []
  clone.exception_handling = Array.isArray(clone.exception_handling)
    ? clone.exception_handling
    : []
  clone.steps = Array.isArray(clone.steps) ? clone.steps : []
  // 重新编号，确保 index 连续（拆解结果可能因增删而错号）
  reindex(clone.steps)
  local.value = clone
}

watch(() => props.parsed, syncFromProps, { immediate: true, deep: true })

/**
 * 重新编号步骤的 index（从 1 开始），任何增删/排序后都要调用。
 */
function reindex(steps) {
  steps.forEach((s, i) => {
    s.index = i + 1
  })
}

/**
 * 任何修改后统一调用：重排序号 + 向父组件抛出更新。
 */
function commit() {
  if (!local.value) return
  reindex(local.value.steps)
  // 抛出深拷贝，避免父子持有同一引用造成意外联动
  emit('update:parsed', JSON.parse(JSON.stringify(local.value)))
}

// ===========================================================================
// 区域②④：约束条件 / 异常处理 —— 标签的增删
// ===========================================================================
// 新增标签输入框的显隐与内容（约束）
const constraintInputVisible = ref(false)
const constraintInputValue = ref('')
// 新增标签输入框的显隐与内容（异常处理）
const exceptionInputVisible = ref(false)
const exceptionInputValue = ref('')

/** 删除一条约束 */
function removeConstraint(idx) {
  local.value.constraints.splice(idx, 1)
  commit()
}
/** 确认新增约束 */
function confirmConstraint() {
  const v = constraintInputValue.value.trim()
  if (v) {
    local.value.constraints.push(v)
    commit()
  }
  constraintInputVisible.value = false
  constraintInputValue.value = ''
}

/** 删除一条异常处理 */
function removeException(idx) {
  local.value.exception_handling.splice(idx, 1)
  commit()
}
/** 确认新增异常处理 */
function confirmException() {
  const v = exceptionInputValue.value.trim()
  if (v) {
    local.value.exception_handling.push(v)
    commit()
  }
  exceptionInputVisible.value = false
  exceptionInputValue.value = ''
}

// ===========================================================================
// 区域③：动作序列 —— 步骤的上移/下移/删除/编辑
// ===========================================================================

/** 上移一步（与上一步交换位置） */
function moveUp(idx) {
  if (idx <= 0) return
  const arr = local.value.steps
  ;[arr[idx - 1], arr[idx]] = [arr[idx], arr[idx - 1]]
  commit()
}

/** 下移一步（与下一步交换位置） */
function moveDown(idx) {
  const arr = local.value.steps
  if (idx >= arr.length - 1) return
  ;[arr[idx], arr[idx + 1]] = [arr[idx + 1], arr[idx]]
  commit()
}

/** 删除一步 */
function removeStep(idx) {
  local.value.steps.splice(idx, 1)
  commit()
}

// ---- 步骤编辑弹窗 ----
const editDialogVisible = ref(false)
const editingIndex = ref(-1) // 正在编辑的数组下标
// 编辑表单：description + params（params 以「键值对数组」形式编辑，便于增删字段）
const editForm = ref({
  description: '',
  expected_result: '',
  paramList: [] // [{ key, value }]
})

/**
 * 打开编辑弹窗，把目标步骤的数据填入表单。
 * params 是对象（如 {target:"桌子"}），这里转成 [{key,value}] 方便表格化编辑。
 */
function openEdit(idx) {
  const step = local.value.steps[idx]
  editingIndex.value = idx
  editForm.value = {
    description: step.description || '',
    expected_result: step.expected_result || '',
    paramList: Object.entries(step.params || {}).map(([key, value]) => ({
      key,
      value: typeof value === 'object' ? JSON.stringify(value) : String(value)
    }))
  }
  editDialogVisible.value = true
}

/** 编辑弹窗中新增一行参数 */
function addParamRow() {
  editForm.value.paramList.push({ key: '', value: '' })
}
/** 编辑弹窗中删除一行参数 */
function removeParamRow(i) {
  editForm.value.paramList.splice(i, 1)
}

/**
 * 保存步骤编辑：把表单写回对应 step（description / expected_result / params）。
 * paramList 转回对象，空 key 行忽略。
 */
function saveEdit() {
  const idx = editingIndex.value
  if (idx < 0 || !local.value.steps[idx]) {
    editDialogVisible.value = false
    return
  }
  const params = {}
  editForm.value.paramList.forEach((row) => {
    const k = (row.key || '').trim()
    if (k) params[k] = row.value
  })
  const step = local.value.steps[idx]
  step.description = editForm.value.description.trim()
  step.expected_result = editForm.value.expected_result.trim()
  step.params = params
  editDialogVisible.value = false
  commit()
  ElMessage.success('步骤已更新')
}

// ===========================================================================
// 从技能库添加步骤（由父组件 TaskEditor 把 SkillLibrary 的 add-skill 事件转交进来）
// ===========================================================================

/**
 * 根据一个技能对象（skills 表行）构造标准 step（结构见 SPEC §3）并追加到序列末尾。
 * 这里是「skill → step」的唯一转换点：
 *   - skill_code / skill_name / category 来自技能；
 *   - params 用技能的 input_params 名称生成空值占位，便于用户在编辑弹窗里填写；
 *   - description / expected_result 给出合理默认文案。
 */
function addSkillStep(skill) {
  if (!skill) return
  // 若当前还没有任何拆解结果，先初始化一个空的 ParsedTask 容器，
  // 让用户可以「从零手动搭流程」。
  if (!local.value) {
    local.value = {
      instruction: '',
      task_type: '自定义',
      goal: '（请填写任务目标）',
      constraints: [],
      steps: [],
      exception_handling: []
    }
  }
  // 用 input_params 的名称生成参数占位对象
  const params = {}
  ;(skill.input_params || []).forEach((p) => {
    params[p.name] = ''
  })
  const step = {
    index: local.value.steps.length + 1,
    skill_code: skill.code,
    skill_name: skill.name,
    category: skill.category,
    params,
    description: `${skill.name}（${skill.description || ''}）`,
    expected_result: ''
  }
  local.value.steps.push(step)
  commit()
  ElMessage.success(`已添加步骤：${skill.name}`)
}

// 暴露给父组件调用：实现「SkillLibrary 添加技能 → 流程图追加步骤」的联动
defineExpose({ addSkillStep })

// ---------------------------------------------------------------------------
// 视图辅助
// ---------------------------------------------------------------------------

/** 是否有可展示的内容 */
const hasContent = computed(() => !!local.value)

/**
 * 把 step.params 对象拼成「键: 值」的可读字符串，在卡片上展示。
 */
function paramText(params) {
  const entries = Object.entries(params || {})
  if (!entries.length) return '无参数'
  return entries
    .map(([k, v]) => `${k}: ${v === '' || v == null ? '—' : v}`)
    .join('，')
}
</script>

<template>
  <div class="flow-chart">
    <!-- 未拆解时的空态引导 -->
    <el-empty
      v-if="!hasContent"
      description="请输入指令并点击「拆解任务」，或从右侧技能库手动搭建流程"
      :image-size="120"
    />

    <template v-else>
      <!-- ========================= 区域①：任务目标 ========================= -->
      <section class="region region-goal">
        <div class="region-head">
          <span class="region-tag goal-tag">任务目标</span>
          <el-tag v-if="local.task_type" size="small" type="primary" effect="plain">
            类型：{{ local.task_type }}
          </el-tag>
        </div>
        <div class="goal-text">{{ local.goal || '（未设定目标）' }}</div>
        <div v-if="local.instruction" class="instruction-text">
          原始指令：{{ local.instruction }}
        </div>
      </section>

      <!-- ========================= 区域②：约束条件 ========================= -->
      <section class="region region-constraint">
        <div class="region-head">
          <span class="region-tag constraint-tag">约束条件</span>
          <span class="region-count">{{ local.constraints.length }} 条</span>
        </div>
        <div class="tag-area">
          <el-tag
            v-for="(c, i) in local.constraints"
            :key="'c' + i"
            type="warning"
            effect="light"
            closable
            class="info-tag"
            @close="removeConstraint(i)"
          >
            {{ c }}
          </el-tag>
          <!-- 行内新增约束 -->
          <el-input
            v-if="constraintInputVisible"
            v-model="constraintInputValue"
            size="small"
            class="tag-input"
            placeholder="输入约束后回车"
            @keyup.enter="confirmConstraint"
            @blur="confirmConstraint"
          />
          <el-button
            v-else
            size="small"
            class="add-tag-btn"
            @click="constraintInputVisible = true"
          >
            + 约束
          </el-button>
        </div>
      </section>

      <!-- ========================= 区域③：动作序列 ========================= -->
      <section class="region region-steps">
        <div class="region-head">
          <span class="region-tag step-tag">动作序列</span>
          <span class="region-count">{{ local.steps.length }} 步</span>
        </div>

        <el-empty
          v-if="!local.steps.length"
          description="暂无步骤，点击右侧技能「添加到流程」开始搭建"
          :image-size="70"
        />

        <!-- 纵向流程卡片：每步一张，左侧色条取技能分类色 -->
        <div class="step-list">
          <div
            v-for="(step, idx) in local.steps"
            :key="idx"
            class="step-card"
            :style="{ borderLeftColor: getCategoryColor(step.category) }"
          >
            <!-- 序号气泡，颜色随分类 -->
            <div
              class="step-index"
              :style="{ background: getCategoryColor(step.category) }"
            >
              {{ idx + 1 }}
            </div>

            <!-- 步骤主体 -->
            <div class="step-body">
              <div class="step-title-row">
                <span class="step-name">{{ step.skill_name }}</span>
                <el-tag
                  size="small"
                  effect="plain"
                  :style="{
                    color: getCategoryColor(step.category),
                    borderColor: getCategoryColor(step.category)
                  }"
                >
                  {{ step.category }}
                </el-tag>
                <span class="step-code">{{ step.skill_code }}</span>
              </div>
              <div class="step-desc">{{ step.description || '（无描述）' }}</div>
              <div class="step-params">参数：{{ paramText(step.params) }}</div>
              <div v-if="step.expected_result" class="step-expect">
                预期：{{ step.expected_result }}
              </div>
            </div>

            <!-- 步骤操作按钮组 -->
            <div class="step-ops">
              <el-button
                circle
                size="small"
                :icon="ArrowUp"
                :disabled="idx === 0"
                title="上移"
                @click="moveUp(idx)"
              />
              <el-button
                circle
                size="small"
                :icon="ArrowDown"
                :disabled="idx === local.steps.length - 1"
                title="下移"
                @click="moveDown(idx)"
              />
              <el-button
                circle
                size="small"
                type="primary"
                plain
                :icon="EditPen"
                title="编辑"
                @click="openEdit(idx)"
              />
              <el-button
                circle
                size="small"
                type="danger"
                plain
                :icon="Close"
                title="删除"
                @click="removeStep(idx)"
              />
            </div>

            <!-- 步骤间的连接箭头（最后一步不显示） -->
            <div v-if="idx < local.steps.length - 1" class="step-arrow">↓</div>
          </div>
        </div>
      </section>

      <!-- ========================= 区域④：异常处理 ========================= -->
      <section class="region region-exception">
        <div class="region-head">
          <span class="region-tag exception-tag">异常处理</span>
          <span class="region-count">{{ local.exception_handling.length }} 条</span>
        </div>
        <div class="tag-area">
          <el-tag
            v-for="(e, i) in local.exception_handling"
            :key="'e' + i"
            type="danger"
            effect="light"
            closable
            class="info-tag"
            @close="removeException(i)"
          >
            {{ e }}
          </el-tag>
          <el-input
            v-if="exceptionInputVisible"
            v-model="exceptionInputValue"
            size="small"
            class="tag-input"
            placeholder="输入异常处理后回车"
            @keyup.enter="confirmException"
            @blur="confirmException"
          />
          <el-button
            v-else
            size="small"
            class="add-tag-btn"
            @click="exceptionInputVisible = true"
          >
            + 异常处理
          </el-button>
        </div>
      </section>
    </template>

    <!-- ===================== 步骤编辑弹窗 ===================== -->
    <el-dialog
      v-model="editDialogVisible"
      title="编辑步骤"
      width="520px"
      append-to-body
    >
      <el-form label-width="80px" label-position="top">
        <el-form-item label="步骤描述">
          <el-input
            v-model="editForm.description"
            type="textarea"
            :rows="2"
            placeholder="描述该步骤要做什么"
          />
        </el-form-item>
        <el-form-item label="预期结果">
          <el-input
            v-model="editForm.expected_result"
            placeholder="该步骤完成后的预期结果（可选）"
          />
        </el-form-item>
        <el-form-item label="参数（params）">
          <div class="param-editor">
            <div
              v-for="(row, i) in editForm.paramList"
              :key="i"
              class="param-row"
            >
              <el-input
                v-model="row.key"
                placeholder="参数名"
                class="param-key"
                size="small"
              />
              <span class="param-colon">：</span>
              <el-input
                v-model="row.value"
                placeholder="参数值"
                class="param-value"
                size="small"
              />
              <el-button
                size="small"
                type="danger"
                plain
                circle
                :icon="Close"
                @click="removeParamRow(i)"
              />
            </div>
            <el-button size="small" class="add-param" @click="addParamRow">
              + 添加参数
            </el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.flow-chart {
  height: 100%;
  overflow-y: auto;
  padding: 4px 6px;
  box-sizing: border-box;
}

/* 四区通用容器：统一设计 token（圆角/轻阴影/细边框） */
.region {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  padding: 16px;
  margin-bottom: 16px;
}
.region-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
/* 区块标签：浅底 + 本色文字（替代实色块，修复黄底白字对比度问题） */
.region-tag {
  font-size: 13px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: var(--radius-sm);
}
.goal-tag {
  background: #eff6ff;
  color: #2563eb;
}
.constraint-tag {
  background: rgba(246, 189, 22, 0.14);
  color: #b45309;
}
.step-tag {
  background: rgba(91, 143, 249, 0.12);
  color: #3b6fd6;
}
.exception-tag {
  background: rgba(232, 104, 74, 0.12);
  color: #d3512e;
}
.region-count {
  font-size: 12px;
  color: #9ca3af;
}

/* 区域①目标 */
.goal-text {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  line-height: 1.5;
}
.instruction-text {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 6px;
}

/* 标签区（约束/异常通用） */
.tag-area {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.info-tag {
  max-width: 100%;
  white-space: normal;
  height: auto;
  line-height: 1.4;
  padding: 4px 8px;
}
.tag-input {
  width: 180px;
}
.add-tag-btn {
  border-style: dashed;
}

/* 区域③步骤列表 */
.step-list {
  display: flex;
  flex-direction: column;
}
.step-card {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: #fafbfc;
  border: 1px solid var(--border-light);
  border-left: 4px solid #5b8ff9;
  border-radius: var(--radius);
  padding: 12px 14px;
  margin-bottom: 26px; /* 给箭头留空间 */
  transition: all 0.2s ease;
}
.step-card:last-child {
  margin-bottom: 4px;
}
.step-card:hover {
  box-shadow: var(--shadow-hover);
  transform: translateY(-1px);
}
.step-index {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  color: #fff;
  font-weight: 700;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.step-body {
  flex: 1;
  min-width: 0;
}
.step-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.step-name {
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
}
.step-code {
  font-size: 11px;
  color: #9ca3af;
  background: #f0f2f5;
  padding: 0 5px;
  border-radius: 4px;
}
.step-desc {
  font-size: 13px;
  color: #4b5563;
  margin-top: 5px;
}
.step-params {
  font-size: 12px;
  color: #6b7280;
  margin-top: 4px;
}
.step-expect {
  font-size: 12px;
  color: #10b981;
  margin-top: 3px;
}
.step-ops {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
}
.step-ops .el-button {
  margin-left: 0;
}
/* 步骤之间的向下箭头 */
.step-arrow {
  position: absolute;
  bottom: -22px;
  left: 26px;
  color: #c0c4cc;
  font-size: 18px;
  font-weight: 700;
}

/* 编辑弹窗参数编辑器 */
.param-editor {
  width: 100%;
}
.param-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.param-key {
  width: 130px;
}
.param-value {
  flex: 1;
}
.param-colon {
  color: #909399;
}
.add-param {
  border-style: dashed;
}
</style>
