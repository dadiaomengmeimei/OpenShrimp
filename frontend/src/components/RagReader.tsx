import { useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, Send, Loader2, FileText } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { uploadDocument, queryDocument, UploadResult } from '../services/api'

export default function RagReader() {
  const [session, setSession] = useState<UploadResult | null>(null)
  const [uploading, setUploading] = useState(false)
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<Array<{ role: string; content: string; sources?: number }>>([])
  const [loading, setLoading] = useState(false)

  const onDrop = useCallback(async (files: File[]) => {
    if (files.length === 0) return
    setUploading(true)
    try {
      const result = await uploadDocument(files[0])
      setSession(result)
      setMessages([])
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'text/plain': ['.txt'],
      'text/markdown': ['.md'],
    },
    maxFiles: 1,
  })

  const handleAsk = async () => {
    if (!session || !question.trim()) return
    const q = question.trim()
    setQuestion('')
    setMessages(prev => [...prev, { role: 'user', content: q }])
    setLoading(true)
    try {
      const { answer, sources } = await queryDocument(session.session_id, q)
      setMessages(prev => [...prev, { role: 'assistant', content: answer, sources }])
    } catch (err: any) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${err.response?.data?.detail || err.message}` }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Upload Area */}
      {!session ? (
        <div
          {...getRootProps()}
          className={`border-2 border-dashed rounded-2xl p-12 text-center cursor-pointer transition-all ${
            isDragActive
              ? 'border-emerald-500 bg-emerald-500/10'
              : 'border-slate-600 hover:border-slate-500 bg-slate-800/30'
          }`}
        >
          <input {...getInputProps()} />
          {uploading ? (
            <Loader2 size={40} className="mx-auto text-emerald-400 animate-spin mb-4" />
          ) : (
            <FileText size={40} className="mx-auto text-slate-400 mb-4" />
          )}
          <p className="text-slate-300 text-lg font-medium">
            {isDragActive ? 'Drop your document here' : 'Drag & drop a document'}
          </p>
          <p className="text-slate-500 text-sm mt-2">Supports PDF, DOCX, TXT, MD</p>
        </div>
      ) : (
        <>
          {/* Doc Info */}
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4 flex items-center justify-between">
            <div>
              <p className="text-white font-medium">📄 {session.filename}</p>
              <p className="text-sm text-slate-400">
                {session.total_chars?.toLocaleString()} characters · {session.num_chunks} chunks
              </p>
            </div>
            <button
              onClick={() => { setSession(null); setMessages([]) }}
              className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg transition-colors"
            >
              Upload New
            </button>
          </div>

          {/* Preview */}
          {session.preview && (
            <div className="bg-slate-800/30 border border-slate-700/30 rounded-xl p-4">
              <h4 className="text-xs text-slate-400 mb-2 font-medium">Document Preview</h4>
              <p className="text-sm text-slate-300 whitespace-pre-wrap line-clamp-6">{session.preview}</p>
            </div>
          )}

          {/* Chat */}
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl flex flex-col" style={{ minHeight: '450px' }}>
            <div className="p-4 border-b border-slate-700/50">
              <h3 className="text-sm font-semibold text-white">💬 Ask about your document</h3>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {messages.length === 0 && (
                <p className="text-slate-500 text-sm text-center py-8">Ask a question about the document...</p>
              )}
              {messages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[85%] p-3 rounded-xl text-sm ${
                      msg.role === 'user'
                        ? 'bg-emerald-600 text-white'
                        : 'bg-slate-700 text-slate-200'
                    }`}
                  >
                    {msg.role === 'assistant' ? (
                      <>
                        <ReactMarkdown className="prose prose-invert prose-sm max-w-none">{msg.content}</ReactMarkdown>
                        {msg.sources !== undefined && (
                          <p className="text-xs text-slate-400 mt-2">Based on {msg.sources} document chunks</p>
                        )}
                      </>
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
                placeholder="What is this document about?"
                className="flex-1 px-3 py-2 bg-slate-900/50 border border-slate-600 rounded-lg text-white text-sm placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
              />
              <button
                onClick={handleAsk}
                disabled={loading || !question.trim()}
                className="p-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-600 text-white rounded-lg transition-colors"
              >
                <Send size={16} />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
