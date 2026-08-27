import { useEffect, useState } from 'react'
import {
  createHotword,
  deleteHotword,
  formatApiError,
  listHotwords,
  type Hotword,
} from '../api/client'
import { Icon } from '../components/Icon'

/** 全局词库：随每场会议的词库快照进入转写，帮助认出专有名词。 */
export function HotwordsPage() {
  const [hotwords, setHotwords] = useState<Hotword[] | null>(null)
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

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
    if (word === '' || adding) {
      return
    }
    setAdding(true)
    setError(null)
    createHotword(word)
      .then((created) => {
        setHotwords((current) =>
          current === null
            ? current
            : [...current, created].sort((a, b) => a.word.localeCompare(b.word, 'zh')),
        )
        setInput('')
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

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">词库</h1>
          <p className="page-subtitle">
            全局热词随每场会议快照进入转写，帮助认出产品名、人名等专有名词；改动只影响之后开始转写的会议
          </p>
        </div>
      </div>

      {error !== null && <div className="notice notice-error">{error}</div>}

      <div className="card" style={{ marginBottom: 12 }}>
        <label className="form-label" htmlFor="hotword-input">
          添加词语
        </label>
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
                <span className="list-row-title">{hotword.word}</span>
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
