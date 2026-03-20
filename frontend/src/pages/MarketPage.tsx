import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Search, Plus, Check, ShoppingBag, Loader2 } from 'lucide-react'
import { listMarket, addFromMarket, AppInfo } from '../services/api'
import { useAuth } from '../contexts/AuthContext'

export default function MarketPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [apps, setApps] = useState<AppInfo[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [addingId, setAddingId] = useState<string | null>(null)

  const fetchMarket = async () => {
    try {
      const data = await listMarket()
      setApps(data)
    } catch (e) {
      console.error('Failed to load market:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchMarket() }, [])

  const filtered = apps.filter(a =>
    a.name.toLowerCase().includes(search.toLowerCase()) ||
    a.description.toLowerCase().includes(search.toLowerCase()) ||
    a.category.toLowerCase().includes(search.toLowerCase())
  )

  const handleAdd = async (e: React.MouseEvent, appId: string) => {
    e.stopPropagation()
    setAddingId(appId)
    try {
      await addFromMarket(appId)
      // Update local state to reflect the change
      setApps(prev => prev.map(a => a.id === appId ? { ...a, added_by_user: true } : a))
    } catch (err) {
      console.error('Failed to add app:', err)
    } finally {
      setAddingId(null)
    }
  }

  const categoryColors: Record<string, string> = {
    data: 'bg-blue-500/20 text-blue-400',
    knowledge: 'bg-emerald-500/20 text-emerald-400',
    general: 'bg-purple-500/20 text-purple-400',
    media: 'bg-orange-500/20 text-orange-400',
  }

  return (
    <div className="min-h-screen bg-[#0f172a]">
      {/* Header */}
      <header className="border-b border-slate-700/50 bg-[#0f172a]/80 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/')}
              className="p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
            >
              <ArrowLeft size={20} />
            </button>
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center text-xl">
                <ShoppingBag size={20} className="text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-white">App Market</h1>
                <p className="text-xs text-slate-400">Browse and add public apps to your workspace</p>
              </div>
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
            placeholder="Search market apps..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-12 pr-4 py-3 bg-slate-800/50 border border-slate-700/50 rounded-xl text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500/50 transition-all"
          />
        </div>
      </div>

      {/* Stats */}
      <div className="max-w-7xl mx-auto px-6 mt-4">
        <p className="text-sm text-slate-400">
          {filtered.length} app{filtered.length !== 1 ? 's' : ''} available in the market
        </p>
      </div>

      {/* App Grid */}
      <main className="max-w-7xl mx-auto px-6 py-6">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-emerald-500"></div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-20 text-slate-400">
            <p className="text-5xl mb-4">🏪</p>
            <p className="text-lg">No apps in the market yet</p>
            <p className="text-sm mt-2">Be the first to publish an app!</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
            {filtered.map(app => (
              <div
                key={app.id}
                className="group relative bg-slate-800/50 hover:bg-slate-800 border border-slate-700/50 hover:border-slate-600 rounded-2xl p-5 transition-all hover:shadow-xl hover:shadow-slate-900/50"
              >
                {/* Add button */}
                <div className="absolute top-3 right-3">
                  {app.added_by_user ? (
                    <span className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-400 text-xs">
                      <Check size={12} />
                      Added
                    </span>
                  ) : (
                    <button
                      onClick={e => handleAdd(e, app.id)}
                      disabled={addingId === app.id}
                      className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-600 text-white text-xs transition-colors"
                    >
                      {addingId === app.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Plus size={12} />
                      )}
                      Add
                    </button>
                  )}
                </div>

                {/* Icon */}
                <div className="text-4xl mb-3">{app.icon}</div>

                {/* Name & Description */}
                <h3 className="text-base font-semibold text-white mb-1.5">{app.name}</h3>
                <p className="text-sm text-slate-400 line-clamp-2 mb-3">{app.description}</p>

                {/* Footer */}
                <div className="flex items-center justify-between">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${categoryColors[app.category] || categoryColors.general}`}>
                    {app.category}
                  </span>
                  <span className="text-xs text-slate-500">
                    by {app.author || 'unknown'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
