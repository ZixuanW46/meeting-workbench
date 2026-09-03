import { useEffect, useState } from 'react'
import { CommandPalette } from './components/CommandPalette'
import { Icon } from './components/Icon'
import { Toaster } from './components/Toast'
import { HotwordsPage } from './pages/HotwordsPage'
import { MeetingListPage } from './pages/MeetingListPage'
import { NewMeetingPage } from './pages/NewMeetingPage'
import { VoiceprintsPage } from './pages/VoiceprintsPage'
import { WorkbenchPage } from './pages/WorkbenchPage'

// 极简 hash 路由：#/ 列表、#/new 新建、#/meetings/{id} 工作台、
// #/voiceprints 声纹库、#/hotwords 词库（可带 ?project=<id> 直达某项目）
function useHashRoute(): string {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash.replace(/^#/, '') || '/'
}

export default function App() {
  const route = useHashRoute()
  // 路由可以带查询串（如 #/hotwords?project=p1）：路径与参数分开解析，路径匹配照旧
  const queryAt = route.indexOf('?')
  const path = queryAt === -1 ? route : route.slice(0, queryAt)
  const params = new URLSearchParams(queryAt === -1 ? '' : route.slice(queryAt + 1))
  const meetingMatch = /^\/meetings\/([^/]+)$/.exec(path)
  const [paletteOpen, setPaletteOpen] = useState(false)

  // Linear 惯例：⌘K / Ctrl+K 呼出命令面板
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const hotwordsProject = params.get('project')
  let page = <MeetingListPage />
  if (path === '/new') {
    page = <NewMeetingPage />
  } else if (path === '/voiceprints') {
    page = <VoiceprintsPage />
  } else if (path === '/hotwords') {
    // key 让 ?project= 换值时重新挂载，初始范围跟着 URL 走
    page = <HotwordsPage key={hotwordsProject ?? '-'} projectId={hotwordsProject} />
  } else if (meetingMatch !== null) {
    page = <WorkbenchPage key={meetingMatch[1]} meetingId={meetingMatch[1]} />
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-brand">会议工作台</div>
        <button
          type="button"
          className="sidebar-search"
          onClick={() => setPaletteOpen(true)}
        >
          <Icon name="search" size={13} />
          搜索
          <kbd className="kbd">⌘K</kbd>
        </button>
        <nav className="sidebar-nav">
          <a
            href="#/"
            className={
              meetingMatch === null &&
              path !== '/new' &&
              path !== '/voiceprints' &&
              path !== '/hotwords'
                ? 'active'
                : ''
            }
          >
            <Icon name="meetings" />
            会议
          </a>
          <a href="#/voiceprints" className={path === '/voiceprints' ? 'active' : ''}>
            <Icon name="voiceprints" />
            声纹库
          </a>
          <a href="#/hotwords" className={path === '/hotwords' ? 'active' : ''}>
            <Icon name="hotwords" />
            词库
          </a>
        </nav>
      </aside>
      <main className="main">{page}</main>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <Toaster />
    </div>
  )
}
