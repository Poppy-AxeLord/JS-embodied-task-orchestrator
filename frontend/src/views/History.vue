<template>
  <!--
    任务历史页（History.vue）
    ============================================================
    产品定位：
      本页是「数据闭环」中"回放 + 人工介入"的核心入口。
      - 「历史任务」标签：把所有执行过的任务（含 Mock 种子数据）以表格形式呈现，
        支持按状态/类型筛选与多维排序，点击「详情」可完整回放一次任务的
        拆解结果、逐步执行日志(task_steps)与用户反馈，便于复盘失败。
      - 「需人工介入」标签：体现 Human-in-the-loop。系统把失败/可疑任务标记为
        needs_review，运营/标注人员在此修正步骤，提交后该任务沉淀为"优质样本"
        (is_golden=1)，反哺拆解模板，形成"越用越好"的飞轮。
    依赖 API（src/api/index.js）：
      getTasks(params) / getTask(id) / deleteTask(id) /
      getHitlList() / resolveHitl(id, payload) / getSkills()
  -->
  <div class="history-page">
    <!-- 顶部标题区 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">任务历史</h2>
        <p class="page-subtitle">回放任务执行全过程，处理需人工介入的样本，沉淀优质数据反哺模型</p>
      </div>
    </div>

    <!-- 主体：两个标签页 -->
    <el-tabs v-model="activeTab" class="history-tabs" @tab-change="onTabChange">
      <!-- ========== 标签一：历史任务列表 ========== -->
      <el-tab-pane name="history">
        <template #label>
          <span class="tab-label">
            <el-icon><Tickets /></el-icon>
            历史任务
          </span>
        </template>

        <!-- 筛选 / 排序工具条 -->
        <el-card shadow="never" class="filter-bar">
          <el-form :inline="true" @submit.prevent>
            <el-form-item label="任务状态">
              <el-select
                v-model="filters.status"
                placeholder="全部状态"
                clearable
                style="width: 150px"
                @change="loadTasks"
              >
                <el-option label="成功" value="success" />
                <el-option label="失败" value="failed" />
                <el-option label="进行中" value="pending" />
              </el-select>
            </el-form-item>

            <el-form-item label="任务类型">
              <el-select
                v-model="filters.task_type"
                placeholder="全部类型"
                clearable
                style="width: 150px"
                @change="loadTasks"
              >
                <el-option
                  v-for="t in taskTypeOptions"
                  :key="t"
                  :label="t"
                  :value="t"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="排序方式">
              <el-select
                v-model="filters.sort"
                style="width: 160px"
                @change="loadTasks"
              >
                <el-option label="按时间（最新优先）" value="time" />
                <el-option label="按成功状态" value="success" />
                <el-option label="按耗时（长→短）" value="duration" />
              </el-select>
            </el-form-item>

            <el-form-item>
              <el-button :icon="Refresh" @click="resetFilters">重置</el-button>
              <el-button type="primary" :icon="Search" @click="loadTasks">查询</el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 任务表格 -->
        <el-card shadow="never" class="table-card">
          <el-table
            v-loading="loading"
            :data="tasks"
            stripe
            style="width: 100%"
            empty-text="暂无任务记录"
          >
            <el-table-column type="index" label="#" width="55" align="center" />

            <el-table-column prop="instruction" label="指令" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="instruction-text">{{ row.instruction }}</span>
              </template>
            </el-table-column>

            <el-table-column prop="task_type" label="类型" width="90" align="center">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ row.task_type }}</el-tag>
              </template>
            </el-table-column>

            <el-table-column prop="strategy" label="策略" width="90" align="center">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="row.strategy === 'llm' ? 'primary' : 'info'"
                  effect="light"
                >
                  {{ row.strategy === 'llm' ? '大模型' : '规则' }}
                </el-tag>
              </template>
            </el-table-column>

            <!-- 状态：成功/失败用不同 tag 颜色 -->
            <el-table-column prop="status" label="状态" width="90" align="center">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="statusTagType(row.status)"
                  effect="dark"
                >
                  {{ statusText(row.status) }}
                </el-tag>
              </template>
            </el-table-column>

            <!-- 失败分类：用 §5 的 5 类配色映射 -->
            <el-table-column prop="failure_category" label="失败分类" width="110" align="center">
              <template #default="{ row }">
                <el-tag
                  v-if="row.failure_category"
                  size="small"
                  effect="light"
                  :style="failureTagStyle(row.failure_category)"
                >
                  {{ row.failure_category }}
                </el-tag>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>

            <el-table-column prop="total_duration_ms" label="耗时" width="100" align="center">
              <template #default="{ row }">
                {{ formatDuration(row.total_duration_ms) }}
              </template>
            </el-table-column>

            <!-- 评分：用 el-rate 只读展示 -->
            <el-table-column prop="rating" label="评分" width="130" align="center">
              <template #default="{ row }">
                <el-rate
                  v-if="row.rating"
                  :model-value="row.rating"
                  disabled
                  size="small"
                />
                <span v-else class="muted">未评分</span>
              </template>
            </el-table-column>

            <el-table-column prop="created_at" label="时间" width="160" align="center">
              <template #default="{ row }">
                <span class="muted">{{ formatDateTime(row.created_at) }}</span>
              </template>
            </el-table-column>

            <el-table-column label="操作" width="150" align="center" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" :icon="View" @click="openDetail(row.id)">
                  详情
                </el-button>
                <el-popconfirm
                  title="确认删除该任务记录吗？"
                  confirm-button-text="删除"
                  cancel-button-text="取消"
                  @confirm="onDeleteTask(row.id)"
                >
                  <template #reference>
                    <el-button link type="danger" :icon="Delete">删除</el-button>
                  </template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ========== 标签二：需人工介入 ========== -->
      <el-tab-pane name="hitl">
        <template #label>
          <span class="tab-label">
            <el-icon><Warning /></el-icon>
            需人工介入
            <el-badge
              v-if="hitlList.length"
              :value="hitlList.length"
              class="tab-badge"
              type="danger"
            />
          </span>
        </template>

        <el-alert
          class="hitl-tip"
          type="warning"
          :closable="false"
          show-icon
        >
          <template #title>
            以下任务执行失败或存在歧义，已被系统标记为「需人工介入」。
            修正其步骤后提交，将自动沉淀为<strong>优质样本</strong>（is_golden），反哺拆解模板。
          </template>
        </el-alert>

        <el-card shadow="never" class="table-card">
          <el-table
            v-loading="hitlLoading"
            :data="hitlList"
            stripe
            style="width: 100%"
            empty-text="太棒了，当前没有需要人工处理的任务"
          >
            <el-table-column type="index" label="#" width="55" align="center" />
            <el-table-column prop="instruction" label="指令" min-width="240" show-overflow-tooltip />
            <el-table-column prop="task_type" label="类型" width="90" align="center">
              <template #default="{ row }">
                <el-tag size="small" effect="plain">{{ row.task_type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="failure_category" label="失败分类" width="120" align="center">
              <template #default="{ row }">
                <el-tag
                  v-if="row.failure_category"
                  size="small"
                  effect="light"
                  :style="failureTagStyle(row.failure_category)"
                >
                  {{ row.failure_category }}
                </el-tag>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" width="160" align="center">
              <template #default="{ row }">
                <span class="muted">{{ formatDateTime(row.created_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140" align="center" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" size="small" :icon="Edit" @click="openHitl(row)">
                  修正并沉淀
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- ================= 任务详情弹窗 ================= -->
    <el-dialog
      v-model="detailVisible"
      title="任务详情回放"
      width="820px"
      top="6vh"
      destroy-on-close
    >
      <div v-loading="detailLoading">
        <template v-if="detail.task">
          <!-- 基本信息 -->
          <el-descriptions :column="2" border size="small" class="detail-desc">
            <el-descriptions-item label="原始指令" :span="2">
              {{ detail.task.instruction }}
            </el-descriptions-item>
            <el-descriptions-item label="任务类型">{{ detail.task.task_type }}</el-descriptions-item>
            <el-descriptions-item label="拆解策略">
              {{ detail.task.strategy === 'llm' ? '大模型拆解' : '规则拆解' }}
            </el-descriptions-item>
            <el-descriptions-item label="执行状态">
              <el-tag size="small" :type="statusTagType(detail.task.status)" effect="dark">
                {{ statusText(detail.task.status) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="失败分类">
              <el-tag
                v-if="detail.task.failure_category"
                size="small"
                :style="failureTagStyle(detail.task.failure_category)"
              >
                {{ detail.task.failure_category }}
              </el-tag>
              <span v-else class="muted">—</span>
            </el-descriptions-item>
            <el-descriptions-item label="总耗时">{{ formatDuration(detail.task.total_duration_ms) }}</el-descriptions-item>
            <el-descriptions-item label="步骤数">{{ detail.task.step_count }}</el-descriptions-item>
            <el-descriptions-item label="重试次数">{{ detail.task.retry_count }}</el-descriptions-item>
            <el-descriptions-item label="用户评分">
              <el-rate v-if="detail.task.rating" :model-value="detail.task.rating" disabled size="small" />
              <span v-else class="muted">未评分</span>
            </el-descriptions-item>
            <el-descriptions-item label="是否优质样本">
              <el-tag v-if="detail.task.is_golden" type="success" size="small">优质样本</el-tag>
              <span v-else class="muted">否</span>
            </el-descriptions-item>
            <el-descriptions-item v-if="detail.task.failure_reason" label="失败原因" :span="2">
              <span class="fail-reason">{{ detail.task.failure_reason }}</span>
            </el-descriptions-item>
          </el-descriptions>

          <!-- 拆解结果（Goal / Constraints / Exception） -->
          <el-divider content-position="left">任务拆解</el-divider>
          <div class="parse-block">
            <p><span class="block-key">目标：</span>{{ detail.task.goal || '—' }}</p>
            <p>
              <span class="block-key">约束条件：</span>
              <template v-if="(detail.task.constraints || []).length">
                <el-tag
                  v-for="(c, i) in detail.task.constraints"
                  :key="'c' + i"
                  size="small"
                  type="info"
                  effect="plain"
                  class="inline-tag"
                >{{ c }}</el-tag>
              </template>
              <span v-else class="muted">无</span>
            </p>
            <p>
              <span class="block-key">异常处理：</span>
              <template v-if="(detail.task.exception_handling || []).length">
                <el-tag
                  v-for="(e, i) in detail.task.exception_handling"
                  :key="'e' + i"
                  size="small"
                  type="warning"
                  effect="plain"
                  class="inline-tag"
                >{{ e }}</el-tag>
              </template>
              <span v-else class="muted">无</span>
            </p>
          </div>

          <!-- 逐步执行日志（task_steps） -->
          <el-divider content-position="left">逐步执行日志</el-divider>
          <el-timeline class="step-timeline">
            <el-timeline-item
              v-for="step in detail.steps"
              :key="step.id || step.step_index"
              :type="step.status === 'success' ? 'success' : 'danger'"
              :timestamp="formatDuration(step.duration_ms)"
              placement="top"
            >
              <div class="step-log-item">
                <span class="step-idx">步骤 {{ step.step_index }}</span>
                <span class="step-name">{{ step.skill_name }}</span>
                <code class="step-code">{{ step.skill_code }}</code>
                <el-tag
                  size="small"
                  :type="step.status === 'success' ? 'success' : 'danger'"
                  effect="dark"
                >
                  {{ step.status === 'success' ? '成功' : '失败' }}
                </el-tag>
              </div>
              <div v-if="parseParams(step.params)" class="step-params">
                参数：{{ parseParams(step.params) }}
              </div>
              <div v-if="step.error" class="step-error">错误：{{ step.error }}</div>
            </el-timeline-item>
            <el-empty v-if="!detail.steps || !detail.steps.length" description="无执行步骤日志" :image-size="60" />
          </el-timeline>

          <!-- 用户反馈 -->
          <el-divider content-position="left">用户反馈</el-divider>
          <template v-if="detail.feedback && detail.feedback.length">
            <div v-for="(fb, i) in detail.feedback" :key="'fb' + i" class="feedback-item">
              <el-rate v-if="fb.rating" :model-value="fb.rating" disabled size="small" />
              <p class="feedback-comment">{{ fb.comment || '（无文字评价）' }}</p>
              <span class="muted">{{ formatDateTime(fb.created_at) }}</span>
            </div>
          </template>
          <el-empty v-else description="暂无反馈" :image-size="60" />
        </template>
      </div>

      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- ================= 人工介入修正弹窗 ================= -->
    <el-dialog
      v-model="hitlVisible"
      title="人工修正 · 沉淀优质样本"
      width="760px"
      top="6vh"
      destroy-on-close
    >
      <el-alert
        type="info"
        :closable="false"
        show-icon
        class="hitl-edit-tip"
        title="请修正下方步骤序列（可调整顺序、增删步骤、修改参数）。提交后该任务将被标记为优质样本并取消人工介入标记。"
      />

      <div v-if="currentHitl" class="hitl-edit-body">
        <p class="hitl-instruction"><span class="block-key">指令：</span>{{ currentHitl.instruction }}</p>

        <!-- 失败分类修正 -->
        <el-form label-width="92px" class="hitl-form">
          <el-form-item label="失败分类">
            <el-select
              v-model="hitlForm.failure_category"
              placeholder="选择失败分类（可选）"
              clearable
              style="width: 220px"
            >
              <el-option
                v-for="cat in failureCategories"
                :key="cat.key"
                :label="cat.label"
                :value="cat.label"
              />
            </el-select>
          </el-form-item>
        </el-form>

        <!-- 可编辑步骤列表 -->
        <div class="edit-steps">
          <div class="edit-steps-head">
            <span>修正后的步骤序列（共 {{ hitlForm.corrected_steps.length }} 步）</span>
            <el-button size="small" type="primary" :icon="Plus" @click="addStep">添加步骤</el-button>
          </div>

          <el-empty
            v-if="!hitlForm.corrected_steps.length"
            description="暂无步骤，请从技能库添加"
            :image-size="60"
          />

          <div
            v-for="(step, idx) in hitlForm.corrected_steps"
            :key="idx"
            class="edit-step-row"
          >
            <span class="edit-step-no">{{ idx + 1 }}</span>

            <!-- 选择技能：联动填充 skill_code / skill_name / category -->
            <el-select
              v-model="step.skill_code"
              filterable
              placeholder="选择技能"
              style="width: 200px"
              @change="(code) => onSkillChange(step, code)"
            >
              <el-option
                v-for="sk in skills"
                :key="sk.code"
                :label="`${sk.icon || ''} ${sk.name}（${sk.code}）`"
                :value="sk.code"
              />
            </el-select>

            <!-- 步骤描述 -->
            <el-input
              v-model="step.description"
              placeholder="步骤描述"
              style="flex: 1; min-width: 160px"
            />

            <!-- 上移 / 下移 / 删除 -->
            <el-button-group>
              <el-button
                size="small"
                :icon="ArrowUp"
                :disabled="idx === 0"
                @click="moveStep(idx, -1)"
              />
              <el-button
                size="small"
                :icon="ArrowDown"
                :disabled="idx === hitlForm.corrected_steps.length - 1"
                @click="moveStep(idx, 1)"
              />
              <el-button
                size="small"
                type="danger"
                :icon="Delete"
                @click="removeStep(idx)"
              />
            </el-button-group>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="hitlVisible = false">取消</el-button>
        <el-button type="success" :icon="Select" :loading="hitlSubmitting" @click="submitHitl">
          提交修正并沉淀优质样本
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * 任务历史页逻辑
 * ------------------------------------------------------------
 * 关键产品逻辑说明：
 *  1) 列表筛选/排序：直接把 status / task_type / sort 透传给后端 getTasks，
 *     保证排序口径与服务端一致（time | success | duration）。
 *  2) 详情回放：getTask 返回 { task, steps, feedback }，本页把三者分区渲染，
 *     完整还原"拆解 → 逐步执行 → 用户反馈"的链路，是失败复盘的依据。
 *  3) Human-in-the-loop：needs_review 任务在「需人工介入」标签集中处理；
 *     人工修正步骤序列后调用 resolveHitl，由后端置 is_golden=1、needs_review=0，
 *     从而把一次失败转化为可复用的优质样本。
 */
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Tickets, Warning, Refresh, Search, View, Delete, Edit,
  Plus, ArrowUp, ArrowDown, Select
} from '@element-plus/icons-vue'
import {
  getTasks, getTask, deleteTask,
  getHitlList, resolveHitl, getSkills
} from '../api/index.js'
import {
  formatDuration, formatDateTime,
  FAILURE_CATEGORIES, failureColor
} from '../utils/format.js'

// ===== 失败分类映射（统一取自 utils/format.js，SPEC §5 五色契约）=====
const failureCategories = FAILURE_CATEGORIES.map((c) => ({
  key: c.key,
  label: c.name
}))

// 任务类型下拉选项（与 SPEC tasks.task_type 取值一致）
const taskTypeOptions = ['整理', '分拣', '取送', '巡检', '养护', '排序', '检查']

// ===== 标签页状态 =====
const activeTab = ref('history')

// ===== 历史任务列表状态 =====
const loading = ref(false)
const tasks = ref([])
const filters = reactive({
  status: '',
  task_type: '',
  sort: 'time'
})

// 加载任务列表（带筛选/排序参数）
async function loadTasks() {
  loading.value = true
  try {
    // 仅传非空参数，避免后端把空串当成有效过滤条件
    const params = {}
    if (filters.status) params.status = filters.status
    if (filters.task_type) params.task_type = filters.task_type
    if (filters.sort) params.sort = filters.sort
    tasks.value = await getTasks(params)
  } catch (e) {
    // 错误已由 axios 拦截器统一弹 ElMessage，这里兜底
    tasks.value = []
  } finally {
    loading.value = false
  }
}

// 重置筛选条件
function resetFilters() {
  filters.status = ''
  filters.task_type = ''
  filters.sort = 'time'
  loadTasks()
}

// 删除任务记录
async function onDeleteTask(id) {
  try {
    await deleteTask(id)
    ElMessage.success('已删除该任务记录')
    loadTasks()
  } catch (e) {
    /* 拦截器已提示 */
  }
}

// ===== 详情弹窗状态 =====
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = reactive({ task: null, steps: [], feedback: [] })

// 打开详情：调用 getTask 拉取完整数据
async function openDetail(id) {
  detailVisible.value = true
  detailLoading.value = true
  detail.task = null
  detail.steps = []
  detail.feedback = []
  try {
    const data = await getTask(id)
    detail.task = data.task || null
    detail.steps = data.steps || []
    detail.feedback = data.feedback || []
  } catch (e) {
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

// ===== 需人工介入（HITL）状态 =====
const hitlLoading = ref(false)
const hitlList = ref([])

// 加载需人工介入列表
async function loadHitl() {
  hitlLoading.value = true
  try {
    hitlList.value = await getHitlList()
  } catch (e) {
    hitlList.value = []
  } finally {
    hitlLoading.value = false
  }
}

// 切换标签时按需加载
function onTabChange(name) {
  if (name === 'hitl') loadHitl()
  else loadTasks()
}

// ===== 技能库（供 HITL 修正时选择技能）=====
const skills = ref([])
async function loadSkills() {
  try {
    skills.value = await getSkills()
  } catch (e) {
    skills.value = []
  }
}

// ===== HITL 修正弹窗状态 =====
const hitlVisible = ref(false)
const hitlSubmitting = ref(false)
const currentHitl = ref(null)
const hitlForm = reactive({
  corrected_steps: [], // [{ index, skill_code, skill_name, category, params, description }]
  failure_category: ''
})

// 打开修正弹窗：以原始 steps 作为可编辑初值
function openHitl(row) {
  currentHitl.value = row
  hitlForm.failure_category = row.failure_category || ''
  // 深拷贝原步骤，避免直接改动列表数据；兼容 steps 为字符串/数组两种形态
  const rawSteps = normalizeSteps(row.steps)
  hitlForm.corrected_steps = rawSteps.map((s, i) => ({
    index: i + 1,
    skill_code: s.skill_code || '',
    skill_name: s.skill_name || '',
    category: s.category || '',
    params: s.params || {},
    description: s.description || ''
  }))
  hitlVisible.value = true
}

// steps 字段可能是 JSON 字符串或数组，这里统一成数组
function normalizeSteps(steps) {
  if (!steps) return []
  if (Array.isArray(steps)) return steps
  try {
    const parsed = JSON.parse(steps)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

// 选择技能时联动填充技能元数据
function onSkillChange(step, code) {
  const sk = skills.value.find((s) => s.code === code)
  if (sk) {
    step.skill_name = sk.name
    step.category = sk.category
    if (!step.description) step.description = sk.description || ''
  }
}

// 新增一个空步骤
function addStep() {
  hitlForm.corrected_steps.push({
    index: hitlForm.corrected_steps.length + 1,
    skill_code: '',
    skill_name: '',
    category: '',
    params: {},
    description: ''
  })
}

// 删除步骤
function removeStep(idx) {
  hitlForm.corrected_steps.splice(idx, 1)
  reindexSteps()
}

// 上移/下移步骤（dir = -1 上移 / 1 下移）
function moveStep(idx, dir) {
  const target = idx + dir
  if (target < 0 || target >= hitlForm.corrected_steps.length) return
  const arr = hitlForm.corrected_steps
  ;[arr[idx], arr[target]] = [arr[target], arr[idx]]
  reindexSteps()
}

// 重排 index，保证步骤序号连续
function reindexSteps() {
  hitlForm.corrected_steps.forEach((s, i) => (s.index = i + 1))
}

// 提交人工修正：调用 resolveHitl，后端置 is_golden=1 / needs_review=0
async function submitHitl() {
  // 表单校验：至少一步，且每步必须选定技能
  if (!hitlForm.corrected_steps.length) {
    ElMessage.warning('请至少保留一个步骤后再提交')
    return
  }
  const invalid = hitlForm.corrected_steps.some((s) => !s.skill_code)
  if (invalid) {
    ElMessage.warning('存在未选择技能的步骤，请先补全')
    return
  }

  hitlSubmitting.value = true
  try {
    // 组装符合 SPEC §3 step 对象的 corrected_steps
    const corrected_steps = hitlForm.corrected_steps.map((s, i) => ({
      index: i + 1,
      skill_code: s.skill_code,
      skill_name: s.skill_name,
      category: s.category,
      params: s.params || {},
      description: s.description || ''
    }))
    const payload = { corrected_steps }
    if (hitlForm.failure_category) payload.failure_category = hitlForm.failure_category

    await resolveHitl(currentHitl.value.id, payload)
    ElMessage.success('修正已提交，该任务已沉淀为优质样本')
    hitlVisible.value = false
    loadHitl() // 刷新待处理列表
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    hitlSubmitting.value = false
  }
}

// ===== 展示辅助函数 =====
// 状态 → tag 类型
function statusTagType(status) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  return 'warning' // pending
}
// 状态 → 中文
function statusText(status) {
  if (status === 'success') return '成功'
  if (status === 'failed') return '失败'
  return '进行中'
}
// 失败分类 tag 内联样式（用 §5 配色，色值统一来自 format.js）
function failureTagStyle(category) {
  const color = failureColor(category)
  return {
    color,
    borderColor: color,
    backgroundColor: hexToRgba(color, 0.08)
  }
}
// 简单 hex → rgba 透明背景
function hexToRgba(hex, alpha) {
  const h = hex.replace('#', '')
  const r = parseInt(h.substring(0, 2), 16)
  const g = parseInt(h.substring(2, 4), 16)
  const b = parseInt(h.substring(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}
// 把 step.params（可能是 JSON 字符串/对象）格式化为可读文本
function parseParams(params) {
  if (!params) return ''
  let obj = params
  if (typeof params === 'string') {
    try {
      obj = JSON.parse(params)
    } catch {
      return params
    }
  }
  if (!obj || typeof obj !== 'object') return ''
  const entries = Object.entries(obj)
  if (!entries.length) return ''
  return entries.map(([k, v]) => `${k}=${v}`).join('，')
}

// 初次进入加载历史列表与技能库
onMounted(() => {
  loadTasks()
  loadSkills()
})
</script>

<style scoped>
.page-header {
  margin-bottom: 16px;
}
.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}
.page-subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: #6b7280;
}

.history-tabs {
  background: transparent;
}
.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.tab-badge {
  margin-left: 2px;
}

.filter-bar {
  margin-bottom: 14px;
  border-radius: 10px;
}
.filter-bar :deep(.el-form-item) {
  margin-bottom: 0;
}

.table-card {
  border-radius: 10px;
}

.instruction-text {
  color: #1f2937;
}
.muted {
  color: #9ca3af;
}

/* HITL 提示区 */
.hitl-tip {
  margin-bottom: 14px;
  border-radius: 10px;
}
.hitl-edit-tip {
  margin-bottom: 14px;
}

/* 详情弹窗 */
.detail-desc {
  margin-bottom: 8px;
}
.block-key {
  font-weight: 600;
  color: #374151;
}
.inline-tag {
  margin: 0 6px 6px 0;
}
.parse-block p {
  margin: 6px 0;
  color: #4b5563;
}
.fail-reason {
  color: #e8684a;
}

/* 步骤时间线 */
.step-timeline {
  padding-left: 4px;
}
.step-log-item {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.step-idx {
  font-weight: 600;
  color: #2563eb;
}
.step-name {
  font-weight: 600;
  color: #1f2937;
}
.step-code {
  font-family: 'SFMono-Regular', Menlo, monospace;
  font-size: 12px;
  color: #6b7280;
  background: #f3f4f6;
  padding: 1px 6px;
  border-radius: 4px;
}
.step-params {
  margin-top: 4px;
  font-size: 12px;
  color: #6b7280;
}
.step-error {
  margin-top: 4px;
  font-size: 12px;
  color: #e8684a;
}

/* 反馈 */
.feedback-item {
  padding: 8px 12px;
  background: #f9fafb;
  border-radius: 8px;
  margin-bottom: 8px;
}
.feedback-comment {
  margin: 6px 0 2px;
  color: #374151;
}

/* HITL 修正弹窗步骤编辑 */
.hitl-instruction {
  margin: 0 0 12px;
  color: #374151;
}
.hitl-form {
  margin-bottom: 8px;
}
.edit-steps-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-weight: 600;
  color: #374151;
}
.edit-step-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.edit-step-no {
  width: 24px;
  height: 24px;
  line-height: 24px;
  text-align: center;
  border-radius: 50%;
  background: #2563eb;
  color: #fff;
  font-size: 12px;
  flex-shrink: 0;
}
</style>
