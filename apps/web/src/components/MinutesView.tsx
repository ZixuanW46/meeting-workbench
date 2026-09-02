import {
  Fragment,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  ApiError,
  formatApiError,
  getMinutes,
  retryMinutes,
  type MinutesResult,
} from '../api/client'
import {
  extractDecisions,
  parseMinutes,
  stripIntroHeader,
  type MinutesStructure,
} from '../minutesStructure'
import { Icon } from './Icon'

interface MinutesViewProps {
  meetingId: string
  /** PARTIAL_READY 时为 true：显示失败说明和重试按钮 */
  canRetry: boolean
  onRetried: () => void
}

const DECISIONS_ANCHOR = '__decisions__'
const TIMELINE_TITLE = '议程时间轴'
const FOLLOWUP_TITLE = '后续跟进'
// 时间轴条目「mm:ss-mm:ss 主题」的时间段，拆出来走等宽字体。
const TIMELINE_LEAD = /^(\d+:\d{2}(?::\d{2})?[–—-]\d+:\d{2}(?::\d{2})?)\s+(.*)$/

// 纪要由本机 LLM 产出，构件不可控（粗体、嵌套列表、checkbox、表格都可能
// 出现），交给 react-markdown + GFM 完整渲染，避免把标记符号漏给用户。
function renderMarkdown(markdown: string, timeline = false) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{ li: timeline ? TimelineItem : PointItem }}
    >
      {markdown}
    </ReactMarkdown>
  )
}

function childText(children: ReactNode): string {
  if (typeof children === 'string') {
    return children
  }
  if (Array.isArray(children)) {
    return children.map(childText).join('')
  }
  if (
    children !== null &&
    typeof children === 'object' &&
    'props' in children
  ) {
    return childText((children as { props: { children?: ReactNode } }).props.children)
  }
  return ''
}

function mergeClassName(base: string | undefined, extra: string | false) {
  const merged = [base, extra].filter(Boolean).join(' ')
  return merged === '' ? undefined : merged
}

/** 议题要点：识别「**结论：**」开头的条目，加引导线样式。 */
function PointItem({ children, className, ...props }: ComponentProps<'li'>) {
  const conclusion = childText(children).trimStart().startsWith('结论')
  return (
    <li
      {...props}
      className={mergeClassName(className, conclusion && 'minutes-conclusion')}
    >
      {children}
    </li>
  )
}

/** 时间轴条目：把行首时间段拆成等宽字体列。 */
function TimelineItem({ children, className, ...props }: ComponentProps<'li'>) {
  const text = childText(children)
  const match = TIMELINE_LEAD.exec(text.trim())
  if (match === null) {
    return (
      <li {...props} className={className}>
        {children}
      </li>
    )
  }
  return (
    <li {...props} className={mergeClassName(className, 'minutes-timeline-item')}>
      <span className="minutes-timeline-time">{match[1]}</span>
      <span>{match[2]}</span>
    </li>
  )
}

/** 有至少两个二级议题才值得出目录导航；否则回退单卡整体渲染。 */
function useMinutesStructure(markdown: string | null): MinutesStructure | null {
  return useMemo(() => {
    if (markdown === null) {
      return null
    }
    const structure = parseMinutes(markdown)
    return structure.sections.length >= 2 ? structure : null
  }, [markdown])
}

function StructuredMinutes({ structure }: { structure: MinutesStructure }) {
  const decisions = extractDecisions(structure)
  const sectionRefs = useRef(new Map<string, HTMLElement>())
  // 锚点用序号而不是标题：LLM 偶尔会产出重复的二级标题
  const anchorOf = (index: number) => `section-${index}`
  const [active, setActive] = useState<string>(
    decisions.length > 0 ? DECISIONS_ANCHOR : anchorOf(0),
  )
  // 点击目录后的平滑滚动期间，观察器会连环触发；短暂挂起联动。
  const suspendUntil = useRef(0)

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') {
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (Date.now() < suspendUntil.current) {
          return
        }
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActive(entry.target.getAttribute('data-anchor') ?? '')
            return
          }
        }
      },
      // 视口上缘 1/4 处的段落算「当前」；底部大半排除，避免整屏多段全命中。
      { rootMargin: '0px 0px -70% 0px' },
    )
    for (const element of sectionRefs.current.values()) {
      observer.observe(element)
    }
    return () => observer.disconnect()
  }, [structure])

  const registerSection = (anchor: string) => (element: HTMLElement | null) => {
    if (element === null) {
      sectionRefs.current.delete(anchor)
    } else {
      element.setAttribute('data-anchor', anchor)
      sectionRefs.current.set(anchor, element)
    }
  }

  const jumpTo = (anchor: string) => {
    setActive(anchor)
    suspendUntil.current = Date.now() + 800
    sectionRefs.current
      .get(anchor)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const tocEntry = (anchor: string, label: ReactNode) => (
    <button
      key={anchor}
      type="button"
      className={`minutes-toc-item${active === anchor ? ' active' : ''}`}
      onClick={() => jumpTo(anchor)}
    >
      {label}
    </button>
  )

  return (
    <div className="minutes-layout">
      <nav className="minutes-toc" aria-label="纪要目录">
        <div className="minutes-toc-heading">本场纪要</div>
        {decisions.length > 0 && tocEntry(DECISIONS_ANCHOR, '决议一览')}
        {structure.sections.map((section, index) =>
          tocEntry(
            anchorOf(index),
            section.title === FOLLOWUP_TITLE && section.taskCount > 0 ? (
              <Fragment>
                {section.title}
                <span className="minutes-toc-badge">{section.taskCount}</span>
              </Fragment>
            ) : (
              section.title
            ),
          ),
        )}
      </nav>
      <div className="minutes-body minutes-content">
        {renderMarkdown(stripIntroHeader(structure.intro))}
        {decisions.length > 0 && (
          <section
            ref={registerSection(DECISIONS_ANCHOR)}
            className="minutes-decisions"
          >
            <div className="minutes-decisions-title">本场决议一览</div>
            {decisions.map((decision, index) => (
              <div key={`${decision.sectionIndex}-${index}`} className="minutes-decision-row">
                <span className="minutes-decision-index">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <span>
                  <button
                    type="button"
                    className="minutes-decision-link"
                    onClick={() => jumpTo(anchorOf(decision.sectionIndex))}
                  >
                    {decision.section}
                  </button>
                  ：{decision.text}
                </span>
              </div>
            ))}
          </section>
        )}
        {structure.sections.map((section, index) => (
          <section
            key={anchorOf(index)}
            ref={registerSection(anchorOf(index))}
            className="minutes-section"
          >
            <h2>{section.title}</h2>
            {renderMarkdown(section.body, section.title === TIMELINE_TITLE)}
          </section>
        ))}
      </div>
    </div>
  )
}

export function MinutesView({ meetingId, canRetry, onRetried }: MinutesViewProps) {
  const [minutes, setMinutes] = useState<MinutesResult | null>(null)
  const [notReady, setNotReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)

  useEffect(() => {
    let stale = false
    getMinutes(meetingId)
      .then((result) => {
        if (!stale) {
          setMinutes(result)
        }
      })
      .catch((e: unknown) => {
        if (stale) {
          return
        }
        if (e instanceof ApiError && e.status === 409) {
          setNotReady(true)
        } else {
          setError(formatApiError(e))
        }
      })
    return () => {
      stale = true
    }
  }, [meetingId])

  const structure = useMinutesStructure(minutes?.markdown ?? null)

  const handleRetry = async () => {
    setRetrying(true)
    setError(null)
    try {
      await retryMinutes(meetingId)
      onRetried()
    } catch (e: unknown) {
      setError(formatApiError(e))
    } finally {
      setRetrying(false)
    }
  }

  return (
    <Fragment>
      {canRetry && (
        <div className="notice notice-warn" style={{ marginBottom: 12 }}>
          <span>纪要生成失败（转写不受影响，仍可导出）。</span>
          <button
            type="button"
            className="btn"
            disabled={retrying}
            onClick={() => {
              void handleRetry()
            }}
          >
            <Icon name="refresh" size={12} />
            重试生成纪要
          </button>
        </div>
      )}
      {error !== null && <div className="notice notice-error">{error}</div>}
      {minutes !== null &&
        (structure !== null ? (
          <StructuredMinutes structure={structure} />
        ) : (
          <div className="card minutes-body">{renderMarkdown(minutes.markdown)}</div>
        ))}
      {minutes === null && notReady && !canRetry && (
        <p className="section-desc">纪要尚未生成</p>
      )}
    </Fragment>
  )
}
