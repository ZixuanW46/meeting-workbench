import { useEffect, useState } from 'react'
import {
  createHotword,
  deleteHotword,
  formatApiError,
  listHotwords,
  updateHotwordNote,
  type Hotword,
} from '../api/client'
import { Icon } from '../components/Icon'

/** 全局词库：词本身随快照进入转写热词；注解与词一起作为术语表喂给纪要 LLM。 */
export function HotwordsPage() {
  const [hotwords, setHotwords] = useState<Hotword[] | null>(null)
  const [input, setInput] = useState('')
  const [noteInput, setNoteInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  // 就地编辑注解：一次只编辑一行。
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingNote, setEditingNote] = useState('')
  const [savingNote, setSavingNote] = useState(false)

  useEffect(() => {
    let stale = false
    listHotwords()
      .then((items) => {
        if (!stale) {
          setHotwords(items)
        }
      })
      .catch((e: unknown) => {
        if (!stale) {
          setError(formatApiError(e))
        }
      })
    return () => {
      stale = true
    }
  }, [])

  const onAdd = () => {
    const word = input.trim()
    const note = noteInput.trim()
    if (word === '' || adding) {
      return
    }
    setAdding(true)
    setError(null)
    createHotword(word, note === '' ? undefined : note)
      .then((created) => {
        setHotwords((current) =>
          current === null
            ? current
            : [...current, created].sort((a, b) => a.word.localeCompare(b.word, 'zh')),
        )
        setInput('')
        setNoteInput('')
      })
      .catch((e: unknown) => {
        setError(formatApiError(e))
      })
      .finally(() => {
        setAdding(false)
      })
  }

  const onDelete = (hotwordId: string) => {
    setDeletingId(hotwordId)
    setError(null)
    deleteHotword(hotwordId)
      .then(() => {
        setHotwords((current) =>
          current === null ? current : current.filter((item) => item.id !== hotwordId),
        )
      })
      .catch((e: unknown) => {
        setError(formatApiError(e))
      })
      .finally(() => {
        setDeletingId(null)
      })
  }

  const startEditNote = (hotword: Hotword) => {
    setEditingId(hotword.id)
    setEditingNote(hotword.note ?? '')
  }

  const saveNote = (hotwordId: string) => {
    if (savingNote) {
      return
    }
    const trimmed = editingNote.trim()
    setSavingNote(true)
    setError(null)
    updateHotwordNote(hotwordId, trimmed === '' ? null : trimmed)
      .then((updated) => {
        setHotwords((current) =>
          current === null
            ? current
            : current.map((item) => (item.id === hotwordId ? updated : item)),
        )
        setEditingId(null)
      })
      .catch((e: unknown) => {
        setError(formatApiError(e))
      })
      .finally(() => {
        setSavingNote(false)
      })
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">词库</h1>
          <p className="page-subtitle">
            全局热词随每场会议快照进入转写，帮助认出产品名、人名等专有名词；改动只影响之后开始转写的会议。注解会作为公司术语表喂给纪要
            LLM，用于纠正近音误写
          </p>
        </div>
      </div>

      {error !== null && <div className="notice notice-error">{error}</div>}

      <div className="card" style={{ marginBottom: 12 }}>
        {/* form-field：label 在上、输入框在下（6px 间距），与新建会议表单一致 */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <div className="form-field" style={{ width: 240 }}>
            <label htmlFor="hotword-input">添加词语</label>
            <input
              id="hotword-input"
              className="input"
              value={input}
              placeholder="输入后回车添加"
              disabled={adding}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  onAdd()
                }
              }}
            />
          </div>
          <div className="form-field" style={{ flex: 1, minWidth: 260 }}>
            <label htmlFor="hotword-note-input">注解（选填，喂给纪要 LLM）</label>
            <input
              id="hotword-note-input"
              className="input"
              value={noteInput}
              placeholder="这个词是什么、常被误写成什么"
              disabled={adding}
              onChange={(event) => setNoteInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  onAdd()
                }
              }}
            />
          </div>
        </div>
      </div>

      {hotwords !== null && (
        <div className="list-card">
          {hotwords.length === 0 ? (
            <div className="empty">
              <div className="empty-title">词库是空的</div>
              <div>把常出现的产品名、人名、术语加进来，转写会更认得它们</div>
            </div>
          ) : (
            hotwords.map((hotword) => (
              <div key={hotword.id} className="list-row">
                <div style={{ flex: 1, minWidth: 0 }}>
                  <span className="list-row-title">{hotword.word}</span>
                  {editingId === hotword.id ? (
                    <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                      <input
                        className="input"
                        style={{ flex: 1 }}
                        aria-label={`注解内容 ${hotword.word}`}
                        value={editingNote}
                        placeholder="留空并保存即清除注解"
                        disabled={savingNote}
                        autoFocus
                        onChange={(event) => setEditingNote(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') {
                            event.preventDefault()
                            saveNote(hotword.id)
                          }
                          if (event.key === 'Escape') {
                            setEditingId(null)
                          }
                        }}
                      />
                      <button
                        type="button"
                        className="btn"
                        disabled={savingNote}
                        onClick={() => saveNote(hotword.id)}
                      >
                        保存
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        disabled={savingNote}
                        onClick={() => setEditingId(null)}
                      >
                        取消
                      </button>
                    </div>
                  ) : (
                    hotword.note !== null && (
                      <div className="section-desc" style={{ marginTop: 2 }}>
                        {hotword.note}
                      </div>
                    )
                  )}
                </div>
                {editingId !== hotword.id && (
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => startEditNote(hotword)}
                    aria-label={`${hotword.note === null ? '添加' : '编辑'}注解 ${hotword.word}`}
                  >
                    <Icon name="edit" size={12} />
                    {hotword.note === null ? '添加注解' : '编辑注解'}
                  </button>
                )}
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={deletingId === hotword.id}
                  onClick={() => onDelete(hotword.id)}
                  aria-label={`删除词语 ${hotword.word}`}
                >
                  <Icon name="trash" size={12} />
                  删除
                </button>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
