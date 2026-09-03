import { useState } from 'react'
import { createProject, formatApiError, type Project } from '../api/client'
import { Icon } from './Icon'

interface InlineProjectCreateProps {
  /** 创建成功后回调：调用方负责把新项目并进自己的列表并选中它 */
  onCreated: (project: Project) => void
  /**
   * 紧凑形态：触发器长得像一颗筛选 pill（会议列表筛选栏用），
   * 默认形态是次级文字按钮（表单、元信息行用）
   */
  compact?: boolean
}

/**
 * 就地新建项目：平时只是一个「新建项目」按钮，点开才变成一行输入 + 创建/取消。
 * 回车创建、Esc 取消；重名等后端错误显示在行内，不打扰调用页自己的错误区。
 */
export function InlineProjectCreate({ onCreated, compact = false }: InlineProjectCreateProps) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const close = () => {
    setOpen(false)
    setName('')
    setError(null)
  }

  const submit = () => {
    const trimmed = name.trim()
    if (trimmed === '' || saving) {
      return
    }
    setSaving(true)
    setError(null)
    createProject(trimmed)
      .then((created) => {
        onCreated(created)
        setOpen(false)
        setName('')
      })
      .catch((e: unknown) => {
        setError(formatApiError(e))
      })
      .finally(() => {
        setSaving(false)
      })
  }

  if (!open) {
    return (
      <button
        type="button"
        className={compact ? 'pill-add' : 'btn btn-ghost'}
        onClick={() => setOpen(true)}
      >
        <Icon name="plus" size={compact ? 11 : 12} />
        新建项目
      </button>
    )
  }

  return (
    <span className={`inline-create${compact ? ' inline-create-compact' : ''}`}>
      <span className="inline-create-row">
        <input
          className="input"
          aria-label="新项目名字"
          placeholder="项目名字，回车创建"
          value={name}
          disabled={saving}
          autoFocus
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              submit()
            }
            if (event.key === 'Escape') {
              event.preventDefault()
              close()
            }
          }}
        />
        <button
          type="button"
          className="btn"
          aria-label="创建项目"
          disabled={saving || name.trim() === ''}
          onClick={submit}
        >
          创建
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          aria-label="取消新建项目"
          disabled={saving}
          onClick={close}
        >
          取消
        </button>
      </span>
      {error !== null && (
        <span className="inline-create-error" role="alert">
          {error}
        </span>
      )}
    </span>
  )
}
