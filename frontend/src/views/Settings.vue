<template>
  <!--
    系统设置页（Settings.vue）
    ============================================================
    产品定位：
      平台的统一配置中心，覆盖四大块：
        ① 大模型配置：选择 provider（openai/qwen/zhipu/mock）、模型、API Key、温度。
           顶部通过 getHealth() 实时展示当前是 Mock 模式还是已接入真实大模型。
        ② 仿真配置：房间尺寸、机器人速度，供 2D 仿真使用。
        ③ 数据配置：历史数据保留天数、是否自动清理。
        ④ 技能库管理：getSkills 表格，支持新增/编辑/删除/启停（createSkill / updateSkill / deleteSkill）。
    依赖 API（src/api/index.js）：
      getSettings / saveSettings / getHealth /
      getSkills / createSkill / updateSkill / deleteSkill
    设计约定：保存均有 ElMessage 成功提示；表单含友好校验。
  -->
  <div class="settings-page">
    <!-- 顶部标题 + 当前模式徽标 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">系统设置</h2>
        <p class="page-subtitle">配置大模型、仿真参数、数据策略与原子技能库</p>
      </div>
      <!-- 顶部 getHealth 显示当前 Mock / 已接入 -->
      <div class="health-badge">
        <el-tag
          v-if="health"
          :type="health.mock_mode ? 'warning' : 'success'"
          effect="dark"
          size="large"
        >
          {{ health.mock_mode ? 'Mock 模式（未接入真实大模型）' : `已接入：${providerLabel(health.llm_provider)}` }}
        </el-tag>
        <el-tag v-else type="info" size="large">健康状态加载中…</el-tag>
      </div>
    </div>

    <el-row :gutter="16">
      <!-- ========== ① 大模型配置 ========== -->
      <el-col :xs="24" :md="12">
        <el-card shadow="never" class="block-card">
          <template #header>
            <div class="card-head">
              <el-icon class="head-icon"><Cpu /></el-icon>
              <span>大模型配置</span>
            </div>
          </template>

          <el-form
            ref="llmFormRef"
            :model="llmForm"
            :rules="llmRules"
            label-width="100px"
          >
            <el-form-item label="服务提供商" prop="provider">
              <el-select v-model="llmForm.provider" style="width: 100%" @change="onProviderChange">
                <el-option label="OpenAI" value="openai" />
                <el-option label="通义千问（qwen）" value="qwen" />
                <el-option label="智谱 AI（zhipu）" value="zhipu" />
                <el-option label="Mock 模拟（本地，无需联网）" value="mock" />
              </el-select>
            </el-form-item>

            <el-form-item label="模型名称" prop="model">
              <el-input
                v-model="llmForm.model"
                placeholder="如 gpt-4o-mini / qwen-plus / glm-4"
                :disabled="llmForm.provider === 'mock'"
              />
            </el-form-item>

            <el-form-item label="API Key" prop="api_key">
              <el-input
                v-model="llmForm.api_key"
                type="password"
                show-password
                clearable
                :placeholder="apiKeyPlaceholder"
                :disabled="llmForm.provider === 'mock'"
              />
              <div class="field-tip">
                <span v-if="settings && settings.llm && settings.llm.api_key_set">
                  已配置 API Key（出于安全不回显明文，留空则保持不变）
                </span>
                <span v-else>Key 仅保存在本地后端，不会回传明文。留空即使用 Mock 模式。</span>
              </div>
            </el-form-item>

            <el-form-item label="采样温度" prop="temperature">
              <el-slider
                v-model="llmForm.temperature"
                :min="0"
                :max="1"
                :step="0.05"
                show-input
                :disabled="llmForm.provider === 'mock'"
              />
              <div class="field-tip">温度越低输出越稳定（推荐 0.2~0.4），越高越发散。</div>
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                :icon="Check"
                :loading="savingLlm"
                @click="saveLlm"
              >
                保存大模型配置
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <!-- ========== ② 仿真配置 ③ 数据配置 ========== -->
      <el-col :xs="24" :md="12">
        <!-- ② 仿真配置 -->
        <el-card shadow="never" class="block-card">
          <template #header>
            <div class="card-head">
              <el-icon class="head-icon"><MagicStick /></el-icon>
              <span>仿真配置</span>
            </div>
          </template>

          <el-form
            ref="simFormRef"
            :model="simForm"
            :rules="simRules"
            label-width="100px"
          >
            <el-form-item label="房间尺寸" prop="room_size">
              <el-input-number
                v-model="simForm.room_size"
                :min="4"
                :max="40"
                :step="1"
              />
              <span class="unit-text">米（正方形房间边长，供 2D 俯视仿真使用）</span>
            </el-form-item>

            <el-form-item label="机器人速度" prop="robot_speed">
              <el-input-number
                v-model="simForm.robot_speed"
                :min="0.1"
                :max="5"
                :step="0.1"
                :precision="1"
              />
              <span class="unit-text">米/秒（影响仿真动画播放节奏）</span>
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                :icon="Check"
                :loading="savingSim"
                @click="saveSim"
              >
                保存仿真配置
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- ③ 数据配置 -->
        <el-card shadow="never" class="block-card">
          <template #header>
            <div class="card-head">
              <el-icon class="head-icon"><Coin /></el-icon>
              <span>数据配置</span>
            </div>
          </template>

          <el-form
            ref="dataFormRef"
            :model="dataForm"
            :rules="dataRules"
            label-width="100px"
          >
            <el-form-item label="保留天数" prop="retention_days">
              <el-input-number
                v-model="dataForm.retention_days"
                :min="1"
                :max="365"
                :step="1"
              />
              <span class="unit-text">天（超出保留期的历史任务可被清理）</span>
            </el-form-item>

            <el-form-item label="自动清理">
              <el-switch
                v-model="dataForm.auto_clean"
                active-text="开启"
                inactive-text="关闭"
              />
              <div class="field-tip">开启后系统会按保留天数自动清理过期历史数据。</div>
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                :icon="Check"
                :loading="savingData"
                @click="saveData"
              >
                保存数据配置
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <!-- ========== ④ 技能库管理 ========== -->
    <el-card shadow="never" class="block-card skill-card">
      <template #header>
        <div class="card-head">
          <el-icon class="head-icon"><Grid /></el-icon>
          <span>原子技能库管理</span>
          <span class="skill-count">（共 {{ skills.length }} 个技能）</span>
          <el-button
            class="add-skill-btn"
            type="primary"
            :icon="Plus"
            size="small"
            @click="openSkillDialog()"
          >
            新增技能
          </el-button>
        </div>
      </template>

      <!-- 分类筛选 -->
      <div class="skill-filter">
        <el-radio-group v-model="skillCategoryFilter" @change="loadSkills">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button
            v-for="cat in skillCategories"
            :key="cat"
            :label="cat"
          >
            {{ cat }}
          </el-radio-button>
        </el-radio-group>
      </div>

      <el-table
        v-loading="skillLoading"
        :data="skills"
        stripe
        style="width: 100%"
        empty-text="暂无技能"
      >
        <el-table-column prop="icon" label="图标" width="64" align="center">
          <template #default="{ row }">
            <span class="skill-emoji">{{ row.icon }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="code" label="编码" width="120">
          <template #default="{ row }">
            <code class="skill-code">{{ row.code }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="中文名" width="110" />
        <el-table-column prop="category" label="分类" width="100" align="center">
          <template #default="{ row }">
            <el-tag size="small" :style="categoryTagStyle(row.category)" effect="light">
              {{ row.category }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
        <el-table-column label="启停" width="90" align="center">
          <template #default="{ row }">
            <!-- 启停：调用 updateSkill 切换 enabled -->
            <el-switch
              :model-value="!!row.enabled"
              @change="(val) => toggleSkill(row, val)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="Edit" @click="openSkillDialog(row)">
              编辑
            </el-button>
            <el-popconfirm
              :title="`确认删除技能「${row.name}」吗？`"
              confirm-button-text="删除"
              cancel-button-text="取消"
              @confirm="onDeleteSkill(row.id)"
            >
              <template #reference>
                <el-button link type="danger" :icon="Delete">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- ===== 技能新增/编辑弹窗 ===== -->
    <el-dialog
      v-model="skillDialogVisible"
      :title="skillEditing ? '编辑技能' : '新增技能'"
      width="560px"
      destroy-on-close
    >
      <el-form
        ref="skillFormRef"
        :model="skillForm"
        :rules="skillRules"
        label-width="92px"
      >
        <el-form-item label="英文编码" prop="code">
          <el-input
            v-model="skillForm.code"
            placeholder="如 MoveTo（唯一）"
            :disabled="skillEditing"
          />
        </el-form-item>
        <el-form-item label="中文名" prop="name">
          <el-input v-model="skillForm.name" placeholder="如 移动到" />
        </el-form-item>
        <el-form-item label="分类" prop="category">
          <el-select v-model="skillForm.category" style="width: 100%">
            <el-option v-for="cat in skillCategories" :key="cat" :label="cat" :value="cat" />
          </el-select>
        </el-form-item>
        <el-form-item label="图标" prop="icon">
          <el-input v-model="skillForm.icon" placeholder="一个 emoji，如 🚶" maxlength="4" />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="skillForm.description"
            type="textarea"
            :rows="2"
            placeholder="技能用途说明"
          />
        </el-form-item>
        <el-form-item label="输入参数">
          <el-input
            v-model="skillForm.input_params_text"
            placeholder="逗号分隔参数名，如 target,force"
          />
          <div class="field-tip">将自动转换为参数对象数组；留空表示无参数。</div>
        </el-form-item>
        <el-form-item label="是否启用">
          <el-switch v-model="skillForm.enabled" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="skillDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingSkill" @click="saveSkill">
          {{ skillEditing ? '保存修改' : '确认新增' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * 系统设置页逻辑
 * ------------------------------------------------------------
 * 关键产品逻辑说明：
 *  1) getSettings 返回 { llm:{provider,model,api_key_set,temperature}, sim:{...}, data:{...} }，
 *     其中 llm.api_key 永远不回显明文（只给 api_key_set 布尔）。因此编辑时 api_key 输入框初始为空：
 *     留空提交 = 保持原 Key 不变；填入新值 = 覆盖。
 *  2) saveSettings 接受"部分配置"，本页按块分别保存（llm/sim/data 各自一个保存按钮），
 *     保存成功后刷新 getHealth，使顶部 Mock/已接入徽标即时更新。
 *  3) 技能库 enabled 启停直接调用 updateSkill，体现技能可被运营动态开关，
 *     影响 task_parser 可用技能集合。
 */
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Cpu, MagicStick, Coin, Grid, Check, Plus, Edit, Delete } from '@element-plus/icons-vue'
import {
  getSettings, saveSettings, getHealth,
  getSkills, createSkill, updateSkill, deleteSkill
} from '../api/index.js'
// 技能分类配色统一取自 utils/format.js（全站唯一色源，与技能库/流程图一致）
import { SKILL_CATEGORY_COLORS, SKILL_CATEGORY_ORDER } from '../utils/format.js'

// 技能 5 大分类（与 SPEC §4 一致），顺序沿用 format.js 的固定展示顺序
const skillCategories = SKILL_CATEGORY_ORDER

// ===== 健康状态 =====
const health = ref(null)
async function loadHealth() {
  try {
    health.value = await getHealth()
  } catch (e) {
    health.value = null
  }
}
// provider 英文 → 中文展示
function providerLabel(p) {
  const map = { openai: 'OpenAI', qwen: '通义千问', zhipu: '智谱 AI', mock: 'Mock' }
  return map[p] || p
}

// ===== 全量设置（用于回显）=====
const settings = ref(null)

// ===== ① 大模型表单 =====
const llmFormRef = ref()
const savingLlm = ref(false)
const llmForm = reactive({
  provider: 'mock',
  model: '',
  api_key: '', // 始终初始为空：留空=不修改
  temperature: 0.3
})
// 大模型表单校验：非 mock 时模型名必填
const llmRules = {
  provider: [{ required: true, message: '请选择服务提供商', trigger: 'change' }],
  model: [
    {
      validator: (rule, value, callback) => {
        if (llmForm.provider !== 'mock' && !value) {
          callback(new Error('请填写模型名称'))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    }
  ]
}
// API Key 输入框占位提示
const apiKeyPlaceholder = computed(() => {
  if (llmForm.provider === 'mock') return 'Mock 模式无需 API Key'
  return settings.value?.llm?.api_key_set ? '已配置，留空则保持不变' : '请输入 API Key'
})
// 切换到 mock 时清空依赖项，避免误校验
function onProviderChange(val) {
  if (val === 'mock') {
    llmFormRef.value?.clearValidate?.()
  }
}
// 保存大模型配置
async function saveLlm() {
  // 触发校验
  const ok = await llmFormRef.value.validate().catch(() => false)
  if (!ok) return
  savingLlm.value = true
  try {
    const llm = {
      provider: llmForm.provider,
      model: llmForm.model,
      temperature: llmForm.temperature
    }
    // 仅当用户填入新 Key 才提交，留空表示保持不变
    if (llmForm.api_key) llm.api_key = llmForm.api_key
    await saveSettings({ llm })
    ElMessage.success('大模型配置已保存')
    llmForm.api_key = '' // 提交后清空输入框，避免误以为明文回显
    await loadSettings() // 刷新 api_key_set
    await loadHealth() // 刷新顶部 Mock/已接入徽标
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    savingLlm.value = false
  }
}

// ===== ② 仿真表单 =====
const simFormRef = ref()
const savingSim = ref(false)
const simForm = reactive({
  room_size: 10,
  robot_speed: 1.0
})
const simRules = {
  room_size: [{ required: true, message: '请填写房间尺寸', trigger: 'blur' }],
  robot_speed: [{ required: true, message: '请填写机器人速度', trigger: 'blur' }]
}
async function saveSim() {
  const ok = await simFormRef.value.validate().catch(() => false)
  if (!ok) return
  savingSim.value = true
  try {
    await saveSettings({ sim: { room_size: simForm.room_size, robot_speed: simForm.robot_speed } })
    ElMessage.success('仿真配置已保存')
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    savingSim.value = false
  }
}

// ===== ③ 数据表单 =====
const dataFormRef = ref()
const savingData = ref(false)
const dataForm = reactive({
  retention_days: 90,
  auto_clean: false
})
const dataRules = {
  retention_days: [{ required: true, message: '请填写保留天数', trigger: 'blur' }]
}
async function saveData() {
  const ok = await dataFormRef.value.validate().catch(() => false)
  if (!ok) return
  savingData.value = true
  try {
    await saveSettings({
      data: { retention_days: dataForm.retention_days, auto_clean: dataForm.auto_clean }
    })
    ElMessage.success('数据配置已保存')
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    savingData.value = false
  }
}

// 拉取全量设置并回显到三个表单
async function loadSettings() {
  try {
    const s = await getSettings()
    settings.value = s
    if (s.llm) {
      llmForm.provider = s.llm.provider || 'mock'
      llmForm.model = s.llm.model || ''
      llmForm.temperature = s.llm.temperature ?? 0.3
      // 注意：api_key 不回显，保持为空
    }
    if (s.sim) {
      simForm.room_size = s.sim.room_size ?? 10
      simForm.robot_speed = s.sim.robot_speed ?? 1.0
    }
    if (s.data) {
      dataForm.retention_days = s.data.retention_days ?? 90
      dataForm.auto_clean = !!s.data.auto_clean
    }
  } catch (e) {
    /* 拦截器已提示 */
  }
}

// ===== ④ 技能库管理 =====
const skillLoading = ref(false)
const skills = ref([])
const skillCategoryFilter = ref('')

async function loadSkills() {
  skillLoading.value = true
  try {
    // 仅在选中具体分类时传 category
    skills.value = await getSkills(skillCategoryFilter.value || undefined)
  } catch (e) {
    skills.value = []
  } finally {
    skillLoading.value = false
  }
}

// 分类 tag 样式（色值来自 format.js 统一映射）
function categoryTagStyle(category) {
  const color = SKILL_CATEGORY_COLORS[category] || '#909399'
  return { color, borderColor: color }
}

// 启停技能：调用 updateSkill 切换 enabled（0/1）
async function toggleSkill(row, val) {
  try {
    await updateSkill(row.id, { enabled: val ? 1 : 0 })
    row.enabled = val ? 1 : 0
    ElMessage.success(val ? `已启用「${row.name}」` : `已停用「${row.name}」`)
  } catch (e) {
    /* 拦截器已提示，回滚由重新加载兜底 */
    loadSkills()
  }
}

// 删除技能
async function onDeleteSkill(id) {
  try {
    await deleteSkill(id)
    ElMessage.success('技能已删除')
    loadSkills()
  } catch (e) {
    /* 拦截器已提示 */
  }
}

// ----- 技能新增/编辑弹窗 -----
const skillDialogVisible = ref(false)
const skillEditing = ref(false) // true=编辑 false=新增
const savingSkill = ref(false)
const skillFormRef = ref()
const skillForm = reactive({
  id: null,
  code: '',
  name: '',
  category: '移动类',
  icon: '',
  description: '',
  input_params_text: '', // 以逗号分隔的参数名，提交时转为对象数组
  enabled: true
})
const skillRules = {
  code: [
    { required: true, message: '请填写英文编码', trigger: 'blur' },
    { pattern: /^[A-Za-z][A-Za-z0-9_]*$/, message: '编码须以字母开头，仅含字母数字下划线', trigger: 'blur' }
  ],
  name: [{ required: true, message: '请填写中文名', trigger: 'blur' }],
  category: [{ required: true, message: '请选择分类', trigger: 'change' }]
}

// 打开弹窗：row 存在=编辑，否则=新增
function openSkillDialog(row) {
  if (row) {
    skillEditing.value = true
    skillForm.id = row.id
    skillForm.code = row.code
    skillForm.name = row.name
    skillForm.category = row.category
    skillForm.icon = row.icon || ''
    skillForm.description = row.description || ''
    // input_params 可能是对象数组，反解析为逗号分隔参数名供编辑
    skillForm.input_params_text = paramsToText(row.input_params)
    skillForm.enabled = !!row.enabled
  } else {
    skillEditing.value = false
    skillForm.id = null
    skillForm.code = ''
    skillForm.name = ''
    skillForm.category = '移动类'
    skillForm.icon = ''
    skillForm.description = ''
    skillForm.input_params_text = ''
    skillForm.enabled = true
  }
  skillDialogVisible.value = true
  // 清除上一次的校验态
  skillFormRef.value?.clearValidate?.()
}

// 把 input_params（对象数组或 JSON 字符串）转为逗号分隔参数名
function paramsToText(input) {
  let arr = input
  if (typeof input === 'string') {
    try {
      arr = JSON.parse(input)
    } catch {
      return ''
    }
  }
  if (!Array.isArray(arr)) return ''
  return arr.map((p) => (typeof p === 'string' ? p : p.name)).filter(Boolean).join(',')
}

// 把逗号分隔参数名转为 SPEC 要求的 [{name,type,desc}] 数组
function textToParams(text) {
  if (!text || !text.trim()) return []
  return text
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((name) => ({ name, type: 'string', desc: '' }))
}

// 保存技能（新增 createSkill / 编辑 updateSkill）
async function saveSkill() {
  const ok = await skillFormRef.value.validate().catch(() => false)
  if (!ok) return
  savingSkill.value = true
  try {
    const payload = {
      code: skillForm.code,
      name: skillForm.name,
      category: skillForm.category,
      icon: skillForm.icon,
      description: skillForm.description,
      input_params: textToParams(skillForm.input_params_text),
      enabled: skillForm.enabled ? 1 : 0
    }
    if (skillEditing.value) {
      await updateSkill(skillForm.id, payload)
      ElMessage.success('技能已更新')
    } else {
      await createSkill(payload)
      ElMessage.success('技能已新增')
    }
    skillDialogVisible.value = false
    loadSkills()
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    savingSkill.value = false
  }
}

// 初次进入：并行加载健康状态、设置、技能库
onMounted(() => {
  loadHealth()
  loadSettings()
  loadSkills()
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 10px;
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

.block-card {
  border-radius: 10px;
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #1f2937;
}
.head-icon {
  color: #2563eb;
  font-size: 18px;
}
.skill-count {
  font-weight: 400;
  font-size: 13px;
  color: #9ca3af;
}
.add-skill-btn {
  margin-left: auto;
}

.field-tip {
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.5;
  margin-top: 2px;
}
.unit-text {
  margin-left: 8px;
  font-size: 12px;
  color: #9ca3af;
}

/* 技能库 */
.skill-card {
  margin-top: 0;
}
.skill-filter {
  margin-bottom: 14px;
}
.skill-emoji {
  font-size: 18px;
}
.skill-code {
  font-family: 'SFMono-Regular', Menlo, monospace;
  font-size: 12px;
  color: #6b7280;
  background: #f3f4f6;
  padding: 1px 6px;
  border-radius: 4px;
}
</style>
