import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Sparkles, Trash2, Search, Pencil, ShoppingBag, Globe, LogOut, Shield, Info } from 'lucide-react'
import { listApps, createApp, deleteApp, publishApp, unpublishApp, AppInfo } from '../services/api'
import { useAuth } from '../contexts/AuthContext'
import ImportModal from '../components/ImportModal'
import AgentModal from '../components/AgentModal'
import AppInfoEditModal from '../components/AppInfoEditModal'

export default function HomePage() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const [apps, setApps] = useState<AppInfo[]>([])
  const [search, setSearch] = useState('')
  const [showImport, setShowImport] = useState(false)
  const [showAgent, setShowAgent] = useState(false)
  const [editTarget, setEditTarget] = useState<{ id: string; name: string } | null>(null)
  const [editInfoApp, setEditInfoApp] = useState<AppInfo | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchApps = async () => {
    try {
      const data = await listApps()
      setApps(data)
    } catch (e) {
      console.error('Failed to load apps:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchApps() }, [])

  const filtered = apps.filter(a =>
    a.name.toLowerCase().includes(search.toLowerCase()) ||
    a.description.toLowerCase().includes(search.toLowerCase()) ||
    a.category.toLowerCase().includes(search.toLowerCase())
  )

  const handleDelete = async (e: React.MouseEvent, appId: string) => {
    e.stopPropagation()
    if (!confirm('Are you sure you want to delete this app?')) return
    await deleteApp(appId)
    fetchApps()
  }

  const handleEdit = (e: React.MouseEvent, app: AppInfo) => {
    e.stopPropagation()
    setEditTarget({ id: app.id, name: app.name })
    setShowAgent(true)
  }

  const handlePublish = async (e: React.MouseEvent, app: AppInfo) => {
    e.stopPropagation()
    try {
      if (app.is_public) {
        await unpublishApp(app.id)
      } else {
        await publishApp(app.id)
      }
      fetchApps()
    } catch (err) {
      console.error('Failed to toggle publish:', err)
    }
  }

  const handleImport = async (data: Partial<AppInfo>) => {
    await createApp(data)
    setShowImport(false)
    fetchApps()
  }

  const handleAgentComplete = () => {
    setShowAgent(false)
    setEditTarget(null)
    fetchApps()
  }

  const handleAgentClose = () => {
    setShowAgent(false)
    setEditTarget(null)
    fetchApps()
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const categoryColors: Record<string, string> = {
    data: 'bg-blue-500/20 text-blue-400',
    knowledge: 'bg-emerald-500/20 text-emerald-400',
    general: 'bg-purple-500/20 text-purple-400',
    media: 'bg-orange-500/20 text-orange-400',
  }

  // Can the current user manage this app?
  const canManage = (app: AppInfo) => {
    if (!user) return false
    if (user.is_admin) return true
    return app.author_id === user.id || !app.author_id  // Own app or platform app
  }

  return (
    <div className="min-h-screen bg-[#0f172a]">
      {/* Header */}
      <header className="border-b border-slate-700/50 bg-[#0f172a]/80 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-500 to-rose-600 flex items-center justify-center text-xl">
              🦐
            </div>
            <div>
              <h1 className="text-xl font-bold text-white">AppShrimp</h1>
              <p className="text-xs text-slate-400">AI App Store</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/market')}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600/80 hover:bg-emerald-500 text-white rounded-lg text-sm font-medium transition-all"
            >
              <ShoppingBag size={16} />
              Market
            </button>
            <button
              onClick={() => { setEditTarget(null); setShowAgent(true) }}
              className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white rounded-lg text-sm font-medium transition-all shadow-lg shadow-purple-500/25"
            >
              <Sparkles size={16} />
              AI Generate
            </button>
            <button
              onClick={() => setShowImport(true)}
              className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg text-sm font-medium transition-colors"
            >
              <Plus size={16} />
              Import
            </button>

            {/* User info & logout */}
            <div className="flex items-center gap-2 ml-2 pl-3 border-l border-slate-700">
              <div className="flex items-center gap-1.5">
                <div className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center text-white text-xs font-bold">
                  {(user?.display_name || user?.username || '?')[0].toUpperCase()}
                </div>
                <div className="text-xs">
                  <p className="text-white font-medium leading-tight">{user?.display_name || user?.username}</p>
                  <p className="text-slate-500 leading-tight flex items-center gap-0.5">
                    {user?.is_admin && <Shield size={8} className="text-amber-400" />}
                    {user?.is_admin ? 'admin' : 'user'}
                  </p>
                </div>
              </div>
              <button
                onClick={handleLogout}
                className="p-1.5 rounded-lg hover:bg-slate-700 text-slate-400 hover:text-red-400 transition-colors"
                title="Sign out"
              >
                <LogOut size={14} />
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Search */}
      <div className="max-w-7xl mx-auto px-6 mt-8">
        <div className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
          <input
            type="text"
            placeholder="Search your apps..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-12 pr-4 py-3 bg-slate-800/50 border border-slate-700/50 rounded-xl text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/50 transition-all"
          />
        </div>
      </div>

      {/* App Grid */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500"></div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-20 text-slate-400">
            <p className="text-5xl mb-4">📭</p>
            <p className="text-lg">No apps found</p>
            <p className="text-sm mt-2">
              Generate an app with AI, import one, or browse the{' '}
              <button onClick={() => navigate('/market')} className="text-emerald-400 hover:text-emerald-300 underline">
                Market
              </button>
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
            {filtered.map(app => (
              <div
                key={app.id}
                onClick={() => {
                  // Web mode apps open in a new browser tab
                  if (app.config?.mode === 'web') {
                    const token = localStorage.getItem('auth_token')
                    const url = token
                      ? `/api/apps/${app.id}/web?token=${encodeURIComponent(token)}`
                      : `/api/apps/${app.id}/web`
                    window.open(url, '_blank')
                  } else {
                    navigate(`/app/${app.id}`)
                  }
                }}
                className="group relative bg-slate-800/50 hover:bg-slate-800 border border-slate-700/50 hover:border-slate-600 rounded-2xl p-5 cursor-pointer transition-all hover:shadow-xl hover:shadow-slate-900/50 hover:-translate-y-1"
              >
                {/* Action buttons */}
                {canManage(app) && (
                  <div className="absolute top-3 right-3 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all">
                    {/* Publish/unpublish toggle (own apps, unowned apps, or admin) */}
                    {(app.author_id === user?.id || !app.author_id || user?.is_admin) && (
                      <button
                        onClick={e => handlePublish(e, app)}
                        className={`p-1.5 rounded-lg bg-slate-700/50 transition-colors ${
                          app.is_public
                            ? 'hover:bg-emerald-500/20 text-emerald-400'
                            : 'hover:bg-blue-500/20 text-slate-400 hover:text-blue-400'
                        }`}
                        title={app.is_public ? 'Unpublish from market' : 'Publish to market'}
                      >
                        <Globe size={14} />
                      </button>
                    )}
                    <button
                      onClick={e => { e.stopPropagation(); setEditInfoApp(app) }}
                      className="p-1.5 rounded-lg bg-slate-700/50 hover:bg-indigo-500/20 text-slate-400 hover:text-indigo-400 transition-colors"
                      title="Edit icon & description"
                    >
                      <Info size={14} />
                    </button>
                    <button
                      onClick={e => handleEdit(e, app)}
                      className="p-1.5 rounded-lg bg-slate-700/50 hover:bg-purple-500/20 text-slate-400 hover:text-purple-400 transition-colors"
                      title="Edit with AI"
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={e => handleDelete(e, app.id)}
                      className="p-1.5 rounded-lg bg-slate-700/50 hover:bg-red-500/20 text-slate-400 hover:text-red-400 transition-colors"
                      title="Delete app"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                )}

                {/* Icon */}
                <div className="text-4xl mb-3">{app.icon}</div>

                {/* Public badge */}
                {app.is_public && (
                  <span className="absolute top-3 left-3 text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
                    Public
                  </span>
                )}

                {/* Web mode badge */}
                {app.config?.mode === 'web' && (
                  <span className={`absolute ${app.is_public ? 'top-8' : 'top-3'} left-3 text-[10px] px-1.5 py-0.5 rounded-full bg-cyan-500/15 text-cyan-400 border border-cyan-500/20 flex items-center gap-0.5`}>
                    🌐 Web
                  </span>
                )}

                {/* Name & Description */}
                <h3 className="text-base font-semibold text-white mb-1.5">{app.name}</h3>
                <p className="text-sm text-slate-400 line-clamp-2 mb-3">{app.description}</p>

                {/* Footer */}
                <div className="flex items-center justify-between">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${categoryColors[app.category] || categoryColors.general}`}>
                    {app.category}
                  </span>
                  <span className="text-xs text-slate-500">v{app.version}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Modals */}
      {showImport && <ImportModal onClose={() => setShowImport(false)} onImport={handleImport} />}
      {showAgent && (
        <AgentModal
          onClose={handleAgentClose}
          onComplete={handleAgentComplete}
          editAppId={editTarget?.id}
          editAppName={editTarget?.name}
        />
      )}
      {editInfoApp && (
        <AppInfoEditModal
          app={editInfoApp}
          onClose={() => setEditInfoApp(null)}
          onSaved={() => {
            setEditInfoApp(null)
            fetchApps()
          }}
        />
      )}
    </div>
  )
}
