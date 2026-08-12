<script setup>
/**
 * TaskEditor.vue —— 任务编排页（核心交互页面）
 *
 * 产品职责（见 SPEC §13）：
 *   三栏布局，把「自然语言 → 结构化任务流程」的拆解与编辑过程可视化。
 *
 *   ┌──────────────┬───────────────────────┬──────────────┐
 *   │  左栏 输入区   │     中栏 流程图          │  右栏 技能库   │
 *   │  - textarea  │  <TaskFlowChart>      │ <SkillLibrary>│
 *   │  - 策略 radio │  目标/约束/动作/异常四区  │ 5 分类技能卡片 │
 *   │  - 拆解按钮    │  步骤增删改排序           │ 添加到流程     │
 *   │  - 10 示例标签 │                       │              │
 *   └──────────────┴───────────────────────┴──────────────┘
 *
 *   底部「去执行」：把当前拆解结果存入 sessionStorage('parsedTask')，跳转 /execution。
 *
 * 三组件协同：
 *   - 「拆解任务」按钮调用 parseTask(instruction, strategy) 得到 ParsedTask，
 *     用 v-model:parsed 传给 <TaskFlowChart> 渲染；
 *   - <SkillLibrary> 的 add-skill 事件 → 调用 flowChartRef.addSkillStep(skill)，
 *     把技能追加为流程图里的一个步骤（技能库与流程图联动）。
 */
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Right } from '@element-plus/icons-vue'
import { getExamples, parseTask } from '../api/index.js'
import TaskFlowChart from '../components/TaskFlowChart.vue'
import SkillLibrary from '../components/SkillLibrary.vue'

const router = useRouter()

// ---------------------------------------------------------------------------
// 左栏状态
// ---------------------------------------------------------------------------
const instruction = ref('') // 用户输入的自然语言指令
const strategy = ref('llm') // 拆解策略：llm（大模型，可能为 Mock）/ rule（规则）
const examples = ref([]) // 10 个预置示例指令（来自后端 getExamples）
const parsing = ref(false) // 拆解中状态，控制按钮 loading

// ---------------------------------------------------------------------------
// 中栏状态
// ---------------------------------------------------------------------------
const parsed = ref(null) // 当前拆解结果（ParsedTask），与 TaskFlowChart v-model 绑定
const flowChartRef = ref(null) // 流程图组件实例引用，用于调用其 addSkillStep 方法

/**
 * 加载 10 个预置示例指令（SPEC §6）。
 * 失败由 axios 拦截器统一提示，这里兜底空数组。
 */
async function loadExamples() {
  try {
    const data = await getExamples()
    examples.value = Array.isArray(data) ? data : []
  } catch (e) {
    examples.value = []
  }
}

/**
 * 点击示例标签：把示例指令填入输入框（不自动拆解，给用户确认空间）。
 * 输入框内容变化本身即是反馈，不再额外弹消息打扰。
 */
function fillExample(ex) {
  instruction.value = ex.instruction
}

/**
 * 难度对应的标签类型，用于示例标签着色（简单=绿 / 中等=橙 / 困难=红）。
 */
function difficultyType(difficulty) {
  if (difficulty === '简单') return 'success'
  if (difficulty === '中等') return 'warning'
  if (difficulty === '困难') return 'danger'
  return 'info'
}

/**
 * 核心动作：调用后端拆解任务。
 * - 校验输入非空；
 * - 调 parseTask(instruction, strategy) → ParsedTask；
 * - 赋给 parsed，TaskFlowChart 自动渲染四区结果。
 */
async function handleParse() {
  if (!instruction.value.trim()) {
    ElMessage.warning('请先输入或选择一条任务指令')
    return
  }
  parsing.value = true
  try {
    const result = await parseTask(instruction.value.trim(), strategy.value)
    parsed.value = result
    ElMessage.success('任务拆解完成，可在中间流程图中调整')
  } catch (e) {
    // 错误提示已由拦截器处理
  } finally {
    parsing.value = false
  }
}

/**
 * 技能库联动：接收 SkillLibrary 的 add-skill 事件，
 * 转交给流程图组件把技能追加为一个步骤。
 */
function handleAddSkill(skill) {
  if (flowChartRef.value && typeof flowChartRef.value.addSkillStep === 'function') {
    flowChartRef.value.addSkillStep(skill)
  }
}

/**
 * 底部「去执行」：
 * - 校验已有拆解结果且至少有一步；
 * - 把 parsed 序列化存入 sessionStorage('parsedTask')（与 Execution 页约定的 key）；
 * - 跳转 /execution。
 */
function goExecute() {
  if (!parsed.value || !parsed.value.steps || !parsed.value.steps.length) {
    ElMessage.warning('当前没有可执行的步骤，请先拆解任务或添加技能')
    return
  }
  // 一并带上当前选择的策略，供执行页默认选中
  const payload = { ...parsed.value, strategy: strategy.value }
  sessionStorage.setItem('parsedTask', JSON.stringify(payload))
  router.push('/execution')
}

onMounted(loadExamples)
</script>

<template>
  <div class="task-editor">
    <!-- 页面标题 -->
    <div class="page-title">
      <h2>任务编排</h2>
      <span class="subtitle">输入自然语言指令，自动拆解为可执行的原子技能动作序列</span>
    </div>

    <!-- 三栏主体 -->
    <div class="editor-grid">
      <!-- ===================== 左栏：输入区 ===================== -->
      <div class="col col-input">
        <div class="panel">
          <div class="panel-title">指令输入</div>

          <el-input
            v-model="instruction"
            type="textarea"
            :rows="5"
            resize="none"
            placeholder="请输入自然语言任务指令，例如：把红色的杯子放到桌子右边"
            class="instruction-input"
          />

          <!-- 拆解策略选择 -->
          <div class="strategy-block">
            <div class="block-label">拆解策略</div>
            <el-radio-group v-model="strategy">
              <el-radio-button label="llm">大模型拆解</el-radio-button>
              <el-radio-button label="rule">规则拆解</el-radio-button>
            </el-radio-group>
            <div class="strategy-hint">
              {{
                strategy === 'llm'
                  ? '调用大模型理解指令（未配置 Key 时自动使用 Mock 高质量拆解）'
                  : '基于关键词的规则引擎拆解，无需大模型，稳定可解释'
              }}
            </div>
          </div>

          <!-- 拆解按钮 -->
          <el-button
            type="primary"
            size="large"
            :loading="parsing"
            class="parse-btn"
            @click="handleParse"
          >
            拆解任务
          </el-button>

          <!-- 10 个示例指令 -->
          <div class="examples-block">
            <div class="block-label">示例指令（点击填入）</div>
            <div class="examples-list">
              <el-tag
                v-for="(ex, i) in examples"
                :key="i"
                :type="difficultyType(ex.difficulty)"
                effect="light"
                class="example-tag"
                @click="fillExample(ex)"
              >
                {{ ex.instruction }}
                <span class="ex-meta">[{{ ex.task_type }}·{{ ex.difficulty }}]</span>
              </el-tag>
            </div>
          </div>
        </div>
      </div>

      <!-- ===================== 中栏：流程图 ===================== -->
      <div class="col col-flow">
        <div class="panel flow-panel">
          <div class="panel-title">
            任务流程
            <span class="flow-hint">目标 · 约束 · 动作序列 · 异常处理</span>
          </div>
          <div class="flow-wrap">
            <!-- v-model:parsed 双向绑定；ref 用于技能库联动调用 addSkillStep -->
            <TaskFlowChart ref="flowChartRef" v-model:parsed="parsed" />
          </div>
        </div>
      </div>

      <!-- ===================== 右栏：技能库 ===================== -->
      <div class="col col-skill">
        <!-- add-skill 事件 → 追加为流程图步骤 -->
        <SkillLibrary @add-skill="handleAddSkill" />
      </div>
    </div>

    <!-- ===================== 底部操作条 ===================== -->
    <div class="footer-bar">
      <span class="footer-tip">
        编排完成后点击右侧按钮进入执行模拟
      </span>
      <el-button type="primary" size="large" @click="goExecute">
        去执行
        <el-icon class="el-icon--right"><Right /></el-icon>
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.task-editor {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.page-title {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 12px;
}
.page-title h2 {
  margin: 0;
  font-size: 20px;
  color: #1f2937;
}
.subtitle {
  font-size: 13px;
  color: #9ca3af;
}

/* 三栏栅格：左 320 / 中 自适应 / 右 360 */
.editor-grid {
  flex: 1;
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr) 360px;
  gap: 16px;
  min-height: 0; /* 允许内部滚动 */
}
.col {
  min-height: 0;
  min-width: 0;
}

.panel {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  padding: 16px 20px;
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
}
/* 面板标题：左侧主色竖条（替代 emoji），与全站 section-title 一致 */
.panel-title {
  position: relative;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  padding-left: 12px;
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.panel-title::before {
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
.flow-hint,
.flow-panel .flow-hint {
  font-size: 12px;
  font-weight: 400;
  color: #9ca3af;
}

/* 左栏 */
.col-input .panel {
  overflow-y: auto;
}
.instruction-input {
  margin-bottom: 14px;
}
.block-label {
  font-size: 13px;
  font-weight: 600;
  color: #4b5563;
  margin-bottom: 8px;
}
.strategy-block {
  margin-bottom: 14px;
}
.strategy-hint {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 8px;
  line-height: 1.5;
}
.parse-btn {
  width: 100%;
  margin-bottom: 18px;
}
.examples-block {
  margin-top: 4px;
}
.examples-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.example-tag {
  cursor: pointer;
  white-space: normal;
  height: auto;
  line-height: 1.5;
  padding: 6px 10px;
  text-align: left;
  transition: transform 0.15s;
}
.example-tag:hover {
  transform: translateX(2px);
}
.ex-meta {
  font-size: 11px;
  opacity: 0.7;
  margin-left: 4px;
}

/* 中栏 */
.flow-panel {
  padding-bottom: 8px;
}
.flow-wrap {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* 底部操作条 */
.footer-bar {
  margin-top: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  padding: 12px 20px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
}
.footer-tip {
  font-size: 13px;
  color: #9ca3af;
}

/* 窄屏自适应：栈式排列 */
@media (max-width: 1280px) {
  .editor-grid {
    grid-template-columns: 280px minmax(0, 1fr) 320px;
  }
}
</style>
