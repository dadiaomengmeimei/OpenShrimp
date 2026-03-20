import { useState, useCallback, useRef, useEffect } from 'react'
import { useDropzone } from 'react-dropzone'
import {
  Upload, Send, BarChart3, Loader2, Download, ChevronDown,
  PieChart, TrendingUp, Activity, CircleDot, Grid3X3, X, Check, Settings2
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import {
  uploadExcel, analyzeExcel, generateChart, generatePresetChart,
  getChartHistory, getChartById, exportChartUrl, suggestCharts,
  UploadResult
} from '../services/api'

interface ChartHistoryItem {
  id: string
  instruction: string
  chart_type: string
  timestamp: number
}

interface ChartSuggestion {
  chart_type: string
  label: string
  description: string
  x_column: string | null
  y_column: string | null
}

// Column selection configuration per chart type
interface ColumnPickerConfig {
  chartType: string
  needsX: boolean       // Does this chart need an X-axis column?
  needsY: boolean       // Does this chart need a Y-axis column?
  needsMultiY: boolean  // Does this chart allow multiple Y-axis columns? (radar / heatmap)
  xLabel: string
  yLabel: string
  xFilter: 'all' | 'numeric' | 'categorical'
  yFilter: 'all' | 'numeric' | 'categorical'
}

const CHART_COLUMN_CONFIG: Record<string, ColumnPickerConfig> = {
  bar:     { chartType: 'bar',     needsX: true,  needsY: true,  needsMultiY: false, xLabel: 'Category (X-axis)', yLabel: 'Value (Y-axis)',    xFilter: 'all',         yFilter: 'numeric' },
  line:    { chartType: 'line',    needsX: true,  needsY: true,  needsMultiY: false, xLabel: 'X-axis',           yLabel: 'Value (Y-axis)',    xFilter: 'all',         yFilter: 'numeric' },
  pie:     { chartType: 'pie',     needsX: true,  needsY: true,  needsMultiY: false, xLabel: 'Category',         yLabel: 'Value',             xFilter: 'categorical', yFilter: 'numeric' },
  radar:   { chartType: 'radar',   needsX: false, needsY: false, needsMultiY: true,  xLabel: '',                 yLabel: 'Metrics (numeric)', xFilter: 'all',         yFilter: 'numeric' },
  scatter: { chartType: 'scatter', needsX: true,  needsY: true,  needsMultiY: false, xLabel: 'X-axis (numeric)', yLabel: 'Y-axis (numeric)',  xFilter: 'numeric',     yFilter: 'numeric' },
  heatmap: { chartType: 'heatmap', needsX: false, needsY: false, needsMultiY: true,  xLabel: '',                 yLabel: 'Columns (numeric)', xFilter: 'all',         yFilter: 'numeric' },
}

const CHART_TYPE_ICONS: Record<string, React.ReactNode> = {
  bar: <BarChart3 size={14} />,
  line: <TrendingUp size={14} />,
  pie: <PieChart size={14} />,
  radar: <Activity size={14} />,
  scatter: <CircleDot size={14} />,
  heatmap: <Grid3X3 size={14} />,
}

const CHART_TYPE_LABELS: Record<string, string> = {
  bar: 'Bar',
  line: 'Line',
  pie: 'Pie',
  radar: 'Radar',
  scatter: 'Scatter',
  heatmap: 'Heatmap',
}

const CHART_TYPE_COLORS: Record<string, string> = {
  bar: 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30 hover:bg-indigo-500/30',
  line: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/30',
  pie: 'bg-pink-500/20 text-pink-400 border-pink-500/30 hover:bg-pink-500/30',
  radar: 'bg-amber-500/20 text-amber-400 border-amber-500/30 hover:bg-amber-500/30',
  scatter: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30 hover:bg-cyan-500/30',
  heatmap: 'bg-red-500/20 text-red-400 border-red-500/30 hover:bg-red-500/30',
}

// ────────────────────────────────────────
// Column Picker Component
// ────────────────────────────────────────
function ColumnPicker({
  config,
  allColumns,
  numericColumns,
  categoricalColumns,
  onConfirm,
  onCancel,
}: {
  config: ColumnPickerConfig
  allColumns: string[]
  numericColumns: string[]
  categoricalColumns: string[]
  onConfirm: (xCol: string | undefined, yCol: string | undefined, multiCols?: string[]) => void
  onCancel: () => void
}) {
  const getFilteredCols = (filter: 'all' | 'numeric' | 'categorical') => {
    if (filter === 'numeric') return numericColumns
    if (filter === 'categorical') return categoricalColumns
    return allColumns
  }

  const xOptions = getFilteredCols(config.xFilter)
  const yOptions = getFilteredCols(config.yFilter)

  // Smart default: pick first available column
  const [xCol, setXCol] = useState<string>(
    config.needsX ? (xOptions[0] || '') : ''
  )
  const [yCol, setYCol] = useState<string>(
    config.needsY ? (yOptions.find(c => c !== xOptions[0]) || yOptions[0] || '') : ''
  )
  // Multi-select for radar / heatmap: default to first 5 numeric cols
  const [multiCols, setMultiCols] = useState<string[]>(
    config.needsMultiY ? numericColumns.slice(0, Math.min(6, numericColumns.length)) : []
  )
  const [title, setTitle] = useState('')

  const toggleMultiCol = (col: string) => {
    setMultiCols(prev =>
      prev.includes(col) ? prev.filter(c => c !== col) : [...prev, col]
    )
  }

  const canConfirm = config.needsMultiY
    ? multiCols.length >= 2
    : (!config.needsX || xCol) && (!config.needsY || yCol)

  return (
    <div className="absolute inset-0 z-50 bg-slate-900/80 backdrop-blur-sm flex items-center justify-center rounded-xl">
      <div className="bg-slate-800 border border-slate-600 rounded-xl p-5 w-80 max-h-[90%] overflow-y-auto shadow-2xl">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            {CHART_TYPE_ICONS[config.chartType]}
            <h4 className="text-white font-semibold text-sm">
              {CHART_TYPE_LABELS[config.chartType]} Chart — Select Columns
            </h4>
          </div>
          <button onClick={onCancel} className="text-slate-400 hover:text-white">
            <X size={16} />
          </button>
        </div>

        {/* Single X / Y selection */}
        {config.needsX && (
          <div className="mb-3">
            <label className="block text-xs text-slate-400 mb-1.5">{config.xLabel}</label>
            <select
              value={xCol}
              onChange={e => setXCol(e.target.value)}
              className="w-full px-3 py-2 bg-slate-900/60 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
            >
              <option value="">-- Select column --</option>
              {xOptions.map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
        )}

        {config.needsY && (
          <div className="mb-3">
            <label className="block text-xs text-slate-400 mb-1.5">{config.yLabel}</label>
            <select
              value={yCol}
              onChange={e => setYCol(e.target.value)}
              className="w-full px-3 py-2 bg-slate-900/60 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
            >
              <option value="">-- Select column --</option>
              {yOptions.map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
        )}

        {/* Multi-select for radar / heatmap */}
        {config.needsMultiY && (
          <div className="mb-3">
            <label className="block text-xs text-slate-400 mb-1.5">
              {config.yLabel} <span className="text-slate-500">(select ≥2, selected: {multiCols.length})</span>
            </label>
            <div className="max-h-40 overflow-y-auto space-y-1 border border-slate-700 rounded-lg p-2 bg-slate-900/40">
              {yOptions.map(c => (
                <label
                  key={c}
                  className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer text-sm transition-colors ${
                    multiCols.includes(c)
                      ? 'bg-indigo-500/20 text-indigo-300'
                      : 'text-slate-300 hover:bg-slate-700/50'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={multiCols.includes(c)}
                    onChange={() => toggleMultiCol(c)}
                    className="rounded border-slate-500 bg-slate-700 text-indigo-500 focus:ring-indigo-500/50"
                  />
                  {c}
                </label>
              ))}
            </div>
          </div>
        )}

        {/* Optional title */}
        <div className="mb-4">
          <label className="block text-xs text-slate-400 mb-1.5">Chart title (optional)</label>
          <input
            type="text"
            value={title}
            onChange={e => setTitle(e.target.value)}
            placeholder="Auto-generated if empty"
            className="w-full px-3 py-2 bg-slate-900/60 border border-slate-600 rounded-lg text-white text-sm placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
          />
        </div>

        {/* Action buttons */}
        <div className="flex gap-2">
          <button
            onClick={onCancel}
            className="flex-1 px-3 py-2 text-sm bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(
              config.needsX ? xCol || undefined : undefined,
              config.needsY ? yCol || undefined : undefined,
              config.needsMultiY ? multiCols : undefined,
            )}
            disabled={!canConfirm}
            className="flex-1 flex items-center justify-center gap-1 px-3 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-600 disabled:text-slate-400 text-white rounded-lg transition-colors"
          >
            <Check size={14} />
            Generate
          </button>
        </div>
      </div>
    </div>
  )
}


// ────────────────────────────────────────
// Main Component
// ────────────────────────────────────────
export default function ExcelAnalyzer() {
  const [session, setSession] = useState<(UploadResult & {
    numeric_columns?: string[]; categorical_columns?: string[]; datetime_columns?: string[]
  }) | null>(null)
  const [uploading, setUploading] = useState(false)
  const [question, setQuestion] = useState('')
  const [chartInstruction, setChartInstruction] = useState('')
  const [messages, setMessages] = useState<Array<{ role: string; content: string }>>([])
  const [chart, setChart] = useState<{ image: string; code: string; chart_id?: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const [chartLoading, setChartLoading] = useState(false)

  // Chart history
  const [chartHistory, setChartHistory] = useState<ChartHistoryItem[]>([])
  const [showHistory, setShowHistory] = useState(false)
  const historyRef = useRef<HTMLDivElement>(null)

  // Chart suggestions
  const [suggestions, setSuggestions] = useState<ChartSuggestion[]>([])

  // Column Picker
  const [pickerConfig, setPickerConfig] = useState<ColumnPickerConfig | null>(null)

  // Close history dropdown on outside click
  useEffect(() => {
    const handle = (e: MouseEvent) => {
      if (historyRef.current && !historyRef.current.contains(e.target as Node)) {
        setShowHistory(false)
      }
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [])

  const refreshHistory = async () => {
    if (!session) return
    try {
      const data = await getChartHistory(session.session_id)
      setChartHistory(data)
    } catch { /* ignore */ }
  }

  const loadSuggestions = async (sessionId: string) => {
    try {
      const { suggestions: s } = await suggestCharts(sessionId)
      setSuggestions(s)
    } catch { /* ignore */ }
  }

  const onDrop = useCallback(async (files: File[]) => {
    if (files.length === 0) return
    setUploading(true)
    try {
      const result = await uploadExcel(files[0])
      setSession(result)
      setMessages([])
      setChart(null)
      setChartHistory([])
      setSuggestions([])
      setPickerConfig(null)
      loadSuggestions(result.session_id)
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls'],
      'text/csv': ['.csv'],
    },
    maxFiles: 1,
  })

  const handleAsk = async () => {
    if (!session || !question.trim()) return
    const q = question.trim()
    setQuestion('')
    const newMessages = [...messages, { role: 'user', content: q }]
    setMessages(newMessages)
    setLoading(true)
    try {
      // Pass chat history (exclude the current question, it's sent separately)
      const history = messages.map(m => ({ role: m.role, content: m.content }))
      const { answer } = await analyzeExcel(session.session_id, q, history)
      setMessages(prev => [...prev, { role: 'assistant', content: answer }])
    } catch (err: any) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${err.response?.data?.detail || err.message}` }])
    } finally {
      setLoading(false)
    }
  }

  // AI-driven dynamic chart generation
  const handleChart = async () => {
    if (!session || !chartInstruction.trim()) return
    setChartLoading(true)
    try {
      const result = await generateChart(session.session_id, chartInstruction)
      setChart(result)
      setChartInstruction('')
      refreshHistory()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Chart generation failed')
    } finally {
      setChartLoading(false)
    }
  }

  // Open column picker for a chart type
  const openColumnPicker = (chartType: string) => {
    const config = CHART_COLUMN_CONFIG[chartType]
    if (config) {
      setPickerConfig(config)
    }
  }

  // Preset chart generation (called after column picker confirms)
  const handlePresetChart = async (xCol?: string, yCol?: string, multiCols?: string[]) => {
    if (!session || !pickerConfig) return
    setPickerConfig(null)
    setChartLoading(true)
    try {
      const result = await generatePresetChart(
        session.session_id,
        pickerConfig.chartType,
        xCol,
        yCol,
        undefined, // title auto-generated
        multiCols, // multi-select columns for radar/heatmap
      )
      setChart(result)
      refreshHistory()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Chart generation failed')
    } finally {
      setChartLoading(false)
    }
  }

  // Quick chart from suggestions (also opens picker but pre-filled)
  const handleSuggestionClick = (s: ChartSuggestion) => {
    // Open picker with the suggestion's chart type; the picker will auto-select the suggested columns
    openColumnPicker(s.chart_type)
  }

  // Load chart from history
  const handleLoadHistory = async (chartId: string) => {
    if (!session) return
    setChartLoading(true)
    setShowHistory(false)
    try {
      const data = await getChartById(session.session_id, chartId)
      setChart({ image: data.image, code: data.code, chart_id: data.id })
    } catch {
      alert('Failed to load chart')
    } finally {
      setChartLoading(false)
    }
  }

  // Export current chart
  const handleExport = () => {
    if (!session || !chart?.chart_id) return
    const url = exportChartUrl(session.session_id, chart.chart_id)
    const a = document.createElement('a')
    a.href = url
    a.download = `chart_${chart.chart_id}.png`
    a.click()
  }

  const formatTime = (ts: number) => {
    const d = new Date(ts * 1000)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }

  return (
    <div className="space-y-6">
      {/* Upload Area */}
      {!session ? (
        <div
          {...getRootProps()}
          className={`border-2 border-dashed rounded-2xl p-12 text-center cursor-pointer transition-all ${
            isDragActive
              ? 'border-indigo-500 bg-indigo-500/10'
              : 'border-slate-600 hover:border-slate-500 bg-slate-800/30'
          }`}
        >
          <input {...getInputProps()} />
          {uploading ? (
            <Loader2 size={40} className="mx-auto text-indigo-400 animate-spin mb-4" />
          ) : (
            <Upload size={40} className="mx-auto text-slate-400 mb-4" />
          )}
          <p className="text-slate-300 text-lg font-medium">
            {isDragActive ? 'Drop your file here' : 'Drag & drop an Excel or CSV file'}
          </p>
          <p className="text-slate-500 text-sm mt-2">or click to browse (.xlsx, .xls, .csv)</p>
        </div>
      ) : (
        <>
          {/* File Info */}
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-white font-medium">📊 {session.filename}</p>
                <p className="text-sm text-slate-400">
                  {session.rows} rows × {session.columns?.length} columns
                  {session.numeric_columns && session.numeric_columns.length > 0 &&
                    <span className="ml-2 text-indigo-400">({session.numeric_columns.length} numeric)</span>
                  }
                  {session.categorical_columns && session.categorical_columns.length > 0 &&
                    <span className="ml-2 text-emerald-400">({session.categorical_columns.length} categorical)</span>
                  }
                </p>
              </div>
              <button
                onClick={() => { setSession(null); setMessages([]); setChart(null); setChartHistory([]); setSuggestions([]); setPickerConfig(null) }}
                className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg transition-colors"
              >
                Upload New
              </button>
            </div>

            {/* Preview Table */}
            {session.preview && session.preview.length > 0 && (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr>
                      {session.columns?.map(col => (
                        <th key={col} className="text-left p-2 border-b border-slate-700 text-slate-400 font-medium whitespace-nowrap">
                          {col}
                          <span className="ml-1 text-[10px] text-slate-500">
                            {session.numeric_columns?.includes(col) ? '(N)' :
                             session.categorical_columns?.includes(col) ? '(C)' :
                             session.datetime_columns?.includes(col) ? '(D)' : ''}
                          </span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {session.preview.slice(0, 5).map((row, i) => (
                      <tr key={i} className="hover:bg-slate-700/30">
                        {session.columns?.map(col => (
                          <td key={col} className="p-2 border-b border-slate-700/50 text-slate-300 whitespace-nowrap max-w-[200px] truncate">
                            {String(row[col] ?? '')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Smart Chart Suggestions */}
          {suggestions.length > 0 && (
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
              <h3 className="text-sm font-semibold text-white mb-3">
                <Settings2 size={14} className="inline mr-1.5 -mt-0.5" />
                Quick Charts — click to configure & generate
              </h3>
              <div className="flex flex-wrap gap-2">
                {suggestions.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => handleSuggestionClick(s)}
                    disabled={chartLoading}
                    className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border transition-all ${CHART_TYPE_COLORS[s.chart_type] || CHART_TYPE_COLORS.bar}`}
                    title={s.description}
                  >
                    {CHART_TYPE_ICONS[s.chart_type] || <BarChart3 size={14} />}
                    {s.label}
                    <span className="text-[10px] opacity-60">({s.x_column}{s.y_column ? ` × ${s.y_column}` : ''})</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Chat Section */}
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl flex flex-col" style={{ minHeight: '400px' }}>
              <div className="p-4 border-b border-slate-700/50">
                <h3 className="text-sm font-semibold text-white">💬 Data Analysis Chat</h3>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {messages.length === 0 && (
                  <p className="text-slate-500 text-sm text-center py-8">Ask a question about your data...</p>
                )}
                {messages.map((msg, i) => (
                  <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div
                      className={`max-w-[85%] p-3 rounded-xl text-sm ${
                        msg.role === 'user'
                          ? 'bg-indigo-600 text-white'
                          : 'bg-slate-700 text-slate-200'
                      }`}
                    >
                      {msg.role === 'assistant' ? (
                        <ReactMarkdown
                          className="prose prose-invert prose-sm max-w-none"
                          components={{
                            code({ className, children, ...props }) {
                              const isBlock = className?.includes('language-')
                              if (isBlock) {
                                return (
                                  <div className="relative my-2">
                                    <div className="flex items-center justify-between bg-slate-900 px-3 py-1 rounded-t-md border-b border-slate-600">
                                      <span className="text-[10px] text-slate-400 uppercase tracking-wider">
                                        {className?.replace('language-', '') || 'code'}
                                      </span>
                                      <button
                                        onClick={() => navigator.clipboard.writeText(String(children))}
                                        className="text-[10px] text-slate-500 hover:text-white transition-colors"
                                      >
                                        Copy
                                      </button>
                                    </div>
                                    <pre className="!mt-0 !rounded-t-none bg-slate-900 overflow-x-auto">
                                      <code className={className} {...props}>{children}</code>
                                    </pre>
                                  </div>
                                )
                              }
                              return <code className="bg-slate-600/50 px-1 py-0.5 rounded text-xs" {...props}>{children}</code>
                            },
                          }}
                        >
                          {msg.content}
                        </ReactMarkdown>
                      ) : (
                        msg.content
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
              <div className="p-3 border-t border-slate-700/50 flex gap-2">
                <input
                  type="text"
                  value={question}
                  onChange={e => setQuestion(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAsk()}
                  placeholder="What's the average of column X?"
                  className="flex-1 px-3 py-2 bg-slate-900/50 border border-slate-600 rounded-lg text-white text-sm placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
                />
                <button
                  onClick={handleAsk}
                  disabled={loading || !question.trim()}
                  className="p-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-600 text-white rounded-lg transition-colors"
                >
                  <Send size={16} />
                </button>
              </div>
            </div>

            {/* Chart Section */}
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl flex flex-col relative" style={{ minHeight: '400px' }}>
              {/* Column Picker Overlay */}
              {pickerConfig && session && (
                <ColumnPicker
                  config={pickerConfig}
                  allColumns={session.columns || []}
                  numericColumns={session.numeric_columns || []}
                  categoricalColumns={session.categorical_columns || []}
                  onConfirm={handlePresetChart}
                  onCancel={() => setPickerConfig(null)}
                />
              )}

              <div className="p-4 border-b border-slate-700/50 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white">📈 Chart Generator</h3>
                <div className="flex items-center gap-2">
                  {/* Export button */}
                  {chart?.chart_id && (
                    <button
                      onClick={handleExport}
                      className="flex items-center gap-1 px-2 py-1 text-xs bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-md transition-colors"
                      title="Export as PNG"
                    >
                      <Download size={12} />
                      Export
                    </button>
                  )}

                  {/* History dropdown */}
                  <div className="relative" ref={historyRef}>
                    <button
                      onClick={() => { refreshHistory(); setShowHistory(!showHistory) }}
                      className="flex items-center gap-1 px-2 py-1 text-xs bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-md transition-colors"
                    >
                      <ChevronDown size={12} className={`transition-transform ${showHistory ? 'rotate-180' : ''}`} />
                      History{chartHistory.length > 0 && ` (${chartHistory.length})`}
                    </button>

                    {showHistory && chartHistory.length > 0 && (
                      <div className="absolute right-0 top-full mt-1 w-72 max-h-60 overflow-y-auto bg-slate-800 border border-slate-600 rounded-lg shadow-xl z-50">
                        {chartHistory.map(h => (
                          <button
                            key={h.id}
                            onClick={() => handleLoadHistory(h.id)}
                            className="w-full text-left px-3 py-2 text-xs hover:bg-slate-700 border-b border-slate-700/50 last:border-b-0 transition-colors"
                          >
                            <div className="flex items-center justify-between">
                              <span className="text-slate-300 truncate flex-1 mr-2">
                                {h.instruction || h.chart_type}
                              </span>
                              <span className="text-slate-500 shrink-0">{formatTime(h.timestamp)}</span>
                            </div>
                            <span className={`inline-block mt-0.5 px-1.5 py-0.5 rounded text-[10px] ${CHART_TYPE_COLORS[h.chart_type]?.split(' ').slice(0, 2).join(' ') || 'bg-slate-600 text-slate-300'}`}>
                              {h.chart_type}
                            </span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Preset chart type buttons — now open column picker */}
              <div className="px-4 pt-3 flex flex-wrap gap-1.5">
                {(['bar', 'line', 'pie', 'radar', 'scatter', 'heatmap'] as const).map(type => (
                  <button
                    key={type}
                    onClick={() => openColumnPicker(type)}
                    disabled={chartLoading}
                    className={`flex items-center gap-1 px-2 py-1 text-[11px] rounded border transition-all ${CHART_TYPE_COLORS[type]}`}
                  >
                    {CHART_TYPE_ICONS[type]}
                    {CHART_TYPE_LABELS[type]}
                  </button>
                ))}
              </div>

              <div className="flex-1 p-4 flex flex-col">
                {chartLoading ? (
                  <div className="flex-1 flex items-center justify-center">
                    <Loader2 size={32} className="animate-spin text-indigo-400" />
                  </div>
                ) : chart ? (
                  <div className="flex-1 flex items-center justify-center">
                    <img src={chart.image} alt="Generated chart" className="max-w-full max-h-72 rounded-lg" />
                  </div>
                ) : (
                  <div className="flex-1 flex items-center justify-center text-slate-500 text-sm text-center px-4">
                    Click a chart type above to select columns,<br />
                    or describe a chart freely below (AI picks the best columns)
                  </div>
                )}
              </div>
              <div className="p-3 border-t border-slate-700/50 flex gap-2">
                <input
                  type="text"
                  value={chartInstruction}
                  onChange={e => setChartInstruction(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleChart()}
                  placeholder="Free-form: e.g. '按月份展示销售额的柱状图'"
                  className="flex-1 px-3 py-2 bg-slate-900/50 border border-slate-600 rounded-lg text-white text-sm placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
                />
                <button
                  onClick={handleChart}
                  disabled={chartLoading || !chartInstruction.trim()}
                  className="p-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-600 text-white rounded-lg transition-colors"
                >
                  <BarChart3 size={16} />
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
