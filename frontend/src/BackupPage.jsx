import { useCallback, useEffect, useState } from 'react'
import { createBackup, getBackupJobs, restoreBackup } from './api.js'

const PAGE_SIZE = 25

function formatDate(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('vi-VN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function formatBytes(value) {
  if (value == null) return '—'
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} KB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}

function jobName(type) {
  if (type === 'backup') return 'Sao lưu thủ công'
  if (type === 'safety_backup') return 'Bản an toàn trước khôi phục'
  return 'Khôi phục'
}

function statusName(status) {
  if (status === 'success') return 'Hoàn tất'
  if (status === 'running') return 'Đang xử lý'
  return 'Thất bại'
}

export default function BackupPage({ token, permissions, onError }) {
  const [page, setPage] = useState({ items: [], total: 0 })
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [restoreTarget, setRestoreTarget] = useState(null)
  const [restoreQuarantine, setRestoreQuarantine] = useState(false)
  const [restoreApplicationLogs, setRestoreApplicationLogs] = useState(false)
  const canCreate = permissions.includes('backup:execute')
  const canRestore = permissions.includes('restore:execute')

  const loadJobs = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setPage(await getBackupJobs(token, PAGE_SIZE, offset))
    } catch (err) {
      setError(err.message || 'Không thể tải danh sách bản sao lưu.')
    } finally {
      setLoading(false)
    }
  }, [token, offset])

  useEffect(() => { loadJobs() }, [loadJobs])

  async function runCreateBackup() {
    setCreating(true)
    setNotice('')
    onError('')
    try {
      const result = await createBackup(token)
      if (result.status === 'success') setNotice('Đã tạo bản sao lưu database và tệp y tế.')
      await loadJobs()
      if (result.status !== 'success') setError(result.message || 'Tạo bản sao lưu thất bại.')
    } catch (err) {
      onError(err.message || 'Không thể tạo bản sao lưu.')
    } finally {
      setCreating(false)
    }
  }

  async function confirmRestore() {
    if (!restoreTarget) return
    setRestoring(true)
    setNotice('')
    setError('')
    onError('')
    try {
      const result = await restoreBackup(token, restoreTarget.id, {
        restoreQuarantine,
        restoreApplicationLogs,
      })
      if (result.status === 'success') setNotice(result.message || 'Đã khôi phục database và thư mục tệp.')
      setRestoreTarget(null)
      setOffset(0)
      await loadJobs()
      if (result.status !== 'success') setError(result.message || 'Khôi phục thất bại.')
    } catch (err) {
      onError(err.message || 'Không thể khôi phục bản sao lưu.')
    } finally {
      setRestoring(false)
    }
  }

  return <section className="feature-page">
    <div className="welcome-row"><div><div className="eyebrow"><span className="live-dot" /> BẢO VỆ VÀ PHỤC HỒI DỮ LIỆU</div><h1>Sao lưu & khôi phục</h1><p className="page-intro">Quản lý bản sao của database và kho tệp y tế.</p></div>{canCreate && <button className="primary-button" onClick={runCreateBackup} disabled={creating || restoring}>{creating ? 'Đang tạo bản sao…' : '＋ Tạo bản sao lưu'}</button>}</div>
    <div className="backup-notice"><span>♢</span><p>Bản sao lưu gồm database MySQL và tệp tại thư mục storage. Khôi phục sẽ thay dữ liệu hiện tại; hệ thống tạo một bản an toàn trước đó.</p></div>
    {notice && <div className="success-banner" role="status">✓ {notice}</div>}
    {error && <div className="alert error-alert" role="alert"><span>!</span>{error}<button onClick={() => setError('')} aria-label="Đóng">×</button></div>}
    <section className="records-panel">
      <div className="panel-heading"><div><div className="section-kicker">LỊCH SỬ CÔNG VIỆC</div><h2>Bản sao lưu gần đây <span className="heading-count">{page.total}</span></h2><p>Checksum giúp kiểm tra archive trước khi khôi phục.</p></div><button className="refresh-button" onClick={loadJobs} disabled={loading}>↻ <span>Làm mới</span></button></div>
      <div className="table-wrap"><table className="backup-table"><thead><tr><th>THỜI GIAN</th><th>LOẠI TÁC VỤ</th><th>TRẠNG THÁI</th><th>DUNG LƯỢNG</th><th>CHECKSUM SHA-256</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
        <tbody>{page.items.map((job) => <tr key={job.id}>
          <td className="date-cell">{formatDate(job.created_at)}</td>
          <td><div className="backup-kind"><span className="backup-icon">{job.job_type === 'restore' ? '↶' : '▧'}</span><span><strong>{jobName(job.job_type)}</strong><small>{job.destination || `Tác vụ #${job.id}`}</small></span></div></td>
          <td><span className={`status-pill ${job.status === 'success' ? 'status-active' : 'status-archived'}`}><span />{statusName(job.status)}</span>{job.message && job.status === 'failed' && <small className="job-error">{job.message}</small>}</td>
          <td className="date-cell">{formatBytes(job.bytes_total)}</td>
          <td><code className="checksum-code" title={job.checksum || ''}>{job.checksum ? `${job.checksum.slice(0, 12)}…${job.checksum.slice(-8)}` : '—'}</code></td>
          <td>{canRestore && job.archive_available && ['backup', 'safety_backup'].includes(job.job_type) && <button className="secondary-button restore-button" disabled={creating || restoring} onClick={() => { setRestoreQuarantine(false); setRestoreApplicationLogs(false); setRestoreTarget(job) }}>Khôi phục</button>}</td>
        </tr>)}</tbody></table>
        {!loading && page.items.length === 0 && <div className="empty-state"><span>▧</span><strong>Chưa có bản sao lưu</strong><p>{canCreate ? 'Tạo bản sao đầu tiên để bảo vệ database và tệp y tế.' : 'Bản sao lưu sẽ xuất hiện ở đây khi được tạo.'}</p></div>}
        {loading && <div className="loading-state">Đang tải lịch sử sao lưu…</div>}
      </div>
      <div className="table-footer"><span>Hiển thị {page.items.length} / {page.total}</span><div className="pagination-actions"><button className="secondary-button" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>← Trước</button><span>Trang {Math.floor(offset / PAGE_SIZE) + 1}</span><button className="secondary-button" disabled={offset + PAGE_SIZE >= page.total || loading} onClick={() => setOffset(offset + PAGE_SIZE)}>Tiếp →</button></div></div>
    </section>
    <p className="hint-text page-hint">Bản sao được giữ trên máy chủ trong <code>D:\HospitalBackups</code>. Không xóa hoặc sửa file ZIP thủ công.</p>

    {restoreTarget && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !restoring) setRestoreTarget(null) }}><section className="record-modal confirm-modal" role="dialog" aria-modal="true" aria-labelledby="restore-title">
      <div className="modal-header"><div><div className="section-kicker">XÁC NHẬN KHÔI PHỤC</div><h2 id="restore-title">Thay thế dữ liệu hiện tại?</h2><p>Bản sao #{restoreTarget.id} · {formatDate(restoreTarget.created_at)}</p></div><button className="modal-close" disabled={restoring} onClick={() => setRestoreTarget(null)} aria-label="Đóng">×</button></div>
      <div className="restore-warning"><strong>Database và 5 thư mục khoa sẽ được thay thế.</strong><p>Hệ thống tạo safety backup trước. Backup\Incoming, Backup\Repository, RestoreTest và các thư mục khác được giữ nguyên.</p></div>
      <fieldset className="optional-restore"><legend>Khôi phục riêng (không ghi đè dữ liệu hiện có)</legend>
        <label><input type="checkbox" checked={restoreQuarantine} onChange={(event) => setRestoreQuarantine(event.target.checked)} disabled={restoring} /> <span><strong>Quarantine</strong><small>Chép vào thư mục Quarantine\RestoredFromBackup riêng cho lần khôi phục này.</small></span></label>
        <label><input type="checkbox" checked={restoreApplicationLogs} onChange={(event) => setRestoreApplicationLogs(event.target.checked)} disabled={restoring} /> <span><strong>System\ApplicationLogs</strong><small>Chép vào thư mục ApplicationLogs\RestoredFromBackup riêng cho lần khôi phục này.</small></span></label>
      </fieldset>
      <div className="modal-actions"><button className="secondary-button" disabled={restoring} onClick={() => setRestoreTarget(null)}>Hủy</button><button className="danger-button" disabled={restoring} onClick={confirmRestore}>{restoring ? 'Đang khôi phục…' : 'Xác nhận khôi phục'}</button></div>
    </section></div>}
  </section>
}
