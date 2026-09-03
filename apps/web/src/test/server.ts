import { HttpResponse, http } from 'msw'
import { setupServer } from 'msw/node'
import { makeDoctorReport } from './doctor'

// 各测试文件通过 server.use(...) 注册自己的 handler。
// doctor 默认全就绪：页面测试无需关心就绪横幅即可保持绿。
export const server = setupServer(
  http.get('/api/doctor', () => HttpResponse.json(makeDoctorReport())),
  // 波形峰值默认为空：确认页测试不关心波形，只关心决定与试听逻辑
  http.get('/api/meetings/:id/peaks', () =>
    HttpResponse.json({ duration: 0, peaks: [] }),
  ),
  // 项目默认为空：不关心项目的页面测试不必自己注册 handler
  http.get('/api/projects', () => HttpResponse.json({ items: [] })),
)

/** 项目 fixture：词库页 / 会议列表 / 新建会议 / 工作台测试共用同一批项目 */
export const PROJECTS = [
  {
    id: 'p1',
    name: '会议工作台',
    created_at: '2026-08-20T08:00:00Z',
    meeting_count: 3,
    hotword_count: 2,
  },
  {
    id: 'p2',
    name: '声纹研究',
    created_at: '2026-08-22T08:00:00Z',
    meeting_count: 1,
    hotword_count: 0,
  },
]

/** 注册一批项目：等价于 server.use(GET /api/projects → items) */
export function useProjects(items: unknown[] = PROJECTS) {
  server.use(http.get('/api/projects', () => HttpResponse.json({ items })))
}
