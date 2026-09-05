import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { useEffect, useRef, useState } from 'react'
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
  moveHotwords,
  renameProject,
  reorderProjects,
  updateHotwordNote,
  updateProjectHotwordNote,
  type Hotword,
  type Project,
} from '../api/client'
import { Icon } from '../components/Icon'
import { toast } from '../components/Toast'

function byWord(a: Hotword, b: Hotword): number {
  return a.word.localeCompare(b.word, 'zh')
}

/** 移动目标：id=null 是通用词库，其余是项目（默认项目不做目标） */
interface MoveTarget {
  id: string | null
  name: string
}

/**
 * 「移动到 ▾」：整批与单条共用同一份目标列表。
 * 用 Radix DropdownMenu（与结果页「更多操作」同一原语），皮肤走本站 .menu。
 */
function MoveMenu({
  targets,
  ariaLabel,
  disabled,
  onPick,
}: {
  targets: MoveTarget[]
  /** 整批是「移动到」，单条是「移动词语 X」，免得两个按钮同名 */
  ariaLabel: string
  disabled: boolean
  onPick: (target: MoveTarget) => void
}) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="btn btn-ghost"
          aria-label={ariaLabel}
          disabled={disabled}
        >
          移动到
          <span aria-hidden="true">▾</span>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="menu" align="end" sideOffset={6}>
          {targets.map((target) => (
            <DropdownMenu.Item asChild key={target.id ?? 'global'}>
              <button
                type="button"
                className="menu-item"
                onClick={() => onPick(target)}
              >
                {target.name}
              </button>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

/**
 * 词库：左栏选范围（通用 / 各项目），右栏是该范围的词条与该项目的重命名 / 删除。
 * 通用词随每场会议快照进入转写；项目词只跟着该项目的会议走；两者与本场热词叠加。
 *
 * projectId 来自 #/hotwords?project=<id>：打开时直接选中它，项目不存在就回到通用。
 */
export function HotwordsPage({
  projectId: initialProjectId = null,
}: {
  projectId?: string | null
}) {
  const [projects, setProjects] = useState<Project[]>([])
  // 当前范围：null = 通用词库，其余是项目 id
  const [scopeId, setScopeId] = useState<string | null>(initialProjectId)
  // 项目列表回来之前不敢信 URL 带来的 id，先不拉它的词
  const [projectsLoaded, setProjectsLoaded] = useState(false)
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
  // 跨层移动：勾选若干条后整批移动，行尾也能单条移动
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [moving, setMoving] = useState(false)
  // 项目维护：左栏新建，右栏头部重命名 / 删除（删除走二次确认）
  const [newProjectName, setNewProjectName] = useState('')
  const [creatingProject, setCreatingProject] = useState(false)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [savingRename, setSavingRename] = useState(false)
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null)
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null)
  // 拖拽排序：draggingId 是被拖的行，dropHint 是插入线画在哪一行的哪一侧
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [dropHint, setDropHint] = useState<{ id: string; side: 'before' | 'after' } | null>(
    null,
  )
  // 排序失败单独提示在左栏，不挤掉右栏的词条错误
  const [reorderError, setReorderError] = useState<string | null>(null)
  // 连按 ⌥↓ 会有多个请求在飞，只认最后一次的回包，免得旧回包把新顺序盖回去
  const reorderSeq = useRef(0)

  // 通用范围随时可拉；项目范围要等项目列表回来，确认这个 id 真的存在
  const scopeReady = scopeId === null || projectsLoaded
  const scope = projects.find((project) => project.id === scopeId) ?? null
  const scopeName = scopeId === null ? '通用' : (scope?.name ?? '项目')
  // 默认项目（General）的热词是叠加出来的：不拉、不改、不删，只给一句说明
  const isDefaultScope = scope?.is_default === true
  const defaultProjectName =
    projects.find((project) => project.is_default)?.name ?? 'General'
  // 能移到哪儿：当前不在通用就可以回通用，加上除当前与默认项目外的所有项目
  const moveTargets: MoveTarget[] = [
    ...(scopeId === null ? [] : [{ id: null, name: '通用词库' }]),
    ...projects
      .filter((project) => !project.is_default && project.id !== scopeId)
      .map((project) => ({ id: project.id, name: project.name })),
  ]
  // 没有别的层可去就别摆多选框，省得勾了没处放
  const canMove = !isDefaultScope && moveTargets.length > 0

  useEffect(() => {
    let stale = false
    listProjects()
      .then((items) => {
        if (!stale) {
          // 后端已按 position 排好序，前端一律直接用返回顺序
          setProjects(items)
          // URL 指名的项目已不存在（或从没存在过）：回到通用，别停在空范围上
          setScopeId((current) =>
            current !== null && !items.some((item) => item.id === current) ? null : current,
          )
          setProjectsLoaded(true)
        }
      })
      .catch((e: unknown) => {
        if (!stale) {
          setError(formatApiError(e))
          setProjectsLoaded(true)
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
    setRenamingId(null)
    setConfirmingDeleteId(null)
    setSelectedIds([])
    // 默认项目不单独维护热词：连列表都不拉，右栏只给说明
    if (!scopeReady || isDefaultScope) {
      return
    }
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
  }, [scopeId, scopeReady, isDefaultScope])

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
        setSelectedIds((current) => current.filter((id) => id !== hotwordId))
        bumpCount(target, -1)
      })
      .catch((e: unknown) => {
        setError(formatApiError(e))
      })
      .finally(() => {
        setDeletingId(null)
      })
  }

  const toggleSelect = (hotwordId: string) => {
    setSelectedIds((current) =>
      current.includes(hotwordId)
        ? current.filter((id) => id !== hotwordId)
        : [...current, hotwordId],
    )
  }

  /**
   * 把选中的词条搬到另一层：成功后本地摘掉这些行，左栏计数按「来源 −全部、目标 +新建」调。
   * merged 的那几条在目标层是并进已有词条，不算新增，所以只加 moved。
   */
  const onMove = (target: MoveTarget, ids: string[]) => {
    if (moving || ids.length === 0) {
      return
    }
    const source = scopeId
    setMoving(true)
    moveHotwords({
      from: { project_id: source },
      to: { project_id: target.id },
      ids,
    })
      .then(({ moved, merged }) => {
        setHotwords((current) =>
          current === null ? current : current.filter((item) => !ids.includes(item.id)),
        )
        setSelectedIds((current) => current.filter((id) => !ids.includes(id)))
        bumpCount(source, -ids.length)
        bumpCount(target.id, moved)
        toast(
          `已移动 ${moved + merged} 个词到「${target.name}」` +
            (merged > 0 ? `，合并 ${merged} 个` : ''),
        )
      })
      .catch((e: unknown) => {
        toast(formatApiError(e), 'error')
      })
      .finally(() => {
        setMoving(false)
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
        // 后端把新项目追加到末尾，前端跟着放最后
        setProjects((current) => [...current, created])
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
          current.map((project) => (project.id === projectId ? updated : project)),
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

  /**
   * 把某个项目挪到 toIndex：先乐观改本地顺序，再把全量 id 顺序 PUT 给后端。
   * 失败就回滚到动之前的顺序，并在左栏给一条错误提示。
   */
  const moveProject = (projectId: string, toIndex: number) => {
    const from = projects.findIndex((project) => project.id === projectId)
    if (from < 0 || toIndex < 0 || toIndex >= projects.length || toIndex === from) {
      return
    }
    const next = [...projects]
    const [moved] = next.splice(from, 1)
    next.splice(toIndex, 0, moved)
    const previous = projects
    setProjects(next)
    setReorderError(null)
    reorderSeq.current += 1
    const seq = reorderSeq.current
    reorderProjects(next.map((project) => project.id))
      .then((items) => {
        if (seq === reorderSeq.current) {
          setProjects(items)
        }
      })
      .catch((e: unknown) => {
        setProjects(previous)
        setReorderError(formatApiError(e))
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
            {/* 「通用」固定第一，不参与排序；留一个和把手同宽的占位让名字对齐 */}
            <div className="scope-row">
              <span className="scope-grip-spacer" aria-hidden="true" />
              <button
                type="button"
                className={`scope-item${scopeId === null ? ' active' : ''}`}
                aria-current={scopeId === null}
                onClick={() => setScopeId(null)}
              >
                <span className="scope-name">通用</span>
              </button>
            </div>

            {projects.map((project, index) => (
              <div
                key={project.id}
                className={[
                  'scope-row',
                  draggingId === project.id ? 'dragging' : '',
                  dropHint !== null && dropHint.id === project.id
                    ? `drop-${dropHint.side}`
                    : '',
                ]
                  .filter((name) => name !== '')
                  .join(' ')}
                draggable
                onDragStart={(event) => {
                  setDraggingId(project.id)
                  const transfer: DataTransfer | undefined = event.dataTransfer
                  if (transfer !== undefined) {
                    transfer.effectAllowed = 'move'
                    transfer.setData('text/plain', project.id)
                  }
                }}
                onDragOver={(event) => {
                  if (draggingId === null || draggingId === project.id) {
                    return
                  }
                  // 只有 preventDefault 过的元素才收得到 drop
                  event.preventDefault()
                  const from = projects.findIndex((item) => item.id === draggingId)
                  setDropHint({ id: project.id, side: from < index ? 'after' : 'before' })
                }}
                onDrop={(event) => {
                  event.preventDefault()
                  const moving = draggingId
                  setDraggingId(null)
                  setDropHint(null)
                  if (moving !== null && moving !== project.id) {
                    moveProject(moving, index)
                  }
                }}
                onDragEnd={() => {
                  setDraggingId(null)
                  setDropHint(null)
                }}
              >
                <button
                  type="button"
                  className="scope-grip"
                  aria-label={`拖动排序 ${project.name}`}
                  title="拖动排序，或按 ⌥↑ / ⌥↓ 上下移动"
                  onKeyDown={(event) => {
                    // 键盘可达的等价操作：⌥↑ / ⌥↓ 各移一位
                    if (!event.altKey) {
                      return
                    }
                    if (event.key === 'ArrowUp') {
                      event.preventDefault()
                      moveProject(project.id, index - 1)
                    }
                    if (event.key === 'ArrowDown') {
                      event.preventDefault()
                      moveProject(project.id, index + 1)
                    }
                  }}
                >
                  <Icon name="grip" size={12} />
                </button>
                <button
                  type="button"
                  className={`scope-item${scopeId === project.id ? ' active' : ''}`}
                  aria-current={scopeId === project.id}
                  onClick={() => setScopeId(project.id)}
                >
                  <span className="scope-name">{project.name}</span>
                  {/* 默认项目的词是叠加出来的，数字没有意义，不摆 */}
                  {!project.is_default && (
                    <span className="scope-count">{project.hotword_count}</span>
                  )}
                </button>
              </div>
            ))}
          </div>

          {reorderError !== null && (
            <div className="notice notice-error scope-error">{reorderError}</div>
          )}

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
            {/* 范围头部：项目名与它的重命名 / 删除常驻同一行，不再靠左栏悬停才浮现 */}
            <div className="scope-head">
              {scope !== null && renamingId === scope.id ? (
                <input
                  className="input scope-head-input"
                  aria-label={`项目新名字 ${scope.name}`}
                  value={renameDraft}
                  disabled={savingRename}
                  autoFocus
                  onChange={(event) => setRenameDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault()
                      onRenameProject(scope.id)
                    }
                    if (event.key === 'Escape') {
                      setRenamingId(null)
                    }
                  }}
                />
              ) : (
                <h2 className="section-title">{scopeName}</h2>
              )}
              {scope !== null && renamingId !== scope.id && (
                <div className="scope-head-actions">
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => {
                      setRenameDraft(scope.name)
                      setConfirmingDeleteId(null)
                      setRenamingId(scope.id)
                    }}
                  >
                    重命名
                  </button>
                  {/* 默认项目不可删（会议要有地方落），改名照旧 */}
                  {!isDefaultScope && (
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => {
                        setRenamingId(null)
                        setConfirmingDeleteId(scope.id)
                      }}
                    >
                      删除
                    </button>
                  )}
                </div>
              )}
            </div>

            {scope !== null && confirmingDeleteId === scope.id && (
              <div className="scope-confirm scope-head-confirm">
                <div className="scope-confirm-text">
                  删除「{scope.name}」？该项目的会议会改挂到 {defaultProjectName}
                  ，项目热词一并删除。
                </div>
                <div className="scope-confirm-actions">
                  <button
                    type="button"
                    className="btn btn-danger"
                    disabled={deletingProjectId === scope.id}
                    onClick={() => onDeleteProject(scope.id)}
                  >
                    确认删除
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={deletingProjectId === scope.id}
                    onClick={() => setConfirmingDeleteId(null)}
                  >
                    取消
                  </button>
                </div>
              </div>
            )}

            <p className="section-desc">
              通用词库对所有会议生效；项目热词只对该项目的会议生效；两者加上本场热词，在转写时叠加使用
            </p>
          </div>

          {/* 默认项目的词是叠加出来的：右栏只留一句说明，不给增删改 */}
          {isDefaultScope && (
            <div className="notice notice-info">
              {`${scopeName} 是默认项目，会自动叠加全局词库和所有项目的热词，不用单独维护`}
            </div>
          )}

          {!isDefaultScope && (
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
          )}

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
                <>
                  {/* 多选表头：只有真有地方可移时才出现 */}
                  {canMove && (
                    <div className="hotword-list-head">
                      <input
                        type="checkbox"
                        className="hotword-check"
                        aria-label="全选"
                        checked={selectedIds.length === hotwords.length}
                        onChange={(event) =>
                          setSelectedIds(
                            event.target.checked
                              ? hotwords.map((item) => item.id)
                              : [],
                          )
                        }
                      />
                      <span>{`${hotwords.length} 个词`}</span>
                    </div>
                  )}
                  {hotwords.map((hotword) => (
                    <div key={hotword.id} className="list-row">
                      {canMove && (
                        <input
                          type="checkbox"
                          className="hotword-check"
                          aria-label={`选择 ${hotword.word}`}
                          checked={selectedIds.includes(hotword.id)}
                          onChange={() => toggleSelect(hotword.id)}
                        />
                      )}
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
                      {canMove && editingId !== hotword.id && (
                        <MoveMenu
                          targets={moveTargets}
                          ariaLabel={`移动词语 ${hotword.word}`}
                          disabled={moving}
                          onPick={(target) => onMove(target, [hotword.id])}
                        />
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
                  ))}
                </>
              )}
            </div>
          )}

          {/* 选了词才出现的吸底操作栏：整批移动 + 清空选择 */}
          {selectedIds.length > 0 && (
            <div className="hotword-bulk-bar">
              <span className="hotword-bulk-count">{`已选 ${selectedIds.length} 个`}</span>
              <MoveMenu
                targets={moveTargets}
                ariaLabel="移动到"
                disabled={moving}
                onPick={(target) =>
                  onMove(
                    target,
                    (hotwords ?? [])
                      .filter((item) => selectedIds.includes(item.id))
                      .map((item) => item.id),
                  )
                }
              />
              <button
                type="button"
                className="btn btn-ghost"
                disabled={moving}
                onClick={() => setSelectedIds([])}
              >
                取消选择
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
