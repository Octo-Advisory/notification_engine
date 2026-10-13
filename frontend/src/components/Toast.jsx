import { createContext, useCallback, useContext, useState } from 'react'
import { CheckCircle2, Info, XCircle } from 'lucide-react'

const ToastContext = createContext(() => {})

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const toast = useCallback((message, tone = 'good') => {
    const id = Math.random()
    setToasts((t) => [...t, { id, message, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'bad' ? 7000 : 4000)
  }, [])
  const icons = { good: CheckCircle2, bad: XCircle, info: Info }
  const colors = { good: 'text-good-text', bad: 'text-bad-text', info: 'text-accent-text' }
  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="fixed bottom-4 right-4 left-4 sm:left-auto z-50 flex flex-col gap-2 items-end" aria-live="polite">
        {toasts.map((t) => {
          const Icon = icons[t.tone]
          return (
            <div key={t.id} className="card shadow-lg px-4 py-3 flex gap-2 items-start max-w-sm">
              <Icon size={16} className={`mt-0.5 flex-none ${colors[t.tone]}`} />
              <span>{t.message}</span>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
