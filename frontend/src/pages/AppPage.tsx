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
        {renderAppContent()}
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
