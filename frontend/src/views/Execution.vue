<script setup>
/**
 * Execution.vue —— 执行模拟页（SPEC §13）
 * --------------------------------------------------------------------------
 * 产品逻辑总览：
 *   1. 进入页面时从 sessionStorage('parsedTask') 取出上一步在「任务编排」页
 *      存下的 ParsedTask；若没有，用 el-empty 提示用户先去编排。
 *   2. 用户选策略 → 点「开始执行」：
 *      - 先调用后端 runExecution(parsed, strategy) 拿到 ExecutionResult
 *        （后端已一次性算好每步的成功/失败、耗时、失败原因并落库）。
 *      - 前端再按每步的 duration_ms，用 setTimeout 逐步"播放"动画，
 *        让 2D 仿真和日志随时间推进，营造真实执行的观感。
 *   3. 支持 暂停 / 继续 / 重新执行：通过一个可清除的定时器句柄 + 状态标志位
 *      实现一个清晰的状态机（见下方 PHASE 常量）。
 *   4. 执行结束弹出反馈对话框：el-rate 评分 + 评价 textarea + 提交(submitFeedback)。
 *   5. 「策略对比」：调用 compareExecution(parsed)，并列展示 llm / rule 两策略的
 *      步骤数 / 耗时 / 成功情况。
 *
 * 状态机（phase）：
 *   idle      —— 初始/重置，未开始
 *   loading   —— 已点开始，正在等待后端返回 ExecutionResult
 *   running   —— 正在逐步播放动画
 *   paused    —— 播放被暂停（定时器已清，等待继续）
 *   finished  —— 全部步骤播放完毕
 * 状态迁移：
 *   idle --开始--> loading --拿到结果--> running
 *   running --暂停--> paused --继续--> running
 *   running --播完--> finished
 *   任意 --重新执行--> idle（清理一切）
 */
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { runExecution, compareExecution, submitFeedback } from '../api/index.js'
// 失败分类配色统一取自 utils/format.js（SPEC §5 五色契约，全站唯一色源）
import { failureColor } from '../utils/format.js'
import Sim2D from '../components/Sim2D.vue'

// 路由实例：用于「策略对比」弹窗跳转到数据看板查看统计规律
const router = useRouter()

// ------------------------------ 阶段常量 ------------------------------
const PHASE = {
  IDLE: 'idle',
  LOADING: 'loading',
  RUNNING: 'running',
  PAUSED: 'paused',
  FINISHED: 'finished'
}

// 单步在日志里的状态（不同于落库的最终态，多了"待执行/执行中"）
const STEP_STATE = {
  PENDING: 'pending', // 待执行
  RUNNING: 'running', // 执行中
  SUCCESS: 'success', // 成功
  FAILED: 'failed' // 失败
}

// 展示模式的默认任务：首次进入执行页也能立即看到完整工作流、工作单元与待执行日志。
// 用户从编排页跳转时，sessionStorage 中的真实编排结果会优先覆盖它。
const SHOWCASE_TASK = {
  instruction: '将红色杯子稳定放置到右侧收纳区',
  strategy: 'llm',
  task_type: '取送',
  difficulty: '中等',
  goal: '红色杯子位于右侧收纳区，且动作完成后得到确认',
  constraints: ['避开工作台边缘', '保持杯体竖直', '放置后进行状态确认'],
  steps: [
    { index: 1, skill_code: 'FindObject', skill_name: '识别目标物体', description: '识别红色杯子与可抓取区域', expected_duration_ms: 620 },
    { index: 2, skill_code: 'Locate', skill_name: '定位目标与收纳区', description: '确定抓取点和右侧放置坐标', expected_duration_ms: 750 },
    { index: 3, skill_code: 'Grasp', skill_name: '稳定抓取目标', description: '以自适应力度抓取杯体', expected_duration_ms: 880 },
    { index: 4, skill_code: 'MoveTo', skill_name: '移动至收纳区', description: '沿安全路径移动至右侧收纳区', expected_duration_ms: 1020 },
    { index: 5, skill_code: 'Place', skill_name: '放置并确认结果', description: '放置杯子并确认任务完成', expected_duration_ms: 760 },
  ],
}

// ------------------------------ 响应式状态 ------------------------------
// 从 sessionStorage 读取的已解析任务
const parsed = ref(null)
// 当前执行策略
const strategy = ref('llm')
// 当前阶段
const phase = ref(PHASE.IDLE)
// 后端返回的完整执行结果（ExecutionResult），播放结束才算最终结论
const execResult = ref(null)
// 当前正在播放到的步骤下标（-1 表示还没开始第一步）
const currentIndex = ref(-1)

// 日志：每一项是 { index, skill_code, skill_name, state, duration_ms, error, failure_category }
// state 用 STEP_STATE。注意它是"播放视角"的状态，会从 pending→running→success/failed 演变。
const logs = ref([])

// 定时器句柄（用于暂停时清除）。null 表示当前没有挂起的计时器。
let stepTimer = null
// 暂停时记录"当前步剩余多少毫秒"，以便继续时接着走（简单起见按整步重放）
// 这里采用整步推进模型：暂停发生在两步之间，继续时直接调度下一步。

// 反馈对话框
const feedbackVisible = ref(false)
const feedback = reactive({ rating: 5, comment: '' })
const submitting = ref(false)

// 策略对比对话框
const compareVisible = ref(false)
const compareLoading = ref(false)
const compareData = ref(null) // { results: [{strategy,success,...}] }

// ------------------------------ 计算属性 ------------------------------
// 总步骤数
const totalSteps = computed(() => parsed.value?.steps?.length || 0)

// 尚未执行时同样给出可解释的时间口径，避免演示首屏出现“--”这类占位数据。
const estimatedTotalMs = computed(() => (parsed.value?.steps || [])
  .reduce((sum, step) => sum + Number(step.expected_duration_ms || step.duration_ms || 0), 0))

// 已完成（成功或失败）的步骤数 —— 用于进度条
const doneSteps = computed(
  () => logs.value.filter((l) => l.state === STEP_STATE.SUCCESS || l.state === STEP_STATE.FAILED).length
)

// 进度百分比（0-100）
const progressPercent = computed(() => {
  if (!totalSteps.value) return 0
  return Math.round((doneSteps.value / totalSteps.value) * 100)
})

// 预计剩余时间（毫秒）：把"尚未播放步骤"的 duration_ms 求和。
// 数据源是后端 execResult.steps（已含每步耗时）。
const remainingMs = computed(() => {
  if (!execResult.value?.steps) return 0
  const steps = execResult.value.steps
  let sum = 0
  for (let i = doneSteps.value; i < steps.length; i++) {
    sum += steps[i]?.duration_ms || 0
  }
  return sum
})

// 进度条颜色：运行中蓝色，结束按成败显示语义绿/红
const progressColor = computed(() => {
  if (phase.value === PHASE.FINISHED) {
    return execResult.value?.success ? '#10B981' : '#EF4444'
  }
  return '#2563EB'
})

// 顶部按钮可用性（驱动 UI 的核心，全部从 phase 派生，保证状态机一致）
const canStart = computed(() => phase.value === PHASE.IDLE || phase.value === PHASE.FINISHED)
const canPause = computed(() => phase.value === PHASE.RUNNING)
const canResume = computed(() => phase.value === PHASE.PAUSED)
const canReset = computed(() => phase.value !== PHASE.IDLE)

// 当前步骤对象（传给 Sim2D 渲染）
const currentStep = computed(() => {
  if (currentIndex.value < 0) return null
  return parsed.value?.steps?.[currentIndex.value] || null
})

// 阶段中文文案（顶部状态徽标）
const phaseLabel = computed(() => {
  switch (phase.value) {
    case PHASE.IDLE:
      return '待执行'
    case PHASE.LOADING:
      return '准备中'
    case PHASE.RUNNING:
      return '执行中'
    case PHASE.PAUSED:
      return '已暂停'
    case PHASE.FINISHED:
      return execResult.value?.success ? '执行成功' : '执行失败'
    default:
      return ''
  }
})
const phaseTagType = computed(() => {
  switch (phase.value) {
    case PHASE.RUNNING:
      return 'primary'
    case PHASE.PAUSED:
      return 'warning'
    case PHASE.FINISHED:
      return execResult.value?.success ? 'success' : 'danger'
    default:
      return 'info'
  }
})

// ------------------------------ 生命周期 ------------------------------
onMounted(() => {
  // 从 sessionStorage 取出编排页存下的 ParsedTask
  const raw = sessionStorage.getItem('parsedTask')
  if (raw) {
    try {
      parsed.value = JSON.parse(raw)
    } catch (e) {
      // 解析失败也按"无任务"处理
      parsed.value = null
    }
  }
  // 不把首次访问导向空白提示：它应该是一段可立即播放、可供讲解的完整演示。
  if (!parsed.value?.steps?.length) {
    parsed.value = SHOWCASE_TASK
  }
  buildInitialLogs()
})

onBeforeUnmount(() => {
  // 离开页面务必清掉定时器，避免内存泄漏 / 离开后还在推进
  clearStepTimer()
})

// ------------------------------ 定时器工具 ------------------------------
/** 清除当前挂起的步骤定时器（暂停/重置/卸载时调用） */
function clearStepTimer() {
  if (stepTimer !== null) {
    clearTimeout(stepTimer)
    stepTimer = null
  }
}

// ------------------------------ 工具函数 ------------------------------
/**
 * 用 ParsedTask.steps 初始化日志列表，全部置为"待执行"。
 * 这样用户一进来就能看到完整的步骤清单。
 */
function buildInitialLogs() {
  logs.value = (parsed.value?.steps || []).map((s) => ({
    index: s.index,
    skill_code: s.skill_code,
    skill_name: s.skill_name,
    state: STEP_STATE.PENDING,
    duration_ms: null,
    error: null,
    failure_category: null
  }))
}

/** 把毫秒格式化为"x.x 秒"，用于日志与剩余时间展示 */
function fmtMs(ms) {
  if (ms == null) return '--'
  return (ms / 1000).toFixed(1) + ' 秒'
}

/** 日志单步状态 → tag 文案 */
function stateText(state) {
  return {
    [STEP_STATE.PENDING]: '待执行',
    [STEP_STATE.RUNNING]: '执行中',
    [STEP_STATE.SUCCESS]: '成功',
    [STEP_STATE.FAILED]: '失败'
  }[state]
}

/** 日志单步状态 → Element Plus tag 类型 */
function stateTagType(state) {
  return {
    [STEP_STATE.PENDING]: 'info',
    [STEP_STATE.RUNNING]: 'primary',
    [STEP_STATE.SUCCESS]: 'success',
    [STEP_STATE.FAILED]: 'danger'
  }[state]
}

// ------------------------------ 核心：开始执行 ------------------------------
/**
 * 「开始执行」：先重置 → 调后端拿结果 → 启动逐步播放。
 */
async function handleStart() {
  if (!parsed.value || !totalSteps.value) {
    ElMessage.warning('当前没有可执行的任务，请先去任务编排页拆解任务')
    return
  }
  // 1) 复位所有播放状态
  resetState(false)
  phase.value = PHASE.LOADING
  buildInitialLogs()

  // 2) 调用后端，一次性拿到 ExecutionResult（含每步耗时与成败）
  try {
    const res = await runExecution(parsed.value, strategy.value)
    execResult.value = res
  } catch (e) {
    // 接口层拦截器已弹错误提示，这里回到 idle 即可
    phase.value = PHASE.IDLE
    return
  }

  // 3) 进入运行态，从第 0 步开始播放
  phase.value = PHASE.RUNNING
  currentIndex.value = -1
  playNextStep()
}

/**
 * 调度并播放"下一步"。
 * 模型说明（整步推进）：
 *   - 把 currentIndex 推进到下一步，立即把该步日志置为"执行中"。
 *   - 用该步的 duration_ms 作为 setTimeout 延时；延时结束后把该步落定为
 *     后端给出的最终态（success/failed），再继续调度更下一步。
 *   - 若该步是失败步，则播放到此为止（整段执行以失败结束）。
 */
function playNextStep() {
  // 防御：只有运行态才继续推进
  if (phase.value !== PHASE.RUNNING) return

  const next = currentIndex.value + 1
  const backendSteps = execResult.value?.steps || []

  // 所有步骤播完 → 结束
  if (next >= backendSteps.length) {
    finishExecution()
    return
  }

  currentIndex.value = next
  const backendStep = backendSteps[next]

  // 标记当前步"执行中"
  const log = logs.value[next]
  if (log) log.state = STEP_STATE.RUNNING

  // 按该步耗时延时推进
  const delay = Math.max(300, backendStep.duration_ms || 800)
  stepTimer = setTimeout(() => {
    stepTimer = null
    // 若期间被暂停/重置，phase 已变，直接返回（保险）
    if (phase.value !== PHASE.RUNNING) return

    // 落定本步最终态（来自后端）
    if (log) {
      log.state = backendStep.status === 'success' ? STEP_STATE.SUCCESS : STEP_STATE.FAILED
      log.duration_ms = backendStep.duration_ms
      log.error = backendStep.error || null
      // 失败步带上整段执行的失败分类（用于上色）
      if (backendStep.status !== 'success') {
        log.failure_category = execResult.value?.failure_category || null
      }
    }

    // 失败步：执行到此为止，整体失败
    if (backendStep.status !== 'success') {
      finishExecution()
      return
    }

    // 成功步：继续下一步
    playNextStep()
  }, delay)
}

/** 暂停：清掉挂起的定时器，置 paused。当前"执行中"的那步保持执行中样式。 */
function handlePause() {
  if (phase.value !== PHASE.RUNNING) return
  clearStepTimer()
  phase.value = PHASE.PAUSED
}

/** 继续：从暂停处重新调度当前"执行中"的那一步。 */
function handleResume() {
  if (phase.value !== PHASE.PAUSED) return
  phase.value = PHASE.RUNNING
  // 暂停时若有一步停在"执行中"，把 currentIndex 回退一格，
  // 让 playNextStep 重新调度该步（整步重放，简单可靠）。
  const idx = currentIndex.value
  const log = logs.value[idx]
  if (log && log.state === STEP_STATE.RUNNING) {
    currentIndex.value = idx - 1
  }
  playNextStep()
}

/** 重新执行：彻底复位回 idle（不自动开始，等用户再点开始）。 */
function handleReset() {
  resetState(true)
}

/**
 * 复位内部状态。
 * @param {boolean} backToIdle 是否回到 idle 阶段（true=用户主动重置）
 */
function resetState(backToIdle) {
  clearStepTimer()
  execResult.value = null
  currentIndex.value = -1
  logs.value = []
  // 重新铺一遍待执行日志，让用户能看到步骤清单
  if (parsed.value) buildInitialLogs()
  if (backToIdle) phase.value = PHASE.IDLE
}

/** 收尾：进入 finished，弹反馈对话框。 */
function finishExecution() {
  clearStepTimer()
  phase.value = PHASE.FINISHED
  // 把进度补满（防御：确保未播步骤不残留 pending 影响进度展示）
  // 实际由 backendSteps 决定，这里不强行改写后续步状态。
  // 自动弹出反馈对话框，引导用户评分（数据闭环关键一环）
  feedback.rating = execResult.value?.success ? 5 : 3
  feedback.comment = ''
  feedbackVisible.value = true
}

// ------------------------------ 反馈提交 ------------------------------
/**
 * 提交反馈：调用 submitFeedback。
 * payload 形如 { task_id, rating, comment }，task_id 来自 ExecutionResult。
 */
async function handleSubmitFeedback() {
  const taskId = execResult.value?.task_id
  if (!taskId) {
    ElMessage.warning('缺少任务 ID，无法提交反馈')
    return
  }
  submitting.value = true
  try {
    await submitFeedback({
      task_id: taskId,
      rating: feedback.rating,
      comment: feedback.comment
    })
    ElMessage.success('反馈已提交，感谢您帮助平台越用越好')
    feedbackVisible.value = false
  } catch (e) {
    // 拦截器已提示错误
  } finally {
    submitting.value = false
  }
}

// ------------------------------ 策略对比 ------------------------------
/**
 * 「策略对比」：对同一任务并行模拟 llm / rule 两策略，并列展示对比。
 */
async function handleCompare() {
  if (!parsed.value || !totalSteps.value) {
    ElMessage.warning('当前没有可对比的任务，请先去任务编排页拆解任务')
    return
  }
  compareVisible.value = true
  compareLoading.value = true
  compareData.value = null
  try {
    const res = await compareExecution(parsed.value)
    compareData.value = res
  } catch (e) {
    // 拦截器已提示
  } finally {
    compareLoading.value = false
  }
}

/** 策略英文 → 中文展示名 */
function strategyLabel(s) {
  return s === 'rule' ? '规则拆解' : '大模型拆解'
}

/**
 * 从「策略对比」弹窗跳转到数据看板。
 * 单次仿真对比只反映一次随机结果，真正的策略选型结论要看看板里
 * 基于 150+ 历史样本聚合的统计规律（成功率 / 平均耗时 / 五维雷达）。
 */
function goDashboard() {
  compareVisible.value = false
  router.push('/dashboard')
}
</script>

<template>
  <div class="execution">
    <!-- ================== 无任务：引导去编排 ================== -->
    <el-empty
      v-if="!parsed"
      description="还没有可执行的任务，请先去「任务编排」页拆解一个任务"
    >
      <el-button type="primary" @click="$router.push('/task')">前往任务编排</el-button>
    </el-empty>

    <!-- ================== 主体 ================== -->
    <template v-else>
      <!-- -------- 顶部工具条：策略选择 + 控制按钮 -------- -->
      <el-card class="exec-toolbar" shadow="never">
        <div class="exec-toolbar__row">
          <div class="exec-toolbar__left">
            <span class="exec-toolbar__label">执行策略</span>
            <el-radio-group
              v-model="strategy"
              :disabled="phase === 'running' || phase === 'paused' || phase === 'loading'"
            >
              <el-radio-button label="llm">大模型拆解</el-radio-button>
              <el-radio-button label="rule">规则拆解</el-radio-button>
            </el-radio-group>
            <el-tag :type="phaseTagType" effect="dark" class="exec-toolbar__phase">
              {{ phaseLabel }}
            </el-tag>
          </div>
          <div class="exec-toolbar__right">
            <el-button
              type="primary"
              :loading="phase === 'loading'"
              :disabled="!canStart"
              @click="handleStart"
            >
              {{ phase === 'finished' ? '重新执行' : '开始执行' }}
            </el-button>
            <el-button :disabled="!canPause" @click="handlePause">暂停</el-button>
            <el-button :disabled="!canResume" @click="handleResume">继续</el-button>
            <el-button :disabled="!canReset" @click="handleReset">重置</el-button>
            <el-button type="warning" plain @click="handleCompare">策略对比</el-button>
          </div>
        </div>
      </el-card>

      <!-- -------- 主区：左仿真 / 右进度+日志 -------- -->
      <div class="exec-main">
        <!-- 左：2D 仿真 -->
        <el-card class="exec-sim" shadow="never">
          <Sim2D
            :step="currentStep"
            :step-index="currentIndex"
            :parsed="parsed"
            :steps="parsed.steps"
            :running="phase === 'running'"
          />
        </el-card>

        <!-- 右：上进度 / 下日志 -->
        <div class="exec-side">
          <!-- 右上：执行进度 -->
          <el-card class="exec-progress" shadow="never">
            <div class="exec-progress__head">
              <span class="exec-card-title">执行进度</span>
              <span class="exec-progress__step">
                第 {{ Math.min(doneSteps + (phase === 'running' ? 1 : 0), totalSteps) }} /
                {{ totalSteps }} 步
              </span>
            </div>
            <el-progress
              :percentage="progressPercent"
              :color="progressColor"
              :stroke-width="14"
              :striped="phase === 'running'"
              :striped-flow="phase === 'running'"
            />
            <div class="exec-progress__meta">
              <div class="exec-progress__meta-item">
                <span class="exec-progress__meta-label">预计剩余</span>
                <span class="exec-progress__meta-value">{{ fmtMs(remainingMs) }}</span>
              </div>
              <div class="exec-progress__meta-item">
                <span class="exec-progress__meta-label">重试次数</span>
                <span class="exec-progress__meta-value">{{ execResult?.retry_count ?? 0 }}</span>
              </div>
              <div class="exec-progress__meta-item">
                <span class="exec-progress__meta-label">{{ phase === 'finished' ? '总耗时' : '预计总耗时' }}</span>
                <span class="exec-progress__meta-value">
                  {{ phase === 'finished' ? fmtMs(execResult?.total_duration_ms) : fmtMs(estimatedTotalMs) }}
                </span>
              </div>
            </div>
            <!-- 失败结论提示 -->
            <el-alert
              v-if="phase === 'finished' && !execResult?.success"
              class="exec-progress__fail"
              :title="`执行失败：${execResult?.failure_category || '未知'}`"
              :description="execResult?.failure_reason || ''"
              type="error"
              :closable="false"
              show-icon
            />
            <el-alert
              v-else-if="phase === 'finished' && execResult?.success"
              class="exec-progress__fail"
              title="任务执行成功"
              type="success"
              :closable="false"
              show-icon
            />
          </el-card>

          <!-- 右下：实时执行日志 -->
          <el-card class="exec-log" shadow="never">
            <div class="exec-card-title exec-log__title">实时执行日志</div>
            <div class="exec-log__list">
              <div
                v-for="log in logs"
                :key="log.index"
                class="exec-log__item"
                :class="{ 'is-active': log.state === 'running' }"
              >
                <span class="exec-log__idx">{{ log.index }}</span>
                <div class="exec-log__body">
                  <div class="exec-log__line">
                    <span class="exec-log__skill">
                      {{ log.skill_name }}
                      <span class="exec-log__code">{{ log.skill_code }}</span>
                    </span>
                    <el-tag :type="stateTagType(log.state)" size="small" effect="light">
                      {{ stateText(log.state) }}
                    </el-tag>
                    <span v-if="log.duration_ms != null" class="exec-log__dur">
                      {{ fmtMs(log.duration_ms) }}
                    </span>
                  </div>
                  <!-- 失败原因：用失败分类配色高亮（统一色源 format.js） -->
                  <div
                    v-if="log.state === 'failed' && log.error"
                    class="exec-log__error"
                    :style="{ color: failureColor(log.failure_category) }"
                  >
                    <span
                      v-if="log.failure_category"
                      class="exec-log__cat"
                      :style="{ background: failureColor(log.failure_category) }"
                    >
                      {{ log.failure_category }}
                    </span>
                    {{ log.error }}
                  </div>
                </div>
              </div>
              <el-empty
                v-if="!logs.length"
                description="点击「开始执行」查看逐步执行日志"
                :image-size="60"
              />
            </div>
          </el-card>
        </div>
      </div>
    </template>

    <!-- ================== 反馈对话框 ================== -->
    <el-dialog v-model="feedbackVisible" title="执行反馈" width="440px" align-center>
      <div class="exec-feedback">
        <div class="exec-feedback__row">
          <span class="exec-feedback__label">本次执行评分</span>
          <el-rate v-model="feedback.rating" show-text :texts="['很差', '较差', '一般', '不错', '很好']" />
        </div>
        <div class="exec-feedback__row exec-feedback__row--col">
          <span class="exec-feedback__label">评价意见</span>
          <el-input
            v-model="feedback.comment"
            type="textarea"
            :rows="4"
            maxlength="300"
            show-word-limit
            placeholder="请描述执行效果、问题或改进建议，您的反馈将沉淀为优质样本反哺平台"
          />
        </div>
      </div>
      <template #footer>
        <el-button @click="feedbackVisible = false">稍后再说</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmitFeedback">
          提交反馈
        </el-button>
      </template>
    </el-dialog>

    <!-- ================== 策略对比对话框 ================== -->
    <el-dialog v-model="compareVisible" title="策略对比" width="640px" align-center>
      <div v-loading="compareLoading" class="exec-compare">
        <template v-if="compareData?.results?.length">
          <div class="exec-compare__grid">
            <div
              v-for="r in compareData.results"
              :key="r.strategy"
              class="exec-compare__col"
            >
              <div class="exec-compare__name">{{ strategyLabel(r.strategy) }}</div>
              <el-tag
                :type="r.success ? 'success' : 'danger'"
                effect="dark"
                class="exec-compare__result"
              >
                {{ r.success ? '执行成功' : '执行失败' }}
              </el-tag>
              <ul class="exec-compare__stats">
                <li>
                  <span>步骤数</span>
                  <b>{{ r.step_count }}</b>
                </li>
                <li>
                  <span>总耗时</span>
                  <b>{{ fmtMs(r.total_duration_ms) }}</b>
                </li>
                <li>
                  <span>重试次数</span>
                  <b>{{ r.retry_count }}</b>
                </li>
              </ul>
            </div>
          </div>
          <p class="exec-compare__tip">
            提示：两种策略对同一任务各模拟一次，可直观比较拆解粒度、执行耗时与稳定性差异。
          </p>
          <!--
            口径说明（重要）：此处为「单次仿真」对比，结果受随机性影响，单看一次可能出现
            规则/大模型互有胜负的偶然情况，不代表策略优劣的统计规律。真正的策略选型结论应看
            数据看板中基于 150+ 历史样本聚合的成功率 / 平均耗时 / 五维雷达对比。
          -->
          <el-alert
            class="exec-compare__note"
            type="info"
            :closable="false"
            show-icon
            title="本对比为单次仿真，受随机性影响"
          >
            <template #default>
              单次结果可能出现偶然的胜负反转，不代表策略优劣的统计规律。
              策略选型的可靠结论请以「数据看板」中基于 <b>150+ 历史样本</b> 聚合的
              成功率 / 平均耗时 / 五维雷达对比为准。
            </template>
          </el-alert>
        </template>
        <el-empty v-else-if="!compareLoading" description="暂无对比数据" :image-size="60" />
      </div>
      <template #footer>
        <el-button type="primary" plain @click="goDashboard">查看数据看板统计规律</el-button>
        <el-button type="primary" @click="compareVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.execution {
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: 100%;
}

/* -------- 顶部工具条 -------- */
.exec-toolbar :deep(.el-card__body) {
  padding: 14px 18px;
}
.exec-toolbar__row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.exec-toolbar__left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.exec-toolbar__label {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
}
.exec-toolbar__phase {
  margin-left: 4px;
}
.exec-toolbar__right {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* -------- 主区布局 -------- */
.exec-main {
  display: grid;
  grid-template-columns: 1.25fr 1fr;
  gap: 14px;
  flex: 1;
  min-height: 0;
}
.exec-sim :deep(.el-card__body) {
  height: 100%;
}
.exec-side {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}

/* 卡片小标题 */
.exec-card-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
}

/* -------- 进度卡 -------- */
.exec-progress__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.exec-progress__step {
  font-size: 13px;
  color: #2563eb;
  font-weight: 600;
}
.exec-progress__meta {
  display: flex;
  gap: 12px;
  margin-top: 14px;
}
.exec-progress__meta-item {
  flex: 1;
  background: #f5f7fa;
  border-radius: 8px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.exec-progress__meta-label {
  font-size: 12px;
  color: #94a3b8;
}
.exec-progress__meta-value {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums; /* 数字等宽，倒计时不跳动 */
}
.exec-progress__fail {
  margin-top: 12px;
}

/* -------- 日志卡 -------- */
.exec-log {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.exec-log :deep(.el-card__body) {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.exec-log__title {
  margin-bottom: 10px;
}
.exec-log__list {
  flex: 1;
  overflow-y: auto;
  min-height: 120px;
  padding-right: 4px;
}
.exec-log__item {
  display: flex;
  gap: 10px;
  padding: 8px 8px;
  border-radius: 8px;
  transition: background 0.2s;
}
.exec-log__item.is-active {
  background: #eef4ff;
}
.exec-log__idx {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #e2e8f2;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.exec-log__body {
  flex: 1;
  min-width: 0;
}
.exec-log__line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.exec-log__skill {
  font-size: 13px;
  font-weight: 600;
  color: #1f2d3d;
}
.exec-log__code {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 400;
  margin-left: 2px;
}
.exec-log__dur {
  font-size: 12px;
  color: #94a3b8;
}
.exec-log__error {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.exec-log__cat {
  color: #fff;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
}

/* -------- 反馈对话框 -------- */
.exec-feedback {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.exec-feedback__row {
  display: flex;
  align-items: center;
  gap: 16px;
}
.exec-feedback__row--col {
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
}
.exec-feedback__label {
  font-size: 14px;
  font-weight: 600;
  color: #1f2d3d;
}

/* -------- 策略对比对话框 -------- */
.exec-compare {
  min-height: 120px;
}
.exec-compare__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.exec-compare__col {
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  padding: 16px;
  text-align: center;
}
.exec-compare__name {
  font-size: 15px;
  font-weight: 700;
  color: #1f2d3d;
  margin-bottom: 10px;
}
.exec-compare__result {
  margin-bottom: 12px;
}
.exec-compare__stats {
  list-style: none;
  margin: 0;
  padding: 0;
}
.exec-compare__stats li {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-top: 1px dashed #eef1f6;
  font-size: 13px;
  color: #475569;
}
.exec-compare__stats li b {
  color: #2563eb;
  font-size: 14px;
}
.exec-compare__tip {
  margin-top: 14px;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.6;
}
/* 单次仿真口径说明：提醒对比受随机性影响，统计规律看数据看板 */
.exec-compare__note {
  margin-top: 10px;
}
.exec-compare__note :deep(.el-alert__description) {
  line-height: 1.6;
}
@media (max-width: 700px) {
  .exec-main { grid-template-columns: 1fr; gap: 12px; }
  .exec-toolbar__row, .exec-toolbar__left { align-items: stretch; }
  .exec-toolbar__left { flex-wrap: wrap; }
  .exec-toolbar__right { width: 100%; }
  .exec-toolbar__right :deep(.el-button) { flex: 1; margin-left: 0; min-width: 74px; }
  .exec-progress__meta { flex-direction: column; gap: 8px; }
  .exec-compare__grid { grid-template-columns: 1fr; }
}
</style>
