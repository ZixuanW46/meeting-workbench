import { useEffect, useState } from 'react'
import { Icon } from './components/Icon'
import { HotwordsPage } from './pages/HotwordsPage'
import { MeetingListPage } from './pages/MeetingListPage'
import { NewMeetingPage } from './pages/NewMeetingPage'
import { VoiceprintsPage } from './pages/VoiceprintsPage'
import { WorkbenchPage } from './pages/WorkbenchPage'

// 极简 hash 路由：#/ 列表、#/new 新建、#/meetings/{id} 工作台、
// #/voiceprints 声纹库、#/hotwords 词库
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
  const meetingMatch = /^\/meetings\/([^/]+)$/.exec(route)

  let page = <MeetingListPage />
  if (route === '/new') {
    page = <NewMeetingPage />
  } else if (route === '/voiceprints') {
    page = <VoiceprintsPage />
  } else if (route === '/hotwords') {
    page = <HotwordsPage />
  } else if (meetingMatch !== null) {
    page = <WorkbenchPage key={meetingMatch[1]} meetingId={meetingMatch[1]} />
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-brand">会议工作台</div>
        <nav className="sidebar-nav">
          <a
            href="#/"
            className={
              meetingMatch === null &&
              route !== '/new' &&
              route !== '/voiceprints' &&
              route !== '/hotwords'
                ? 'active'
                : ''
            }
          >
            <Icon name="meetings" />
            会议
          </a>
          <a href="#/voiceprints" className={route === '/voiceprints' ? 'active' : ''}>
            <Icon name="voiceprints" />
            声纹库
          </a>
          <a href="#/hotwords" className={route === '/hotwords' ? 'active' : ''}>
            <Icon name="hotwords" />
            词库
          </a>
        </nav>
        <div className="sidebar-foot">
          音频与转写全程本机处理
          <br />
          仅纪要文本经本机 CLI 调用云端
        </div>
      </aside>
      <main className="main">{page}</main>
    </div>
  )
}
