import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Settings } from 'lucide-react'
import { getApp, AppInfo } from '../services/api'
import ExcelAnalyzer from '../components/ExcelAnalyzer'
import RagReader from '../components/RagReader'
import GenericApp from '../components/GenericApp'
import AppInfoEditModal from '../components/AppInfoEditModal'

export default function AppPage() {
  const { appId } = useParams<{ appId: string }>()
  const navigate = useNavigate()
  const [app, setApp] = useState<AppInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [showEditInfo, setShowEditInfo] = useState(false)

  useEffect(() => {
    if (!appId) return
    getApp(appId)
      .then(setApp)
      .catch(() => navigate('/'))
      .finally(() => setLoading(false))
  }, [appId])

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0f172a] flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500"></div>
      </div>
    )
  }

  if (!app) return null

  // Web mode: redirect to standalone web page in new tab
  const isWebMode = app.config?.mode === 'web'

  const handleOpenWebApp = () => {
    const token = localStorage.getItem('auth_token')
    const url = token
      ? `/api/apps/${app.id}/web?token=${encodeURIComponent(token)}`
      : `/api/apps/${app.id}/web`
    window.open(url, '_blank')
  }

  const renderAppContent = () => {
    switch (app.id) {
      case 'excel_analyzer':
        return <ExcelAnalyzer />
      case 'rag_reader':
        return <RagReader />
      default:
        return <GenericApp appId={app.id} appName={app.name} appConfig={app.config} />
    }
  }

  return (
    <div className="min-h-screen bg-[#0f172a]">
      {/* Header */}
      <header className="border-b border-slate-700/50 bg-[#0f172a]/80 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/')}
              className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
            >
              <ArrowLeft size={20} />
            </button>
            <div className="flex items-center gap-3">
              <span className="text-2xl">{app.icon}</span>
              <div>
                <h1 className="text-lg font-semibold text-white">{app.name}</h1>
                <p className="text-xs text-slate-400">{app.description}</p>
              </div>
            </div>
          </div>
          <button
            onClick={() => setShowEditInfo(true)}
            className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
            title="Edit app info"
          >
            <Settings size={18} />
          </button>
        </div>
      </header>

      {/* App Content */}
      <main className="max-w-7xl mx-auto px-6 py-6">
        {isWebMode ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="text-6xl mb-4">🌐</div>
            <h2 className="text-xl font-semibold text-white mb-2">Standalone Web Application</h2>
            <p className="text-slate-400 mb-6 max-w-md">
              This app runs as a standalone web page in a new browser tab with its own full interface.
            </p>
            <button
              onClick={handleOpenWebApp}
              className="px-6 py-3 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white rounded-xl text-sm font-medium transition-all shadow-lg shadow-cyan-500/25 flex items-center gap-2"
            >
              <span>🚀</span>
              Open in New Tab
            </button>
            <p className="text-xs text-slate-500 mt-4">
              The app will open at: <code className="text-slate-400">/api/apps/{app.id}/web</code>
            </p>
          </div>
        ) : (
          renderAppContent()
        )}
      </main>

      {/* Edit Info Modal */}
      {showEditInfo && app && (
        <AppInfoEditModal
          app={app}
          onClose={() => setShowEditInfo(false)}
          onSaved={(updated) => {
            setApp(updated)
            setShowEditInfo(false)
          }}
        />
      )}
    </div>
  )
}
