import { useEffect, useMemo, useState } from 'react'
import { api, formatDate, parseVariables } from './api'
import type { EventItem, Macro, ModelSettings, Run, Step, View } from './types'

const exampleInstruction = 'Open the product catalog, search for {{search_term}}, collect the name, price, and URL of each result across up to {{max_pages}} pages, and export the results to CSV.'
const exampleUrl = `${window.location.origin}/demo/catalog`

const navItems: { id: View; label: string; icon: string }[] = [
  { id: 'overview', label: 'Overview', icon: '◈' },
  { id: 'composer', label: 'Task composer', icon: '✦' },
  { id: 'macros', label: 'Macro library', icon: '⌘' },
  { id: 'runs', label: 'Run history', icon: '◷' },
  { id: 'settings', label: 'Settings', icon: '⚙' },
]

function App() {
  const [view, setView] = useState<View>('overview')
  const [macros, setMacros] = useState<Macro[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [settings, setSettings] = useState<ModelSettings | null>(null)
  const [selectedRun, setSelectedRun] = useState<Run | null>(null)
  const [activeMacro, setActiveMacro] = useState<Macro | null>(null)
  const [notice, setNotice] = useState<{ kind: 'success' | 'error' | 'info'; text: string } | null>(null)

  const refresh = async () => {
    try {
      const [macroList, runList, modelSettings] = await Promise.all([
        api<Macro[]>('/api/macros'),
        api<Run[]>('/api/runs'),
        api<ModelSettings>('/api/settings/model'),
      ])
      setMacros(macroList)
      setRuns(runList)
      setSettings(modelSettings)
      if (selectedRun) {
        const latest = runList.find((run) => run.id === selectedRun.id)
        if (latest) setSelectedRun(latest)
      }
    } catch (error) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'Could not load the workspace.' })
    }
  }

  useEffect(() => { void refresh() }, [])
  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), 5000)
    return () => window.clearTimeout(timer)
  }, [notice])

  const activeRun = runs.find((run) => ['Planning', 'Running', 'Paused'].includes(run.status))

  const navigate = (next: View) => setView(next)
  const openMacro = (macro: Macro) => { setActiveMacro(macro); setView('composer') }
  const handleRunSelected = (run: Run) => { setSelectedRun(run); setView('runs') }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">A</span><span>automata</span><span className="brand-dot">●</span></div>
        <p className="sidebar-kicker">LOCAL WORKSPACE</p>
        <nav className="nav-list">
          {navItems.map((item) => <button key={item.id} className={`nav-item ${view === item.id ? 'active' : ''}`} onClick={() => navigate(item.id)}><span className="nav-icon">{item.icon}</span>{item.label}{item.id === 'macros' && macros.length > 0 && <span className="nav-count">{macros.length}</span>}</button>)}
        </nav>
        <div className="sidebar-bottom">
          <div className="security-card"><span className="status-orb green" /><div><strong>Local-first</strong><span>Your runs stay here.</span></div></div>
          <button className="demo-link" onClick={() => window.open('/demo/catalog', '_blank')}>Open demo website <span>↗</span></button>
        </div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div><span className="eyebrow">AUTOMATION STUDIO</span><h1>{navItems.find((item) => item.id === view)?.label}</h1></div>
          <div className="topbar-actions">
            <div className={`connection-pill ${settings?.api_key_configured ? 'ready' : ''}`}><span className="status-orb" />{settings?.api_key_configured ? 'Model connected' : 'Model not configured'}</div>
            {activeRun && <button className="run-chip" onClick={() => handleRunSelected(activeRun)}><span className="pulse" />{activeRun.status} <span>→</span></button>}
          </div>
        </header>
        {notice && <div className={`notice ${notice.kind}`}>{notice.kind === 'error' ? '!' : '✓'} {notice.text}</div>}
        {view === 'overview' && <Overview macros={macros} runs={runs} settings={settings} onCompose={() => { setActiveMacro(null); setView('composer') }} onOpenMacro={openMacro} onOpenRun={handleRunSelected} onOpenMacros={() => setView('macros')} onOpenRuns={() => setView('runs')} />}
        {view === 'composer' && <Composer initialMacro={activeMacro} onSaved={(macro) => { setActiveMacro(macro); void refresh(); setNotice({ kind: 'success', text: 'Macro saved to the local library.' }) }} onRun={(run) => { setSelectedRun(run); void refresh(); setNotice({ kind: 'success', text: 'Browser run started. Live events are streaming below.' }) }} onError={(text) => setNotice({ kind: 'error', text })} />}
        {view === 'macros' && <MacroLibrary macros={macros} onRefresh={refresh} onEdit={openMacro} onRun={(run) => { setSelectedRun(run); setView('runs'); void refresh() }} onError={(text) => setNotice({ kind: 'error', text })} />}
        {view === 'runs' && <RunHistory runs={runs} selectedRun={selectedRun} onSelect={setSelectedRun} onRefresh={refresh} onError={(text) => setNotice({ kind: 'error', text })} />}
        {view === 'settings' && <Settings settings={settings} onSaved={(next) => { setSettings(next); setNotice({ kind: 'success', text: 'Model settings saved.' }) }} onError={(text) => setNotice({ kind: 'error', text })} />}
      </main>
    </div>
  )
}

function Overview({ macros, runs, settings, onCompose, onOpenMacro, onOpenRun, onOpenMacros, onOpenRuns }: { macros: Macro[]; runs: Run[]; settings: ModelSettings | null; onCompose: () => void; onOpenMacro: (macro: Macro) => void; onOpenRun: (run: Run) => void; onOpenMacros: () => void; onOpenRuns: () => void }) {
  const completed = runs.filter((run) => run.status === 'Completed').length
  const lastRun = runs[0]
  return <div className="view-stack overview-view">
    <section className="hero-card">
      <div className="hero-copy"><span className="eyebrow bright">PLAIN ENGLISH → RELIABLE MACRO</span><h2>Turn repetitive browser work<br /><em>into something you can trust.</em></h2><p>Plan once, run visibly, and keep every result, screenshot, and repair note on your machine.</p><button className="primary-button" onClick={onCompose}>Create a task <span>✦</span></button></div>
      <div className="hero-orbit"><div className="orbit-ring ring-one" /><div className="orbit-ring ring-two" /><div className="orbit-core">A<span>+</span></div><div className="orbit-label label-one">PLAN</div><div className="orbit-label label-two">RUN</div><div className="orbit-label label-three">REUSE</div></div>
    </section>
    <section className="metric-grid"><Metric label="Saved macros" value={macros.length} detail="Ready to reuse" accent="blue" /><Metric label="Completed runs" value={completed} detail={lastRun ? `Last ${formatDate(lastRun.finished_at)}` : 'No runs yet'} accent="violet" /><Metric label="Model status" value={settings?.api_key_configured ? 'Ready' : 'Setup'} detail={settings?.model || 'OpenAI-compatible'} accent="orange" /></section>
    <div className="two-column">
      <section className="panel recent-panel"><PanelHeading title="Recent runs" action="View all" onAction={onOpenRuns} /><div className="run-list">{runs.slice(0, 4).map((run) => <RunRow key={run.id} run={run} onClick={() => onOpenRun(run)} />)}{runs.length === 0 && <EmptyState icon="◷" title="No runs yet" body="Your first execution will show up here." />}</div></section>
      <section className="panel quick-panel"><PanelHeading title="Your macro library" action="Browse" onAction={onOpenMacros} /><div className="macro-mini-list">{macros.slice(0, 4).map((macro) => <button key={macro.id} className="macro-mini" onClick={() => onOpenMacro(macro)}><span className="macro-icon">⌘</span><span><strong>{macro.name}</strong><small>{macro.steps.length} steps · {macro.parameters.length} inputs</small></span><span className="arrow">→</span></button>)}{macros.length === 0 && <EmptyState icon="⌘" title="Library is empty" body="Save a successful plan to make it reusable." />}</div></section>
    </div>
    <section className="principles-strip"><div><span className="principle-icon">◎</span><span><strong>Deterministic runs</strong><small>Saved macros never call the model again.</small></span></div><div><span className="principle-icon">⌁</span><span><strong>Visible by default</strong><small>Watch the real browser do the work.</small></span></div><div><span className="principle-icon">↺</span><span><strong>Bounded repair</strong><small>Two attempts, fully recorded.</small></span></div></section>
  </div>
}

function Composer({ initialMacro, onSaved, onRun, onError }: { initialMacro: Macro | null; onSaved: (macro: Macro) => void; onRun: (run: Run) => void; onError: (text: string) => void }) {
  const [url, setUrl] = useState(initialMacro?.starting_url || exampleUrl)
  const [instruction, setInstruction] = useState(initialMacro?.description || exampleInstruction)
  const [variablesText, setVariablesText] = useState(JSON.stringify(Object.fromEntries((initialMacro?.parameters || [{ name: 'search_term', default: 'desk' }, { name: 'max_pages', default: 3 }]).map((parameter) => [parameter.name, parameter.default ?? ''])), null, 2))
  const [macro, setMacro] = useState<Macro | null>(initialMacro)
  const [planMeta, setPlanMeta] = useState<{ source?: string; reason?: string; model?: string } | null>(null)
  const [busy, setBusy] = useState<'plan' | 'save' | 'run' | null>(null)
  const [aiRepair, setAiRepair] = useState(false)
  const [pauseBetween, setPauseBetween] = useState(false)
  const parsedVariables = useMemo(() => { try { return parseVariables(variablesText) } catch { return {} } }, [variablesText])

  const generate = async () => {
    if (!url.trim() || instruction.trim().length < 5) return onError('Add a starting URL and a little more detail about the task.')
    setBusy('plan')
    try {
      const response = await api<{ macro: Macro; meta: { source?: string; reason?: string } }>('/api/plans/generate', { method: 'POST', body: JSON.stringify({ starting_url: url, instruction, variables: parsedVariables, use_model: true }) })
      setMacro(response.macro)
      setPlanMeta(response.meta)
    } catch (error) { onError(error instanceof Error ? error.message : 'Could not generate a plan.') } finally { setBusy(null) }
  }
  const save = async () => {
    if (!macro) return onError('Generate or load a plan first.')
    setBusy('save')
    try { const saved = await api<Macro>('/api/macros', { method: 'POST', body: JSON.stringify(macro) }); setMacro(saved); onSaved(saved) } catch (error) { onError(error instanceof Error ? error.message : 'Could not save the macro.') } finally { setBusy(null) }
  }
  const run = async () => {
    if (!macro) return onError('Generate or load a plan first.')
    let variables: Record<string, unknown>
    try { variables = parseVariables(variablesText) } catch (error) { return onError(error instanceof Error ? error.message : 'Invalid variables.') }
    setBusy('run')
    try { const runResult = await api<{ id: string }>('/api/runs', { method: 'POST', body: JSON.stringify({ macro, variables, ai_repair: aiRepair, repair_attempts: 2, pause_between_steps: pauseBetween, session_name: 'default' }) }); const run = await api<Run>(`/api/runs/${runResult.id}`); onRun(run) } catch (error) { onError(error instanceof Error ? error.message : 'Could not start the run.') } finally { setBusy(null) }
  }
  const updateStep = (index: number, patch: Partial<Step>) => setMacro((current) => current ? { ...current, steps: current.steps.map((step, stepIndex) => stepIndex === index ? { ...step, ...patch } : step) } : current)
  return <div className="view-stack composer-view">
    <div className="composer-toolbar"><div><span className="eyebrow">BUILD A REUSABLE WORKFLOW</span><h2>{macro?.name || 'What should the browser do?'}</h2></div><div className="toolbar-buttons"><button className="ghost-button" onClick={() => { setMacro(null); setPlanMeta(null) }}>Clear</button><button className="secondary-button" onClick={save} disabled={!macro || busy !== null}>{busy === 'save' ? 'Saving…' : 'Save macro'}</button><button className="primary-button compact" onClick={run} disabled={!macro || busy !== null}>{busy === 'run' ? 'Starting…' : 'Run plan'} <span>▶</span></button></div></div>
    <div className="composer-grid">
      <section className="panel composer-input-panel"><div className="panel-title-row"><div><span className="section-label">01 · Describe the task</span><h3>Start with intent</h3></div><span className="sparkle">✦</span></div><label className="field-label">Starting URL<input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com" /></label><label className="field-label">Plain-English instruction<textarea rows={8} value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="Tell the browser what to do…" /></label><label className="field-label">Task variables <span className="optional">JSON</span><textarea className="code-input" rows={6} value={variablesText} onChange={(event) => setVariablesText(event.target.value)} /></label><div className="hint-row"><span className="hint-icon">i</span><span>Use <code>{'{{variable_name}}'}</code> in the instruction. Values remain separate from executable steps.</span></div><button className="generate-button" onClick={generate} disabled={busy !== null}>{busy === 'plan' ? <><span className="spinner" /> Planning…</> : <>Generate editable plan <span>→</span></>}</button></section>
      <section className="panel plan-panel"><div className="panel-title-row"><div><span className="section-label">02 · Review and edit</span><h3>{macro ? 'Your automation plan' : 'Your plan will appear here'}</h3></div>{macro && <span className="valid-badge"><span>✓</span> Schema valid</span>}</div>{planMeta && <div className={`plan-note ${planMeta.source === 'model' ? 'model' : ''}`}><span>{planMeta.source === 'model' ? '✦' : '◌'}</span><span>{planMeta.source === 'model' ? `Planned by ${planMeta.model || 'configured model'}.` : planMeta.reason}</span></div>}{macro ? <div className="plan-editor"><label className="field-label compact-field">Macro name<input value={macro.name} onChange={(event) => setMacro({ ...macro, name: event.target.value })} /></label><label className="field-label compact-field">Description<textarea rows={2} value={macro.description} onChange={(event) => setMacro({ ...macro, description: event.target.value })} /></label><div className="step-list">{macro.steps.map((step, index) => <StepEditor key={step.id} step={step} index={index} onChange={updateStep} />)}</div><div className="outputs-row"><span className="section-label">OUTPUTS</span>{macro.expected_outputs.map((output) => <span key={output} className="output-chip">{output}</span>)}</div></div> : <EmptyState icon="✦" title="No plan yet" body="Describe a task on the left, then generate a schema-validated plan." />}</section>
    </div>
    <section className="panel run-options"><div><span className="section-label">03 · Execution options</span><h3>Keep the run under your control</h3></div><label className="toggle-row"><input type="checkbox" checked={aiRepair} onChange={(event) => setAiRepair(event.target.checked)} /><span className="toggle" /><span><strong>AI-assisted repair</strong><small>Allow up to two minimal locator repairs when a step fails.</small></span></label><label className="toggle-row"><input type="checkbox" checked={pauseBetween} onChange={(event) => setPauseBetween(event.target.checked)} /><span className="toggle" /><span><strong>Pause between steps</strong><small>Review the browser state before each next action.</small></span></label><div className="browser-note"><span className="status-orb green" /><span><strong>Visible Chromium</strong><small>Runs use an isolated browser context. Your everyday profile stays separate.</small></span></div></section>
  </div>
}

function StepEditor({ step, index, onChange }: { step: Step; index: number; onChange: (index: number, patch: Partial<Step>) => void }) {
  const locatorText = step.locator ? `${step.locator.strategy}: ${step.locator.value}${step.locator.name ? ` · ${step.locator.name}` : ''}` : step.url || 'No target needed'
  return <article className="step-card"><div className="step-index">{String(index + 1).padStart(2, '0')}</div><div className="step-content"><div className="step-topline"><span className="step-action">{step.action.replace('_', ' ')}</span><span className="step-id">{step.id}</span><span className="step-timeout">{step.timeout_ms / 1000}s</span></div><input className="step-description" value={step.description} onChange={(event) => onChange(index, { description: event.target.value })} /><div className="step-target"><span className="target-icon">⌁</span><span>{locatorText}</span></div>{step.value_ref && <div className="variable-ref"><span>↳</span> uses <code>{`{{${step.value_ref}}}`}</code></div>}</div></article>
}

function MacroLibrary({ macros, onRefresh, onEdit, onRun, onError }: { macros: Macro[]; onRefresh: () => Promise<void>; onEdit: (macro: Macro) => void; onRun: (run: Run) => void; onError: (text: string) => void }) {
  const [query, setQuery] = useState('')
  const filtered = macros.filter((macro) => `${macro.name} ${macro.description}`.toLowerCase().includes(query.toLowerCase()))
  const runMacro = async (macro: Macro) => { try { const variables = Object.fromEntries(macro.parameters.map((parameter) => [parameter.name, parameter.default ?? ''])); const result = await api<{ id: string }>('/api/runs', { method: 'POST', body: JSON.stringify({ macro_id: macro.id, variables, session_name: 'default', ai_repair: false, repair_attempts: 2, pause_between_steps: false }) }); onRun(await api<Run>(`/api/runs/${result.id}`)) } catch (error) { onError(error instanceof Error ? error.message : 'Could not run macro.') } }
  const duplicate = async (macro: Macro) => { try { await api(`/api/macros/${macro.id}/duplicate`, { method: 'POST' }); await onRefresh() } catch (error) { onError(error instanceof Error ? error.message : 'Could not duplicate macro.') } }
  const remove = async (macro: Macro) => { if (!window.confirm(`Delete “${macro.name}”?`)) return; try { await api(`/api/macros/${macro.id}`, { method: 'DELETE' }); await onRefresh() } catch (error) { onError(error instanceof Error ? error.message : 'Could not delete macro.') } }
  return <div className="view-stack"><div className="library-toolbar"><div><span className="eyebrow">REUSE WHAT WORKS</span><h2>Macro library</h2><p>Saved plans run deterministically with new inputs.</p></div><label className="search-box"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search macros" /></label></div><section className="macro-grid">{filtered.map((macro) => <article className="macro-card" key={macro.id}><div className="macro-card-head"><span className="macro-large-icon">⌘</span><div><h3>{macro.name}</h3><p>{macro.description || 'No description'}</p></div><button className="icon-button" title="More actions" onClick={() => duplicate(macro)}>⋯</button></div><div className="macro-meta"><span>{macro.steps.length} steps</span><span>{macro.parameters.length} inputs</span><span>Edited {formatDate(macro.modified_at)}</span></div><div className="macro-card-actions"><button className="secondary-button" onClick={() => runMacro(macro)}>Run now <span>▶</span></button><button className="text-button" onClick={() => onEdit(macro)}>Edit</button><a className="text-button" href={`/api/macros/${macro.id}/export.json`}>JSON</a><a className="text-button" href={`/api/macros/${macro.id}/export.py`}>Python</a><button className="delete-button" onClick={() => remove(macro)}>Delete</button></div></article>)}{filtered.length === 0 && <div className="empty-wide"><EmptyState icon="⌘" title={query ? 'No matching macros' : 'No saved macros yet'} body={query ? 'Try a different search.' : 'Generate a plan, run it, and save it here.'} /></div>}</section></div>
}

function RunHistory({ runs, selectedRun, onSelect, onRefresh, onError }: { runs: Run[]; selectedRun: Run | null; onSelect: (run: Run) => void; onRefresh: () => Promise<void>; onError: (text: string) => void }) {
  return <div className="view-stack"><div className="library-toolbar"><div><span className="eyebrow">OBSERVE AND RECOVER</span><h2>Run history</h2><p>Every action, artifact, and failure stays attached to its run.</p></div><button className="ghost-button" onClick={() => void onRefresh()}>Refresh ↻</button></div><div className="runs-layout"><section className="panel history-panel"><div className="history-header"><span>RUN</span><span>STATUS</span><span>STARTED</span><span>RESULT</span></div>{runs.map((run) => <button className={`history-row ${selectedRun?.id === run.id ? 'selected' : ''}`} key={run.id} onClick={() => onSelect(run)}><div><strong>{run.macro?.name || 'Untitled run'}</strong><small>{run.id.slice(0, 8)} · {run.macro?.steps.length || 0} steps</small></div><StatusBadge status={run.status} /><span>{formatDate(run.started_at || run.created_at)}</span><span>{run.outputs?.records && typeof run.outputs.records === 'object' && 'count' in (run.outputs.records as object) ? `${(run.outputs.records as { count: number }).count} records` : run.error ? 'Needs attention' : run.status === 'Completed' ? 'Complete' : '—'}</span></button>)}{runs.length === 0 && <EmptyState icon="◷" title="No run history" body="Start a plan to create your first run." />}</section>{selectedRun && <RunDetail run={selectedRun} onRefresh={onRefresh} onError={onError} />}</div></div>
}

function RunDetail({ run: initialRun, onRefresh, onError }: { run: Run; onRefresh: () => Promise<void>; onError: (text: string) => void }) {
  const [run, setRun] = useState(initialRun)
  const [events, setEvents] = useState<EventItem[]>([])
  const [screenshot, setScreenshot] = useState<string | null>(null)
  useEffect(() => setRun(initialRun), [initialRun])
  useEffect(() => {
    const source = new EventSource(`/api/runs/${initialRun.id}/events`)
    source.onmessage = (message) => { try { const event = JSON.parse(message.data) as EventItem; setEvents((current) => [...current.slice(-49), event]); if (event.type === 'screenshot') setScreenshot(`${event.url || `/api/runs/${initialRun.id}/screenshot`}?t=${Date.now()}`); if (event.type === 'status' || event.type === 'failed' || event.type === 'done') void api<Run>(`/api/runs/${initialRun.id}`).then(setRun).catch(() => undefined) } catch { /* ignore malformed event */ } }
    source.onerror = () => source.close()
    return () => source.close()
  }, [initialRun.id])
  const control = async (action: 'pause' | 'resume' | 'stop') => { try { await api(`/api/runs/${run.id}/${action}`, { method: 'POST' }); setRun(await api<Run>(`/api/runs/${run.id}`)); await onRefresh() } catch (error) { onError(error instanceof Error ? error.message : `Could not ${action} the run.`) } }
  const isActive = ['Planning', 'Running', 'Paused'].includes(run.status)
  const previewScreenshot = screenshot || (run.artifacts?.find((artifact) => artifact.kind === 'screenshot') ? `/api/runs/${run.id}/screenshot` : null)
  return <section className="panel run-detail"><div className="run-detail-head"><div><span className="section-label">SELECTED RUN</span><h3>{run.macro?.name || 'Run'}</h3><small>{formatDate(run.created_at)} · {run.current_url || run.macro?.starting_url}</small></div><StatusBadge status={run.status} /></div>{isActive && <div className="run-controls"><button className="secondary-button" onClick={() => control(run.status === 'Paused' ? 'resume' : 'pause')}>{run.status === 'Paused' ? 'Resume' : 'Pause'}</button><button className="danger-button" onClick={() => control('stop')}>Stop</button></div>}<div className="run-detail-grid"><div><span className="section-label">LIVE ACTIVITY</span><div className="activity-feed">{events.length ? events.map((event, index) => <div className={`activity-item ${event.type}`} key={`${event.id}-${index}`}><span className="activity-dot" /><div><strong>{event.type === 'step_started' ? event.description : event.type === 'step_completed' ? `${event.step_id} completed` : event.message || event.type.replace('_', ' ')}</strong><small>{event.elapsed_ms ? `${event.elapsed_ms} ms` : event.action || ''}</small></div></div>) : <div className="activity-empty"><span className="pulse" />Waiting for browser events…</div>}</div></div><div className="screenshot-box"><div className="screenshot-head"><span className="section-label">LATEST SCREENSHOT</span>{previewScreenshot && <a href={previewScreenshot} target="_blank">Open ↗</a>}</div>{previewScreenshot ? <img src={previewScreenshot} alt="Latest browser screenshot" /> : <div className="screenshot-empty"><span>▧</span><p>Screenshot preview appears at meaningful checkpoints.</p></div>}</div></div>{run.error && <div className="error-card"><div className="error-icon">!</div><div><strong>{run.error.message}</strong><p>{run.error.page_excerpt || 'Review the failed step and use the screenshot to diagnose the page state.'}</p>{run.error.screenshot && <span className="mono">Failed step: {run.error.screenshot}</span>}</div></div>}{run.outputs && <OutputTable outputs={run.outputs} />}{run.artifacts && run.artifacts.length > 0 && <div className="artifact-list"><span className="section-label">FILES</span>{run.artifacts.map((artifact) => <a key={artifact.name} href={artifact.url} target="_blank">{artifact.kind === 'screenshot' ? '▧' : '↓'} {artifact.name}</a>)}</div>}</section>
}

function OutputTable({ outputs }: { outputs: Record<string, unknown> }) { const records = Array.isArray(outputs.records) ? outputs.records as Record<string, unknown>[] : []; if (!records.length) return <div className="output-summary"><span className="section-label">OUTPUTS</span><pre>{JSON.stringify(outputs, null, 2)}</pre></div>; const columns = Object.keys(records[0] || {}); return <div className="output-table-wrap"><div className="table-title"><span className="section-label">EXTRACTED DATA</span><span>{records.length} records</span></div><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{records.slice(0, 8).map((record, rowIndex) => <tr key={rowIndex}>{columns.map((column) => <td key={column}>{String(record[column] ?? '')}</td>)}</tr>)}</tbody></table>{records.length > 8 && <small className="table-foot">Showing first 8 rows. Download the exported file for the full result.</small>}</div> }

function Settings({ settings, onSaved, onError }: { settings: ModelSettings | null; onSaved: (settings: ModelSettings) => void; onError: (text: string) => void }) {
  const [endpoint, setEndpoint] = useState(settings?.endpoint || 'https://api.openai.com/v1')
  const [model, setModel] = useState(settings?.model || 'gpt-4o-mini')
  const [timeout, setTimeoutValue] = useState(settings?.timeout_seconds || 45)
  const [key, setKey] = useState('')
  const [images, setImages] = useState(settings?.supports_images || false)
  const [structured, setStructured] = useState(settings?.supports_structured_output ?? true)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (settings) { setEndpoint(settings.endpoint); setModel(settings.model); setTimeoutValue(settings.timeout_seconds); setImages(settings.supports_images); setStructured(settings.supports_structured_output) } }, [settings])
  const save = async () => { setBusy(true); try { const next = await api<ModelSettings>('/api/settings/model', { method: 'PUT', body: JSON.stringify({ endpoint, model, timeout_seconds: timeout, supports_images: images, supports_structured_output: structured, api_key: key || null }) }); setKey(''); onSaved(next) } catch (error) { onError(error instanceof Error ? error.message : 'Could not save model settings.') } finally { setBusy(false) } }
  const test = async () => { setBusy(true); try { await api('/api/settings/model/test', { method: 'POST' }); onSaved({ ...(settings as ModelSettings), endpoint, model, timeout_seconds: timeout, supports_images: images, supports_structured_output: structured, api_key_configured: true }) } catch (error) { onError(error instanceof Error ? error.message : 'Connection test failed.') } finally { setBusy(false) } }
  const [sessionName, setSessionName] = useState('default')
  const [sessionUrl, setSessionUrl] = useState(exampleUrl)
  const [sessions, setSessions] = useState<{ name: string; saved: boolean }[]>([])
  const loadSessions = async () => { try { setSessions(await api('/api/sessions')) } catch { /* browser may not be installed yet */ } }
  useEffect(() => { void loadSessions() }, [])
  const openBrowser = async () => { try { await api(`/api/sessions/${encodeURIComponent(sessionName)}/open?url=${encodeURIComponent(sessionUrl)}`, { method: 'POST' }); await loadSessions() } catch (error) { onError(error instanceof Error ? error.message : 'Could not open the browser session.') } }
  const saveSession = async () => { try { await api(`/api/sessions/${encodeURIComponent(sessionName)}/save`, { method: 'POST' }); await loadSessions() } catch (error) { onError(error instanceof Error ? error.message : 'Could not save the browser session.') } }
  const deleteSession = async (name: string) => { try { await api(`/api/sessions/${encodeURIComponent(name)}`, { method: 'DELETE' }); await loadSessions() } catch (error) { onError(error instanceof Error ? error.message : 'Could not remove the browser session.') } }
  return <div className="view-stack settings-view"><div className="library-toolbar"><div><span className="eyebrow">LOCAL CONFIGURATION</span><h2>Settings</h2><p>Keys stay on the backend. Browser sessions are isolated from your everyday profile.</p></div></div><div className="settings-grid"><section className="panel settings-panel"><div className="panel-title-row"><div><span className="section-label">MODEL CONNECTION</span><h3>Provider adapter</h3></div><StatusBadge status={settings?.api_key_configured ? 'Connected' : 'Needs setup'} /></div><label className="field-label">Compatible endpoint<input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} placeholder="https://api.openai.com/v1" /></label><label className="field-label">Model name<input value={model} onChange={(event) => setModel(event.target.value)} placeholder="gpt-4o-mini" /></label><div className="field-row"><label className="field-label">Timeout (seconds)<input type="number" min={5} max={180} value={timeout} onChange={(event) => setTimeoutValue(Number(event.target.value))} /></label><label className="field-label">API key <span className="optional">write-only</span><input type="password" value={key} onChange={(event) => setKey(event.target.value)} placeholder={settings?.api_key_configured ? '••••••••  saved' : 'Paste key locally'} /></label></div><div className="capability-list"><label className="check-row"><input type="checkbox" checked={structured} onChange={(event) => setStructured(event.target.checked)} /><span>Structured JSON output</span></label><label className="check-row"><input type="checkbox" checked={images} onChange={(event) => setImages(event.target.checked)} /><span>Image input for repair</span></label></div><div className="settings-actions"><button className="secondary-button" onClick={test} disabled={busy}>{busy ? 'Testing…' : 'Test connection'}</button><button className="primary-button compact" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save settings'}</button></div><p className="settings-footnote">For a local model, point the endpoint at its OpenAI-compatible <code>/v1</code> server and leave the API key blank.</p></section><section className="panel settings-panel"><div className="panel-title-row"><div><span className="section-label">BROWSER SESSIONS</span><h3>Authorized contexts</h3></div><span className="session-lock">▣ isolated</span></div><p className="panel-description">Open a visible Chromium window, sign in manually if needed, then save the session explicitly for future macro runs.</p><label className="field-label">Session name<input value={sessionName} onChange={(event) => setSessionName(event.target.value)} /></label><label className="field-label">Open URL<input value={sessionUrl} onChange={(event) => setSessionUrl(event.target.value)} /></label><div className="settings-actions"><button className="secondary-button" onClick={openBrowser}>Open visible browser</button><button className="ghost-button" onClick={saveSession}>Save current session</button></div><div className="session-list">{sessions.map((session) => <div className="session-row" key={session.name}><span className="status-orb green" /><span><strong>{session.name}</strong><small>{session.saved ? 'Saved browser state' : 'Open, not saved'}</small></span><button className="delete-button" onClick={() => deleteSession(session.name)}>Remove</button></div>)}{sessions.length === 0 && <p className="muted-copy">No saved sessions yet.</p>}</div></section></div></div>
}

function Metric({ label, value, detail, accent }: { label: string; value: string | number; detail: string; accent: string }) { return <div className={`metric-card ${accent}`}><span className="metric-label">{label}</span><strong>{value}</strong><small>{detail}</small><span className="metric-line" /></div> }
function PanelHeading({ title, action, onAction }: { title: string; action: string; onAction: () => void }) { return <div className="panel-heading"><h3>{title}</h3><button className="text-button" onClick={onAction}>{action} →</button></div> }
function EmptyState({ icon, title, body }: { icon: string; title: string; body: string }) { return <div className="empty-state"><span className="empty-icon">{icon}</span><strong>{title}</strong><p>{body}</p></div> }
function StatusBadge({ status }: { status: string }) { const normalized = status.toLowerCase().replace(' ', '-'); return <span className={`status-badge ${normalized}`}><span />{status}</span> }
function RunRow({ run, onClick }: { run: Run; onClick: () => void }) { return <button className="run-row" onClick={onClick}><span className={`run-status-dot ${run.status.toLowerCase()}`} /><span className="run-row-copy"><strong>{run.macro?.name || 'Untitled run'}</strong><small>{formatDate(run.created_at)}</small></span><StatusBadge status={run.status} /><span className="arrow">→</span></button> }

export default App
