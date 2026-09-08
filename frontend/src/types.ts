export type View = 'overview' | 'composer' | 'macros' | 'runs' | 'settings'

export type Locator = {
  strategy: 'role' | 'label' | 'test_id' | 'text' | 'css' | 'placeholder'
  value: string
  name?: string | null
  exact?: boolean
}

export type Step = {
  id: string
  action: string
  description: string
  locator?: Locator | null
  url?: string | null
  value?: string | number | boolean | null
  value_ref?: string | null
  key?: string | null
  condition?: { kind: string; locator?: Locator | null; expected?: string | null } | null
  record_locator?: Locator | null
  fields?: { name: string; locator: Locator; attribute?: string | null }[]
  pagination?: { next_locator: Locator; max_pages: number | string } | null
  output_key?: string | null
  filename?: string | null
  export_format?: 'csv' | 'json'
  timeout_ms: number
  retry_attempts: number
}

export type MacroParameter = {
  name: string
  label: string
  type: string
  required: boolean
  default?: string | number | boolean | null
}

export type Macro = {
  schema_version: '1.0'
  id?: string | null
  name: string
  description: string
  starting_url: string
  parameters: MacroParameter[]
  steps: Step[]
  expected_outputs: string[]
  created_at?: string | null
  modified_at?: string | null
}

export type Run = {
  id: string
  macro_id?: string | null
  status: string
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  macro: Macro
  variables?: Record<string, unknown>
  options?: Record<string, unknown>
  outputs?: Record<string, unknown>
  artifacts?: { kind: string; name: string; url: string }[]
  error?: { kind?: string; message: string; url?: string; screenshot?: string; page_excerpt?: string }
  repairs?: { step_id: string; outcome: string; attempt: number; error?: string }[]
  current_url?: string | null
}

export type EventItem = {
  id: number
  type: string
  created_at?: string
  status?: string
  message?: string
  step_id?: string
  description?: string
  action?: string
  elapsed_ms?: number
  outputs?: unknown
  screenshot?: string
  url?: string
  outcome?: string
}

export type ModelSettings = {
  endpoint: string
  model: string
  timeout_seconds: number
  supports_images: boolean
  supports_structured_output: boolean
  api_key_configured: boolean
  source: string
}
