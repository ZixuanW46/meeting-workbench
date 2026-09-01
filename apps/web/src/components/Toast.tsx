import { useEffect, useState } from 'react'
import { Icon } from './Icon'

export type ToastKind = 'success' | 'error'

interface ToastItem {
  id: number
  kind: ToastKind
  message: string
}

type Listener = (item: ToastItem) => void

// 模块级发射器：任何页面调 toast()，App 里唯一的 <Toaster/> 负责渲染。
const listeners = new Set<Listener>()
let nextId = 1

export function toast(message: string, kind: ToastKind = 'success'): void {
  const item = { id: nextId, kind, message }
  nextId += 1
  for (const listener of listeners) {
    listener(item)
  }
}

/** 右下角操作反馈：成功 4s、错误 6s 自动消失，点击立即关闭。 */
export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([])

  useEffect(() => {
    const timers: number[] = []
    const onToast = (item: ToastItem) => {
      setItems((current) => [...current, item])
      timers.push(
        window.setTimeout(
          () => setItems((current) => current.filter((t) => t.id !== item.id)),
          item.kind === 'error' ? 6000 : 4000,
        ),
      )
    }
    listeners.add(onToast)
    return () => {
      listeners.delete(onToast)
      for (const timer of timers) {
        window.clearTimeout(timer)
      }
    }
  }, [])

  if (items.length === 0) {
    return null
  }
  return (
    <div className="toaster" role="status" aria-live="polite">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          className={`toast toast-${item.kind}`}
          onClick={() =>
            setItems((current) => current.filter((t) => t.id !== item.id))
          }
        >
          <Icon name={item.kind === 'error' ? 'close' : 'check'} size={12} />
          {item.message}
        </button>
      ))}
    </div>
  )
}
