import { useEffect, useState } from 'react'
import { getAuditLogs } from './api.js'

const PAGE_SIZE = 25
const ACTIONS = [
  'login',
  'records.list',
  'records.read',
  'records.create',
  'records.update',
  'files.upload',
  'files.download',
  'backup.create',
  'backup.restore',
]
const OUTCOMES = ['success', 'failure', 'denied', 'denied_or_not_found', 'integrity_failure']
const OUTCOME_NAMES = {
  success: 'Thành công',
  failure: 'Thất bại',
  denied: 'Bị từ chối',
  denied_or_not_found: 'Bị từ chối / Không tìm thấy',
  integrity_failure: 'Lỗi toàn vẹn',
}

function formatDate(value) {
  return new Intl.DateTimeFormat('vi-VN', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

export default function AuditPage({ token }) {
  const [page, setPage] = useState({ items: [], total: 0 })
  const [offset, setOffset] = useState(0)
  const [action, setAction] = useState('')
  const [outcome, setOutcome] = useState('')
  const [reloadId, setReloadId] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    getAuditLogs(token, { limit: PAGE_SIZE, offset, action, outcome })
      .then((result) => { if (!cancelled) setPage(result) })
      .catch((err) => { if (!cancelled) setError(err.message || 'Không thể tải nhật ký truy cập.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [token, offset, action, outcome, reloadId])

  function changeFilter(setter, value) {
    setter(value)
    setOffset(0)
  }

  return <section className="feature-page">
    <div className="welcome-row"><div><div className="eyebrow"><span className="live-dot" /> THEO DÕI HOẠT ĐỘNG</div><h1>Nhật ký truy cập</h1><p className="page-intro">Lịch sử thao tác được ghi nhận bởi hệ thống.</p></div><button className="refresh-button" onClick={() => setReloadId((current) => current + 1)} title="Làm mới nhật ký">↻ <span>Làm mới</span></button></div>
    <section className="records-panel">
      <div className="panel-heading"><div><div className="section-kicker">KIỂM TOÁN</div><h2>Lịch sử hoạt động <span className="heading-count">{page.total}</span></h2><p>Thông tin người thao tác, tài nguyên và kết quả.</p></div></div>
      <div className="toolbar"><div className="filters audit-filters"><select value={action} onChange={(event) => changeFilter(setAction, event.target.value)} aria-label="Lọc thao tác"><option value="">Mọi thao tác</option>{ACTIONS.map((item) => <option value={item} key={item}>{item}</option>)}</select><select value={outcome} onChange={(event) => changeFilter(setOutcome, event.target.value)} aria-label="Lọc kết quả"><option value="">Mọi kết quả</option>{OUTCOMES.map((item) => <option value={item} key={item}>{OUTCOME_NAMES[item]}</option>)}</select></div><span className="filter-summary">{loading ? 'Đang tải…' : `${page.items.length} mục trên trang`}</span></div>
      {error && <div className="inline-error" role="alert">{error}<button onClick={() => setReloadId((current) => current + 1)} aria-label="Thử lại">↻</button></div>}
      <div className="table-wrap"><table className="audit-table"><thead><tr><th>THỜI GIAN</th><th>NGƯỜI DÙNG</th><th>THAO TÁC</th><th>TÀI NGUYÊN</th><th>KẾT QUẢ</th><th>ĐỊA CHỈ IP</th></tr></thead>
        <tbody>{page.items.map((item) => <tr key={item.id}>
          <td className="date-cell">{formatDate(item.created_at)}</td>
          <td><strong className="audit-actor">{item.actor_username || 'Tài khoản đã xóa'}</strong><small className="audit-sub">ID {item.actor_user_id ?? '—'}</small></td>
          <td><code className="action-code">{item.action}</code></td>
          <td><span className="audit-resource">{item.resource_type}{item.resource_id ? ` · ${item.resource_id}` : ''}</span></td>
          <td><span className={`status-pill ${item.outcome === 'success' ? 'status-active' : 'status-archived'}`}><span />{OUTCOME_NAMES[item.outcome] || item.outcome}</span></td>
          <td className="date-cell">{item.ip_address || '—'}</td>
        </tr>)}</tbody></table>
        {!loading && page.items.length === 0 && <div className="empty-state"><span>◷</span><strong>Chưa có hoạt động phù hợp</strong><p>Thử chọn bộ lọc khác hoặc kiểm tra lại sau.</p></div>}
        {loading && <div className="loading-state">Đang tải nhật ký…</div>}
      </div>
      <div className="table-footer"><span>Hiển thị {page.items.length} / {page.total}</span><div className="pagination-actions"><button className="secondary-button" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>← Trước</button><span>Trang {Math.floor(offset / PAGE_SIZE) + 1}</span><button className="secondary-button" disabled={offset + PAGE_SIZE >= page.total || loading} onClick={() => setOffset(offset + PAGE_SIZE)}>Tiếp →</button></div></div>
    </section>
    <p className="hint-text page-hint">Nhật ký chỉ đọc. Chi tiết nhạy cảm không được hiển thị trong trang này.</p>
  </section>
}
