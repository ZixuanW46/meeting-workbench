import { useEffect, useState } from 'react'
import {
  createHotword,
  createProject,
  createProjectHotword,
  deleteHotword,
  deleteProject,
  deleteProjectHotword,
  formatApiError,
  listHotwords,
  listProjectHotwords,
  listProjects,
  renameProject,
  updateHotwordNote,
  updateProjectHotwordNote,
  type Hotword,
  type Project,
} from '../api/client'
import { Icon } from '../components/Icon'

function byName(a: Project, b: Project): number {
  return a.name.localeCompare(b.name, 'zh')
}

function byWord(a: Hotword, b: Hotword): number {
  return a.word.localeCompare(b.word, 'zh')
}

/**
 * 词库：左栏选范围（通用 / 各项目），右栏是该范围的词条。
 * 通用词随每场会议快照进入转写；项目词只跟着该项目的会议走；两者与本场热词叠加。
 */
export function HotwordsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  // 当前范围：null = 通用词库，其余是项目 id
  const [scopeId, setScopeId] = useState<string | null>(null)
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
  // 左栏项目维护：新建 / 重命名 / 删除（删除走二次确认）
  const [newProjectName, setNewProjectName] = useState('')
  const [creatingProject, setCreatingProject] = useState(false)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [savingRename, setSavingRename] = useState(false)
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null)
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null)

  const scope = projects.find((project) => project.id === scopeId) ?? null
  const scopeName = scopeId === null ? '通用' : (scope?.name ?? '项目')

  useEffect(() => {
    let stale = false
    listProjects()
      .then((items) => {
        if (!stale) {
          setProjects([...items].sort(byName))
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

  // 切范围就换数据源：通用走 /api/hotwords，项目走 /api/projects/{id}/hotwords
  useEffect(() => {
    let stale = false
    setHotwords(null)
    setEditingId(null)
    const loading = scopeId === null ? listHotwords() : listProjectHotwords(scopeId)
    loading
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
  }, [scopeId])

  // 左栏计数跟着右栏增删走，省一次列表请求
  const bumpCount = (projectId: string | null, delta: number) => {
    if (projectId === null) {
      return
    }
    setProjects((current) =>
      current.map((project) =>
        project.id === projectId
          ? { ...project, hotword_count: project.hotword_count + delta }
          : project,
      ),
    )
  }

  const onAdd = () => {
    const word = input.trim()
    const note = noteInput.trim()
    if (word === '' || adding) {
      return
    }
    const target = scopeId
    setAdding(true)
    setError(null)
    const creating =
      target === null
        ? createHotword(word, note === '' ? undefined : note)
        : createProjectHotword(target, word, note === '' ? undefined : note)
    creating
      .then((created) => {
        setHotwords((current) =>
          current === null ? current : [...current, created].sort(byWord),
        )
        bumpCount(target, 1)
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
    const target = scopeId
    setDeletingId(hotwordId)
    setError(null)
    const removing =
      target === null ? deleteHotword(hotwordId) : deleteProjectHotword(target, hotwordId)
    removing
      .then(() => {
        setHotwords((current) =>
          current === null ? current : current.filter((item) => item.id !== hotwordId),
        )
        bumpCount(target, -1)
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
    const note = trimmed === '' ? null : trimmed
    setSavingNote(true)
    setError(null)
    const saving =
      scopeId === null
        ? updateHotwordNote(hotwordId, note)
        : updateProjectHotwordNote(scopeId, hotwordId, note)
    saving
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

  const onCreateProject = () => {
    const name = newProjectName.trim()
    if (name === '' || creatingProject) {
      return
    }
    setCreatingProject(true)
    setError(null)
    createProject(name)
      .then((created) => {
        setProjects((current) => [...current, created].sort(byName))
        setNewProjectName('')
        setScopeId(created.id)
      })
      .catch((e: unknown) => {
        setError(formatApiError(e))
      })
      .finally(() => {
        setCreatingProject(false)
      })
  }

  const onRenameProject = (projectId: string) => {
    const name = renameDraft.trim()
    if (name === '' || savingRename) {
      return
    }
    setSavingRename(true)
    setError(null)
    renameProject(projectId, name)
      .then((updated) => {
        setProjects((current) =>
          current.map((project) => (project.id === projectId ? updated : project)).sort(byName),
        )
        setRenamingId(null)
      })
      .catch((e: unknown) => {
        setError(formatApiError(e))
      })
      .finally(() => {
        setSavingRename(false)
      })
  }

  const onDeleteProject = (projectId: string) => {
    setDeletingProjectId(projectId)
    setError(null)
    deleteProject(projectId)
      .then(() => {
        setProjects((current) => current.filter((project) => project.id !== projectId))
        setConfirmingDeleteId(null)
        // 删的正好是当前范围，就回到通用
        setScopeId((current) => (current === projectId ? null : current))
      })
      .catch((e: unknown) => {
        setError(formatApiError(e))
      })
      .finally(() => {
        setDeletingProjectId(null)
      })
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">词库</h1>
          <p className="page-subtitle">
            热词随每场会议快照进入转写，帮助认出产品名、人名等专有名词；改动只影响之后开始转写的会议。注解会作为公司术语表喂给纪要
            LLM，用于纠正近音误写
          </p>
        </div>
      </div>

      {error !== null && <div className="notice notice-error">{error}</div>}

      <div className="hotword-layout">
        <div className="scope-rail">
          <div className="scope-list">
            <div className="scope-row">
              <button
                type="button"
                className={`scope-item${scopeId === null ? ' active' : ''}`}
                aria-current={scopeId === null}
                onClick={() => setScopeId(null)}
              >
                <span className="scope-name">通用</span>
              </button>
            </div>

            {projects.map((project) => {
              if (confirmingDeleteId === project.id) {
                return (
                  <div key={project.id} className="scope-confirm">
                    <div className="scope-confirm-text">
                      删除「{project.name}」？该项目的会议会变成无项目，项目热词一并删除。
                    </div>
                    <div className="scope-confirm-actions">
                      <button
                        type="button"
                        className="btn btn-danger"
                        disabled={deletingProjectId === project.id}
                        onClick={() => onDeleteProject(project.id)}
                      >
                        确认删除
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        disabled={deletingProjectId === project.id}
                        onClick={() => setConfirmingDeleteId(null)}
                      >
                        取消
                      </button>
                    </div>
                  </div>
                )
              }
              if (renamingId === project.id) {
                return (
                  <div key={project.id} className="scope-rename">
                    <input
                      className="input"
                      aria-label={`项目新名字 ${project.name}`}
                      value={renameDraft}
                      disabled={savingRename}
                      autoFocus
                      onChange={(event) => setRenameDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.preventDefault()
                          onRenameProject(project.id)
                        }
                        if (event.key === 'Escape') {
                          setRenamingId(null)
                        }
                      }}
                    />
                  </div>
                )
              }
              return (
                <div key={project.id} className="scope-row">
                  <button
                    type="button"
                    className={`scope-item${scopeId === project.id ? ' active' : ''}`}
                    aria-current={scopeId === project.id}
                    onClick={() => setScopeId(project.id)}
                  >
                    <span className="scope-name">{project.name}</span>
                    <span className="scope-count">{project.hotword_count}</span>
                  </button>
                  <span className="scope-actions">
                    <button
                      type="button"
                      className="btn btn-ghost scope-action-btn"
                      aria-label={`重命名项目 ${project.name}`}
                      onClick={() => {
                        setRenameDraft(project.name)
                        setConfirmingDeleteId(null)
                        setRenamingId(project.id)
                      }}
                    >
                      <Icon name="edit" size={11} />
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost scope-action-btn"
                      aria-label={`删除项目 ${project.name}`}
                      onClick={() => {
                        setRenamingId(null)
                        setConfirmingDeleteId(project.id)
                      }}
                    >
                      <Icon name="trash" size={11} />
                    </button>
                  </span>
                </div>
              )
            })}
          </div>

          <div className="scope-new">
            <input
              className="input"
              aria-label="新建项目"
              placeholder="新建项目"
              value={newProjectName}
              disabled={creatingProject}
              onChange={(event) => setNewProjectName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  onCreateProject()
                }
              }}
            />
            <button
              type="button"
              className="btn scope-new-btn"
              disabled={creatingProject || newProjectName.trim() === ''}
              onClick={onCreateProject}
            >
              <Icon name="plus" size={12} />
            </button>
          </div>
        </div>

        <div className="scope-panel">
          <div className="scope-panel-head">
            <h2 className="section-title">{scopeName}</h2>
            <p className="section-desc">
              通用词库对所有会议生效；项目热词只对该项目的会议生效；两者加上本场热词，在转写时叠加使用
            </p>
          </div>

          <div className="card" style={{ marginBottom: 12 }}>
            {/* form-field：label 在上、输入框在下（6px 间距），与新建会议表单一致 */}
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <div className="form-field" style={{ width: 200 }}>
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
              <div className="form-field" style={{ flex: 1, minWidth: 220 }}>
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
                  <div className="empty-title">
                    {scopeId === null ? '词库是空的' : `「${scopeName}」还没有项目热词`}
                  </div>
                  <div>
                    {scopeId === null
                      ? '把常出现的产品名、人名、术语加进来，转写会更认得它们'
                      : '加进来的词只对这个项目的会议生效'}
                  </div>
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
      </div>
    </div>
  )
}
