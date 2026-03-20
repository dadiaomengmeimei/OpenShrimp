import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, Wrench, Terminal, CheckCircle, AlertCircle, FileCode, ChevronDown, ChevronUp, RotateCcw, StopCircle, MessageSquare, ThumbsDown } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import api, { autoFixAppStream, AgentEvent, interruptAgent, injectAgentMessage } from '../services/api'

interface Props {
  appId: string
  appName: string
}

interface FixLogEntry {
  id: number
  type: AgentEvent['type']
  content: string
  detail?: string
}

export default function GenericApp({ appId, appName }: Props) {
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<Array<{ role: string; content: string; rawData?: any }>>([])
  const [loading, setLoading] = useState(false)

  // Auto-fix state
  const [errorInfo, setErrorInfo] = useState<{
    message: string
    error_type: string
    traceback: string
    user_input: string
  } | null>(null)
  const [fixing, setFixing] = useState(false)
  const [fixLogs, setFixLogs] = useState<FixLogEntry[]>([])
  const [fixDone, setFixDone] = useState(false)
  const [showFixPanel, setShowFixPanel] = useState(false)
  const [showFixLogs, setShowFixLogs] = useState(true)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [supervisionInput, setSupervisionInput] = useState('')
  // Behavior fix state
  const [behaviorFixTarget, setBehaviorFixTarget] = useState<{
    userInput: string
    actualOutput: string
    messageIndex: number
  } | null>(null)
  const [expectedBehavior, setExpectedBehavior] = useState('')
  const [showBehaviorDialog, setShowBehaviorDialog] = useState(false)
  const fixLogEndRef = useRef<HTMLDivElement>(null)
  const fixLogIdRef = useRef(0)
  const retryPendingRef = useRef(false)

  useEffect(() => {
    fixLogEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [fixLogs])

  // Auto-send when retryPendingRef is set (after state updates from handleRetry)
  useEffect(() => {
    if (retryPendingRef.current && question.trim()) {
      retryPendingRef.current = false
      handleSend()
    }
  }, [question])

  const addFixLog = (type: AgentEvent['type'], content: string, detail?: string) => {
    fixLogIdRef.current += 1
    setFixLogs(prev => [...prev, { id: fixLogIdRef.current, type, content, detail }])
  }

  const handleSend = async () => {
    if (!question.trim()) return
    const q = question.trim()
    setQuestion('')
    const newMessages = [...messages, { role: 'user', content: q }]
    setMessages(newMessages)
    setLoading(true)
    // Clear previous error and all fix state when sending new message
    setErrorInfo(null)
    setShowFixPanel(false)
    setFixDone(false)
    setFixing(false)
    setFixLogs([])
    try {
      const { data } = await api.post(`/apps/${appId}/chat`, {
        messages: newMessages,
      })
      // Defensive: ensure reply is always a string (backend might return object)
      let reply = data.reply
      if (typeof reply === 'object' && reply !== null) {
        reply = reply.content || reply.text || reply.reply || JSON.stringify(reply)
      }
      reply = String(reply ?? '')
      // Preserve raw structured data from backend for behavior-fix context
      const rawData = data.raw || undefined
      setMessages(prev => [...prev, { role: 'assistant', content: reply, rawData }])
    } catch (err: any) {
      const detail = err.response?.data?.detail
      // Check if it's a structured auto-fixable error
      if (detail && typeof detail === 'object' && detail.auto_fixable) {
        const errData = {
          message: detail.message || err.message,
          error_type: detail.error_type || '',
          traceback: detail.traceback || '',
          user_input: q,
        }
        // Reset all fix state for the new error
        setFixDone(false)
        setFixing(false)
        setFixLogs([])
        setErrorInfo(errData)
        setShowFixPanel(true)
        setMessages(prev => [
          ...prev,
          {
            role: 'assistant',
            content: `⚠️ **Runtime Error**: ${errData.message}\n\n_This error can be auto-fixed. Click the "Auto Fix" button below._`,
          },
        ])
      } else {
        const errMsg = (typeof detail === 'string' ? detail : detail?.message) || err.message
        setMessages(prev => [
          ...prev,
          { role: 'assistant', content: `Error: ${errMsg}` },
        ])
      }
    } finally {
      setLoading(false)
    }
  }

  const handleAutoFix = async () => {
    if (!errorInfo) return
    setFixing(true)
    setFixDone(false)
    setFixLogs([])
    setShowFixLogs(true)
    setSessionId(null)
    setSupervisionInput('')

    addFixLog('start', `🔧 Starting auto-fix for "${appId}"...`)
    addFixLog('log', `Error: ${errorInfo.message}`)

    try {
      await autoFixAppStream(
        {
          app_id: appId,
          error_message: errorInfo.message,
          error_type: errorInfo.error_type,
          traceback: errorInfo.traceback,
          user_input: errorInfo.user_input,
          phase: 'runtime',
        },
        (event: AgentEvent) => {
          switch (event.type) {
            case 'start':
              if (event.session_id) setSessionId(event.session_id)
              addFixLog('start', `Agent method: ${event.method || 'auto-fix'}`)
              break
            case 'log':
              addFixLog('log', event.message || '')
              break
            case 'tool_call':
              addFixLog('tool_call', `🔧 ${event.tool}`, JSON.stringify(event.input || {}, null, 2))
              break
            case 'tool_result':
              addFixLog('tool_result', `✅ ${event.tool} done`, event.output || '')
              break
            case 'file_modified':
              addFixLog('file_modified', `📝 Fixed: ${event.path}`)
              break
            case 'done':
              setFixDone(true)
              setSessionId(null)
              addFixLog('done', '✨ Auto-fix complete! Please retry your message.')
              break
            case 'error':
              addFixLog('error', `❌ ${event.error}`)
              break
            case 'skills_updated':
              addFixLog('log', `🧠 Debugging insights saved: ${event.count} skills`)
              break
            case 'text_delta':
              // Skip streaming text in compact view
              break
          }
        },
      )
    } catch (err: any) {
      addFixLog('error', `❌ Auto-fix failed: ${err.message}`)
    } finally {
      setFixing(false)
      setSessionId(null)
    }
  }

  const handleInterrupt = async () => {
    if (!sessionId) return
    try {
      await interruptAgent(sessionId)
      addFixLog('log', '⛔ Interrupt signal sent...')
    } catch {
      addFixLog('error', '❌ Failed to send interrupt')
    }
  }

  const handleInjectMessage = async () => {
    if (!sessionId || !supervisionInput.trim()) return
    const msg = supervisionInput.trim()
    setSupervisionInput('')
    try {
      await injectAgentMessage(sessionId, msg)
      addFixLog('log', `📝 Supervision message queued: ${msg}`)
    } catch {
      addFixLog('error', '❌ Failed to inject message')
    }
  }

  // Start behavior fix (output not as expected, no crash)
  const handleBehaviorFixStart = (msgIndex: number) => {
    // Find the user input that preceded this assistant message
    let userInput = ''
    for (let i = msgIndex - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        userInput = messages[i].content
        break
      }
    }
    // Include raw structured data if available for richer context in behavior fix
    const msg = messages[msgIndex]
    const actualOutput = msg.rawData
      ? `${msg.content}\n\n--- Raw Structured Data ---\n${JSON.stringify(msg.rawData, null, 2)}`
      : msg.content
    setBehaviorFixTarget({
      userInput,
      actualOutput,
      messageIndex: msgIndex,
    })
    setExpectedBehavior('')
    setShowBehaviorDialog(true)
  }

  const handleBehaviorFixSubmit = async () => {
    if (!behaviorFixTarget || !expectedBehavior.trim()) return
    setShowBehaviorDialog(false)

    // Set up the fix panel
    setFixing(true)
    setFixDone(false)
    setFixLogs([])
    setShowFixPanel(true)
    setShowFixLogs(true)
    setSessionId(null)
    setSupervisionInput('')
    setErrorInfo(null)

    addFixLog('start', `🔧 Starting behavior fix for "${appId}"...`)
    addFixLog('log', `User input: ${behaviorFixTarget.userInput.substring(0, 100)}`)
    addFixLog('log', `Actual output: ${behaviorFixTarget.actualOutput.substring(0, 100)}`)
    addFixLog('log', `Expected: ${expectedBehavior.substring(0, 100)}`)

    try {
      await autoFixAppStream(
        {
          app_id: appId,
          error_message: `Output not as expected. User expected: ${expectedBehavior}`,
          mode: 'behavior',
          user_input: behaviorFixTarget.userInput,
          actual_output: behaviorFixTarget.actualOutput,
          expected_behavior: expectedBehavior,
          conversation_history: messages,
          phase: 'runtime',
        },
        (event: AgentEvent) => {
          switch (event.type) {
            case 'start':
              if (event.session_id) setSessionId(event.session_id)
              addFixLog('start', `Agent method: ${event.method || 'auto-fix'} (behavior mode)`)
              break
            case 'log':
              addFixLog('log', event.message || '')
              break
            case 'tool_call':
              addFixLog('tool_call', `🔧 ${event.tool}`, JSON.stringify(event.input || {}, null, 2))
              break
            case 'tool_result':
              addFixLog('tool_result', `✅ ${event.tool} done`, event.output || '')
              break
            case 'file_modified':
              addFixLog('file_modified', `📝 Fixed: ${event.path}`)
              break
            case 'done':
              setFixDone(true)
              setSessionId(null)
              addFixLog('done', '✨ Behavior fix complete! Please retry your message.')
              break
            case 'error':
              addFixLog('error', `❌ ${event.error}`)
              break
            case 'skills_updated':
              addFixLog('log', `🧠 Insights saved: ${event.count} skills`)
              break
            case 'text_delta':
              break
          }
        },
      )
    } catch (err: any) {
      addFixLog('error', `❌ Behavior fix failed: ${err.message}`)
    } finally {
      setFixing(false)
      setSessionId(null)
      setBehaviorFixTarget(null)
    }
  }

  const handleRetry = async () => {
    // Find the last user message to retry (works for both error-fix and behavior-fix)
    const lastUserMsg = errorInfo?.user_input
      || [...messages].reverse().find(m => m.role === 'user')?.content
    if (!lastUserMsg) return

    setShowFixPanel(false)
    setErrorInfo(null)
    // Remove the error message and retry
    const filtered = messages.filter(
      m => !m.content.includes('⚠️ **Runtime Error**')
    )
    setMessages(filtered)
    setQuestion(lastUserMsg)
    // Use a ref-stable flag to trigger send on next render
    retryPendingRef.current = true
  }

  const getLogIcon = (type: string) => {
    switch (type) {
      case 'start': return <Wrench size={12} className="text-purple-400" />
      case 'log': return <Terminal size={12} className="text-slate-400" />
      case 'tool_call': return <Wrench size={12} className="text-amber-400" />
      case 'tool_result': return <CheckCircle size={12} className="text-green-400" />
      case 'file_modified': return <FileCode size={12} className="text-blue-400" />
      case 'done': return <CheckCircle size={12} className="text-emerald-400" />
      case 'error': return <AlertCircle size={12} className="text-red-400" />
      default: return <Terminal size={12} className="text-slate-400" />
    }
  }

  return (
    <div className="flex gap-4" style={{ minHeight: '500px' }}>
      {/* Main chat area */}
      <div className={`bg-slate-800/50 border border-slate-700/50 rounded-xl flex flex-col flex-1 transition-all ${showFixPanel ? 'max-w-[55%]' : ''}`}>
        <div className="p-4 border-b border-slate-700/50">
          <h3 className="text-sm font-semibold text-white">💬 Chat with {appName}</h3>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.length === 0 && (
            <p className="text-slate-500 text-sm text-center py-8">Start a conversation...</p>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className="group relative max-w-[85%]">
                <div
                  className={`p-3 rounded-xl text-sm ${
                    msg.role === 'user' ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-200'
                  }`}
                >
                  {msg.role === 'assistant' ? (
                    <ReactMarkdown className="prose prose-invert prose-sm max-w-none">{msg.content}</ReactMarkdown>
                  ) : (
                    msg.content
                  )}
                </div>
                {/* "Not as expected" button for assistant messages (non-error) */}
                {msg.role === 'assistant' && !msg.content.includes('⚠️ **Runtime Error**') && !msg.content.startsWith('Error:') && (
                  <button
                    onClick={() => handleBehaviorFixStart(i)}
                    className="absolute -bottom-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity px-2 py-0.5 bg-slate-600 hover:bg-amber-600 text-slate-300 hover:text-white text-[10px] rounded-full flex items-center gap-1 shadow-lg"
                    title="Report: output not as expected"
                  >
                    <ThumbsDown size={10} />
                    Not as expected
                  </button>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-slate-700 p-3 rounded-xl">
                <Loader2 size={16} className="animate-spin text-slate-400" />
              </div>
            </div>
          )}
        </div>

        {/* Auto-fix action bar (inline, when error detected) */}
        {errorInfo && !showFixPanel && (
          <div className="px-4 py-2 bg-amber-500/10 border-t border-amber-500/20 flex items-center gap-3">
            <AlertCircle size={14} className="text-amber-400 shrink-0" />
            <span className="text-xs text-amber-300 flex-1 truncate">Runtime error detected</span>
            <button
              onClick={() => setShowFixPanel(true)}
              className="px-3 py-1 bg-amber-600 hover:bg-amber-500 text-white text-xs rounded-md transition-colors flex items-center gap-1"
            >
              <Wrench size={12} />
              Auto Fix
            </button>
          </div>
        )}

        <div className="p-3 border-t border-slate-700/50 flex gap-2">
          <input
            type="text"
            value={question}
            onChange={e => setQuestion(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSend()}
            placeholder="Type a message..."
            className="flex-1 px-3 py-2 bg-slate-900/50 border border-slate-600 rounded-lg text-white text-sm placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
          />
          <button
            onClick={handleSend}
            disabled={loading || !question.trim()}
            className="p-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-600 text-white rounded-lg transition-colors"
          >
            <Send size={16} />
          </button>
        </div>
      </div>

      {/* Auto-fix side panel */}
      {showFixPanel && (
        <div className="w-[45%] bg-slate-900/80 border border-amber-500/30 rounded-xl flex flex-col overflow-hidden">
          {/* Panel header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-amber-500/20 bg-amber-500/5">
            <div className="flex items-center gap-2">
              <Wrench size={16} className="text-amber-400" />
              <h3 className="text-sm font-semibold text-amber-300">Auto-Fix Agent</h3>
              {fixing && (
                <Loader2 size={14} className="animate-spin text-amber-400" />
              )}
            </div>
            <button
              onClick={() => setShowFixPanel(false)}
              className="text-slate-500 hover:text-slate-300 text-xs"
            >
              Close
            </button>
          </div>

          {/* Error summary */}
          <div className="px-4 py-3 bg-red-500/5 border-b border-red-500/10">
            <p className="text-xs text-red-400 font-mono break-all">
              {errorInfo?.error_type && <span className="text-red-500 font-semibold">{errorInfo.error_type}: </span>}
              {errorInfo?.message}
            </p>
          </div>

          <div className="px-4 py-3 border-b border-slate-700/50 flex flex-col gap-2">
            {/* Main action row */}
            <div className="flex gap-2">
              {!fixDone ? (
                <>
                  <button
                    onClick={handleAutoFix}
                    disabled={fixing}
                    className="flex-1 py-2 bg-amber-600 hover:bg-amber-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors flex items-center justify-center gap-2"
                  >
                    {fixing ? (
                      <>
                        <Loader2 size={14} className="animate-spin" />
                        Fixing...
                      </>
                    ) : (
                      <>
                        <Wrench size={14} />
                        Start Auto-Fix
                      </>
                    )}
                  </button>
                  {fixing && sessionId && (
                    <button
                      onClick={handleInterrupt}
                      className="px-3 py-2 bg-red-600 hover:bg-red-500 text-white text-sm rounded-lg transition-colors flex items-center gap-1.5"
                      title="Interrupt agent"
                    >
                      <StopCircle size={14} />
                      Stop
                    </button>
                  )}
                </>
              ) : (
                <button
                  onClick={handleRetry}
                  className="flex-1 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-lg transition-colors flex items-center justify-center gap-2"
                >
                  <RotateCcw size={14} />
                  Retry Message
                </button>
              )}
            </div>

            {/* Supervision message input (shown while fixing) */}
            {fixing && sessionId && (
              <div className="flex gap-1.5">
                <input
                  type="text"
                  value={supervisionInput}
                  onChange={e => setSupervisionInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleInjectMessage()}
                  placeholder="Send supervision message to agent..."
                  className="flex-1 px-2.5 py-1.5 bg-slate-800/50 border border-slate-600 rounded-md text-white text-xs placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-amber-500/50"
                />
                <button
                  onClick={handleInjectMessage}
                  disabled={!supervisionInput.trim()}
                  className="px-2.5 py-1.5 bg-amber-700 hover:bg-amber-600 disabled:bg-slate-700 disabled:cursor-not-allowed text-white text-xs rounded-md transition-colors flex items-center gap-1"
                >
                  <MessageSquare size={12} />
                  Send
                </button>
              </div>
            )}
          </div>

          {/* Fix execution log */}
          {fixLogs.length > 0 && (
            <div className="flex-1 overflow-hidden flex flex-col min-h-0">
              <button
                onClick={() => setShowFixLogs(!showFixLogs)}
                className="flex items-center justify-between px-4 py-2 bg-slate-800/50 border-b border-slate-700/50 text-xs text-slate-400 hover:bg-slate-800/80"
              >
                <span className="flex items-center gap-1.5">
                  <Terminal size={12} />
                  Fix Log ({fixLogs.length} events)
                </span>
                {showFixLogs ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              </button>

              {showFixLogs && (
                <div className="flex-1 overflow-y-auto p-2 space-y-0.5 font-mono text-[11px]">
                  {fixLogs.map(log => (
                    <div key={log.id} className="flex items-start gap-1.5 py-0.5 px-1.5 rounded hover:bg-slate-800/30">
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
                          <pre className="mt-0.5 text-slate-500 whitespace-pre-wrap break-all max-h-16 overflow-y-auto bg-slate-900/50 p-1 rounded text-[10px]">
                            {log.detail.substring(0, 300)}
                          </pre>
                        )}
                      </div>
                    </div>
                  ))}
                  <div ref={fixLogEndRef} />
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {/* Behavior fix dialog */}
      {showBehaviorDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-slate-800 border border-slate-600 rounded-2xl w-[500px] max-w-[90vw] shadow-2xl">
            <div className="px-5 py-4 border-b border-slate-700 flex items-center gap-2">
              <ThumbsDown size={16} className="text-amber-400" />
              <h3 className="text-sm font-semibold text-white">Report Unexpected Output</h3>
            </div>
            <div className="px-5 py-4 space-y-3">
              {behaviorFixTarget && (
                <>
                  <div>
                    <label className="text-xs text-slate-400 font-medium">Your input:</label>
                    <p className="text-xs text-slate-300 mt-1 bg-slate-900/50 p-2 rounded-lg max-h-16 overflow-y-auto">
                      {behaviorFixTarget.userInput.substring(0, 200)}
                    </p>
                  </div>
                  <div>
                    <label className="text-xs text-slate-400 font-medium">App's response (actual):</label>
                    <p className="text-xs text-slate-300 mt-1 bg-slate-900/50 p-2 rounded-lg max-h-20 overflow-y-auto">
                      {behaviorFixTarget.actualOutput.substring(0, 300)}
                    </p>
                  </div>
                </>
              )}
              <div>
                <label className="text-xs text-slate-400 font-medium">What did you expect? <span className="text-amber-400">*</span></label>
                <textarea
                  value={expectedBehavior}
                  onChange={e => setExpectedBehavior(e.target.value)}
                  placeholder="Describe what the correct output should look like, or what behavior you expected..."
                  className="w-full mt-1 px-3 py-2 bg-slate-900/50 border border-slate-600 rounded-lg text-white text-sm placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/50 resize-none"
                  rows={3}
                  autoFocus
                />
              </div>
            </div>
            <div className="px-5 py-3 border-t border-slate-700 flex justify-end gap-2">
              <button
                onClick={() => { setShowBehaviorDialog(false); setBehaviorFixTarget(null) }}
                className="px-4 py-2 text-slate-400 hover:text-white text-sm transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleBehaviorFixSubmit}
                disabled={!expectedBehavior.trim()}
                className="px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors flex items-center gap-1.5"
              >
                <Wrench size={14} />
                Start Behavior Fix
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
