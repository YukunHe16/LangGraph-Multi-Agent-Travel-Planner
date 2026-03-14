#!/usr/bin/env node

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const checks = new Set(process.argv.slice(2).map((item) => String(item).toLowerCase()))
if (checks.size === 0) {
  checks.add('nationality')
  checks.add('export')
}

const read = (relativePath) => readFileSync(resolve(process.cwd(), relativePath), 'utf-8')

const types = read('src/types/index.ts')
const home = read('src/views/Home.vue')
const result = read('src/views/Result.vue')

const assert = (condition, message) => {
  if (!condition) {
    throw new Error(message)
  }
}

if (checks.has('nationality')) {
  assert(/nationality:\s*string/.test(types), 'TripFormData 缺少 nationality 类型字段')
  assert(/name="nationality"/.test(home), 'Home.vue 缺少 nationality 表单项')
  assert(/v-model:value="formData\.nationality"/.test(home), 'Home.vue 未绑定 nationality 字段')
}

if (checks.has('export')) {
  assert(/export_to_google_calendar:\s*boolean/.test(types), 'TripFormData 缺少 export_to_google_calendar 类型字段')
  assert(/name="export_to_google_calendar"/.test(home), 'Home.vue 缺少 export_to_google_calendar 表单项')
  assert(/exportToGoogleCalendar/.test(result), 'Result.vue 缺少 Google Calendar 导出交互')
}

console.log(`E1 checks passed: ${Array.from(checks).join(', ')}`)
