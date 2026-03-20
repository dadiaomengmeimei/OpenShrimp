import { useState, useRef, useEffect } from 'react'
import { X, Sparkles, Loader2, Terminal, FileCode, CheckCircle, AlertCircle, Code, Wrench, ChevronDown, ChevronUp, Brain, StopCircle, MessageSquare } from 'lucide-react'
import { generateAppStream, AgentEvent, getAppSkills, interruptAgent, injectAgentMessage } from '../services/api'

interface Props {
  onClose: () => void
  onComplete: () => void
  editAppId?: string  // If set, we're editing an existing app
  editAppName?: string
}

interface LogEntry {
  id: number
  type: AgentEvent['type']
  content: string
  detail?: string
  timestamp: Date
}

export default function AgentModal({ onClose, onComplete, editAppId, editAppName }: Props) {
  const [description, setDescription] = useState('')
  const [running, setRunning] = useState(false)
  const [finished, setFinished] = useState(false)
  const [error, setError] = useState('')
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [agentText, setAgentText] = useState('')
  const [filesModified, setFilesModified] = useState<string[]>([])
  const [method, setMethod] = useState('')
  const [showAgentText, setShowAgentText] = useState(false)
  const [skills, setSkills] = useState<string[]>([])
  const [showSkills, setShowSkills] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [supervisionInput, setSupervisionInput] = useState('')
  const logEndRef = useRef<HTMLDivElement>(null)
  const logIdRef = useRef(0)

  // Load existing skills when editing
  useEffect(() => {
    if (editAppId) {
      getAppSkills(editAppId).then(data => {
        if (data.items.length > 0) {
          setSkills(data.items)
        }
      }).catch(() => {})
    }
  }, [editAppId])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  const addLog = (type: AgentEvent['type'], content: string, detail?: string) => {
    logIdRef.current += 1
    setLogs(prev => [...prev, { id: logIdRef.current, type, content, detail, timestamp: new Date() }])
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!description.trim()) return
    setRunning(true)
    setFinished(false)
    setError('')
    setLogs([])
    setAgentText('')
    setFilesModified([])
    setSupervisionInput('')
    setSessionId(null)

    addLog('start', editAppId
      ? `Starting modification of app "${editAppName || editAppId}"...`
      : 'Starting app generation...'
    )

    try {
      await generateAppStream(
        description,
        editAppId,
        undefined,
        (event: AgentEvent) => {
          switch (event.type) {
            case 'start':
              setMethod(event.method || '')
              if (event.session_id) setSessionId(event.session_id)
              addLog('start', `Agent method: ${event.method || 'unknown'}`)
              break
            case 'log':
              addLog('log', event.message || '')
              break
            case 'text_delta':
              setAgentText(prev => prev + (event.delta || ''))
              break
            case 'tool_call':
              addLog('tool_call', `🔧 Tool: ${event.tool}`, JSON.stringify(event.input || {}, null, 2))
              break
            case 'tool_result':
              addLog('tool_result', `✅ ${event.tool} completed`, event.output || '')
              break
            case 'file_modified':
              if (event.path) {
                setFilesModified(prev => prev.includes(event.path!) ? prev : [...prev, event.path!])
                addLog('file_modified', `📝 File: ${event.path}`)
              }
              break
            case 'done':
              setFinished(true)
              setSessionId(null)
              setFilesModified(event.files_modified || [])
              addLog('done', '✨ Generation complete!')
              break
            case 'skills_updated':
              if (event.items) {
                setSkills(event.items)
                addLog('log', `🧠 Skills updated: ${event.count} skills saved`)
              }
              break
            case 'error':
              setError(event.error || 'Unknown error')
              addLog('error', `❌ Error: ${event.error}`)
              break
          }
        }
      )
    } catch (err: any) {
      setError(err.message || 'Generation failed')
      addLog('error', `❌ ${err.message || 'Generation failed'}`)
    } finally {
      setRunning(false)
      setSessionId(null)
    }
  }

  const handleInterrupt = async () => {
    if (!sessionId) return
    try {
      await interruptAgent(sessionId)
      addLog('log', '⛔ Interrupt signal sent...')
    } catch {
      addLog('error', '❌ Failed to send interrupt')
    }
  }

  const handleInjectMessage = async () => {
    if (!sessionId || !supervisionInput.trim()) return
    const msg = supervisionInput.trim()
    setSupervisionInput('')
    try {
      await injectAgentMessage(sessionId, msg)
      addLog('log', `📝 Supervision message queued: ${msg}`)
    } catch {
      addLog('error', '❌ Failed to inject message')
    }
  }

  const examples = editAppId ? [
    'Add a file upload feature that accepts PDF files',
    'Improve the error handling and add input validation',
    'Add a chat history sidebar with session management',
  ] : [
    'A weather dashboard that fetches and displays weather data with charts',
    'A code review assistant that analyzes code snippets and suggests improvements',
    'A meeting summarizer that processes meeting transcripts and extracts action items',
  ]

  const getLogIcon = (type: string) => {
    switch (type) {
      case 'start': return <Sparkles size={14} className="text-purple-400" />
      case 'log': return <Terminal size={14} className="text-slate-400" />
      case 'tool_call': return <Wrench size={14} className="text-amber-400" />
      case 'tool_result': return <CheckCircle size={14} className="text-green-400" />
      case 'file_modified': return <FileCode size={14} className="text-blue-400" />
      case 'done': return <CheckCircle size={14} className="text-emerald-400" />
      case 'error': return <AlertCircle size={14} className="text-red-400" />
      case 'skills_updated': return <Brain size={14} className="text-cyan-400" />
      default: return <Code size={14} className="text-slate-400" />
    }
  }

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-4xl max-h-[90vh] shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-slate-700 shrink-0">
          <div className="flex items-center gap-2">
            <Sparkles size={18} className="text-purple-400" />
            <h2 className="text-lg font-semibold text-white">
              {editAppId ? `Edit App: ${editAppName || editAppId}` : 'AI App Generator'}
            </h2>
            {method && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300 uppercase tracking-wider">
                {method}
              </span>
            )}
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-700 text-slate-400 transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Skills badge (show when skills exist for this app) */}
        {skills.length > 0 && (
          <div className="px-5 py-2 bg-cyan-500/5 border-b border-cyan-500/20">
            <button
              onClick={() => setShowSkills(!showSkills)}
              className="flex items-center gap-2 text-xs text-cyan-400 hover:text-cyan-300 transition-colors w-full"
            >
              <Brain size={14} />
              <span>{skills.length} accumulated skill{skills.length > 1 ? 's' : ''} loaded</span>
              {showSkills ? <ChevronUp size={12} className="ml-auto" /> : <ChevronDown size={12} className="ml-auto" />}
            </button>
            {showSkills && (
              <div className="mt-2 space-y-1">
                {skills.map((skill, i) => (
                  <div key={i} className="text-xs text-cyan-300/70 pl-5 flex items-start gap-1.5">
                    <span className="text-cyan-500 shrink-0">•</span>
                    <span>{skill}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Content area */}
        <div className="flex-1 overflow-hidden flex flex-col min-h-0">
          {/* Input section */}
          <form onSubmit={handleSubmit} className="p-5 space-y-3 border-b border-slate-700/50 shrink-0">
            <div>
              <label className="block text-sm text-slate-400 mb-1.5">
                {editAppId ? 'Describe the changes you want to make' : 'Describe the app you want to create'}
              </label>
              <textarea
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder={editAppId ? "I want to add..." : "I want an app that..."}
                rows={3}
                disabled={running}
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-600 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-purple-500/50 text-sm resize-none disabled:opacity-50"
              />
            </div>

            {!running && !finished && (
              <div>
                <p className="text-xs text-slate-500 mb-2">Try these examples:</p>
                <div className="flex flex-wrap gap-1.5">
                  {examples.map((ex, i) => (
                    <button
                      key={i}
                      type="button"
                      onClick={() => setDescription(ex)}
                      className="text-xs text-slate-400 hover:text-purple-400 px-2.5 py-1 rounded-md hover:bg-slate-700/50 transition-colors border border-slate-700/50"
                    >
                      💡 {ex}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="flex gap-3">
              <button
                type="submit"
                disabled={running || !description.trim()}
                className="flex-1 py-2.5 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 disabled:from-slate-600 disabled:to-slate-600 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-all shadow-lg shadow-purple-500/25 flex items-center justify-center gap-2"
              >
                {running ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    Agent is working...
                  </>
                ) : finished ? (
                  '🔄 Regenerate'
                ) : (
                  <>
                    <Sparkles size={14} />
                    {editAppId ? 'Apply Changes' : 'Generate App'}
                  </>
                )}
              </button>
              {running && sessionId && (
                <button
                  type="button"
                  onClick={handleInterrupt}
                  className="px-4 py-2.5 bg-red-600 hover:bg-red-500 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                  title="Stop the agent"
                >
                  <StopCircle size={14} />
                  Stop
                </button>
              )}
              {finished && (
                <button
                  type="button"
                  onClick={() => { onComplete(); onClose() }}
                  className="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-sm font-medium transition-colors"
                >
                  Done
                </button>
              )}
            </div>

            {/* Supervision message input (shown while agent is running) */}
            {running && sessionId && (
              <div className="flex gap-2 pt-1">
                <input
                  type="text"
                  value={supervisionInput}
                  onChange={e => setSupervisionInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleInjectMessage() } }}
                  placeholder="Send supervision message to guide the agent..."
                  className="flex-1 px-3 py-2 bg-slate-800/50 border border-slate-600 rounded-lg text-white text-sm placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-purple-500/50"
                />
                <button
                  type="button"
                  onClick={handleInjectMessage}
                  disabled={!supervisionInput.trim()}
                  className="px-3 py-2 bg-purple-600 hover:bg-purple-500 disabled:bg-slate-700 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors flex items-center gap-1.5"
                >
                  <MessageSquare size={14} />
                  Send
                </button>
              </div>
            )}
          </form>

          {/* Execution log */}
          {logs.length > 0 && (
            <div className="flex-1 overflow-hidden flex flex-col min-h-0">
              {/* Log header */}
              <div className="flex items-center justify-between px-5 py-2 bg-slate-800/50 border-b border-slate-700/50 shrink-0">
                <div className="flex items-center gap-2 text-xs text-slate-400">
                  <Terminal size={12} />
                  <span>Execution Log</span>
                  <span className="text-slate-500">({logs.length} events)</span>
                </div>
                <div className="flex items-center gap-2">
                  {filesModified.length > 0 && (
                    <span className="text-xs text-blue-400">
                      📁 {filesModified.length} file{filesModified.length > 1 ? 's' : ''} modified
                    </span>
                  )}
                </div>
              </div>

              {/* Log entries */}
              <div className="flex-1 overflow-y-auto p-3 space-y-1 font-mono text-xs">
                {logs.map(log => (
                  <div key={log.id} className="flex items-start gap-2 py-1 px-2 rounded hover:bg-slate-800/30">
                    <span className="shrink-0 mt-0.5">{getLogIcon(log.type)}</span>
                    <div className="min-w-0 flex-1">
                      <span className={`${
                        log.type === 'error' ? 'text-red-400' :
                        log.type === 'done' ? 'text-emerald-400' :
                        log.type === 'file_modified' ? 'text-blue-400' :
                        log.type === 'tool_call' ? 'text-amber-400' :
                        log.type === 'tool_result' ? 'text-green-400' :
                        'text-slate-300'
                      }`}>
                        {log.content}
                      </span>
                      {log.detail && (
                        <pre className="mt-1 text-slate-500 whitespace-pre-wrap break-all max-h-24 overflow-y-auto bg-slate-900/50 p-1.5 rounded">
                          {log.detail.substring(0, 500)}
                        </pre>
                      )}
                    </div>
                    <span className="text-slate-600 shrink-0 text-[10px]">
                      {log.timestamp.toLocaleTimeString()}
                    </span>
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>

              {/* Agent thinking text (collapsible) */}
              {agentText && (
                <div className="border-t border-slate-700/50 shrink-0">
                  <button
                    onClick={() => setShowAgentText(!showAgentText)}
                    className="w-full flex items-center justify-between px-5 py-2 text-xs text-slate-400 hover:bg-slate-800/30 transition-colors"
                  >
                    <span>Agent Reasoning</span>
                    {showAgentText ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
                  </button>
                  {showAgentText && (
                    <div className="px-5 pb-3 max-h-40 overflow-y-auto">
                      <pre className="text-xs text-slate-500 whitespace-pre-wrap">{agentText}</pre>
                    </div>
                  )}
                </div>
              )}

              {/* Files modified summary */}
              {filesModified.length > 0 && (
                <div className="border-t border-slate-700/50 px-5 py-3 shrink-0">
                  <p className="text-xs text-slate-400 mb-2">Files modified:</p>
                  <div className="flex flex-wrap gap-1.5">
                    {filesModified.map((f, i) => (
                      <span key={i} className="text-[10px] px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                        {f.split('/').slice(-2).join('/')}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Error display */}
          {error && !logs.some(l => l.type === 'error') && (
            <div className="mx-5 mb-3 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400">
              ❌ {error}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
