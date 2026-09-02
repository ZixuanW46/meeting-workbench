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
)
