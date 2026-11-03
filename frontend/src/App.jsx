import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ApiError,
  createRecord,
  downloadFile,
  getMe,
  getRecords,
  login,
  updateRecord,
  uploadFile,
} from './api.js'

const TOKEN_KEY = 'hospital_access_token'
const DEPARTMENTS = ['Clinical', 'Laboratory', 'Imaging', 'Administration', 'HR']
const DEPARTMENT_NAMES = {
  Clinical: 'Khoa lâm sàng',
  Laboratory: 'Xét nghiệm',
  Imaging: 'Chẩn đoán hình ảnh',
  Administration: 'Hành chính',
  HR: 'Nhân sự',
}
const ROLE_NAMES = {
  system_admin: 'Quản trị hệ thống',
  doctor: 'Bác sĩ',
  nurse: 'Điều dưỡng',
  lab_staff: 'Nhân viên xét nghiệm',
  admin_staff: 'Nhân viên hành chính',
  backup_operator: 'Nhân viên sao lưu',
  restore_operator: 'Nhân viên khôi phục',
}

function formatDate(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('vi-VN', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(value))
}

function initials(name = '') {
  return name.trim().split(/\s+/).slice(-2).map((part) => part[0]).join('').toUpperCase() || 'NV'
}

function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) || '')
  const [user, setUser] = useState(null)
  const [records, setRecords] = useState([])
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(Boolean(sessionStorage.getItem(TOKEN_KEY)))
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [departmentFilter, setDepartmentFilter] = useState('all')
  const [modal, setModal] = useState(null)
  const [saving, setSaving] = useState(false)
  const [uploads, setUploads] = useState([])
  const [uploadingId, setUploadingId] = useState(null)
  const [mobileNav, setMobileNav] = useState(false)

  const can = (permission) => user?.permissions?.includes(permission) || false
  const isSystemAdmin = user?.roles?.includes('system_admin') || false

  const clearSession = useCallback(() => {
    sessionStorage.removeItem(TOKEN_KEY)
    setToken('')
    setUser(null)
    setRecords([])
    setUploads([])
  }, [])

  const loadRecords = useCallback(async (activeToken, reset = true) => {
    const pageOffset = reset ? 0 : offset + 50
    const result = await getRecords(activeToken, pageOffset, 50)
    setRecords((current) => reset ? result : [...current, ...result])
    setOffset(pageOffset)
    setHasMore(result.length === 50)
  }, [offset])

  useEffect(() => {
    if (!token) {
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    getMe(token)
      .then(async (profile) => {
        if (cancelled) return
        setUser(profile)
        try {
          const items = await getRecords(token, 0, 50)
          if (cancelled) return
          setRecords(items)
          setOffset(0)
          setHasMore(items.length === 50)
        } catch (err) {
          if (cancelled) return
          if (err instanceof ApiError && err.status === 403) {
            setError('Tài khoản của bạn chưa được cấp quyền xem hồ sơ bệnh án.')
          } else {
            throw err
          }
        }
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 401) clearSession()
        else setError(err.message || 'Không thể kết nối máy chủ.')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [token, clearSession])

  const visibleRecords = useMemo(() => {
    const search = query.trim().toLocaleLowerCase('vi')
    return records.filter((record) => {
      const matchesText = !search || [record.record_number, record.patient_code, record.title, record.department]
        .some((value) => String(value || '').toLocaleLowerCase('vi').includes(search))
      const matchesStatus = statusFilter === 'all' || record.status === statusFilter
      const matchesDepartment = departmentFilter === 'all' || record.department === departmentFilter
      return matchesText && matchesStatus && matchesDepartment
    })
  }, [records, query, statusFilter, departmentFilter])

  async function handleLogin(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setSaving(true)
    setError('')
    try {
      const result = await login(String(form.get('username')).trim(), String(form.get('password')))
      sessionStorage.setItem(TOKEN_KEY, result.access_token)
      setToken(result.access_token)
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? 'Tên đăng nhập hoặc mật khẩu chưa đúng.' : err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleSaveRecord(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const existing = modal?.record
    const payload = existing
      ? { title: String(form.get('title')).trim(), status: String(form.get('status')) }
      : {
          record_number: String(form.get('record_number')).trim(),
          patient_code: String(form.get('patient_code')).trim(),
          title: String(form.get('title')).trim(),
          department: String(form.get('department')),
        }
    setSaving(true)
    setError('')
    try {
      const saved = existing
        ? await updateRecord(token, existing.id, payload)
        : await createRecord(token, payload)
      setRecords((current) => existing
        ? current.map((record) => record.id === saved.id ? saved : record)
        : [saved, ...current])
      setNotice(existing ? 'Đã cập nhật hồ sơ.' : 'Đã tạo hồ sơ mới.')
      setModal(null)
    } catch (err) {
      setError(err instanceof ApiError && err.status === 409 ? 'Mã hồ sơ đã tồn tại.' : err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleUpload(record, file) {
    if (!file) return
    if (file.size > 10 * 1024 * 1024) {
      setError('Tệp vượt quá giới hạn 10 MB.')
      return
    }
    setUploadingId(record.id)
    setError('')
    try {
      const uploaded = await uploadFile(token, record.id, file)
      setUploads((current) => [{ ...uploaded, record_number: record.record_number }, ...current])
      setNotice(`Đã tải lên ${uploaded.original_filename}.`)
    } catch (err) {
      setError(err.message || 'Không thể tải tệp lên.')
    } finally {
      setUploadingId(null)
    }
  }

  async function handleDownload(file) {
    try {
      const response = await downloadFile(token, file.id)
      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = objectUrl
      anchor.download = file.original_filename || `tep-${file.id}`
      anchor.click()
      URL.revokeObjectURL(objectUrl)
    } catch (err) {
      setError(err.message || 'Không thể tải tệp xuống.')
    }
  }

  useEffect(() => {
    if (!notice) return undefined
    const timer = window.setTimeout(() => setNotice(''), 3600)
    return () => window.clearTimeout(timer)
  }, [notice])

  if (!token || (!user && !loading && !error)) return <LoginScreen onSubmit={handleLogin} saving={saving} error={error} />
  if (loading && !user) return <div className="boot-screen"><span className="brand-mark">✚</span><span>Đang kết nối dữ liệu bệnh viện…</span></div>
  if (!user) return <LoginScreen onSubmit={handleLogin} saving={saving} error={error} />

  const filteredDepartmentOptions = isSystemAdmin ? DEPARTMENTS : (user.department ? [user.department] : [])
  const activeCount = records.filter((record) => record.status === 'active').length
  const archivedCount = records.filter((record) => record.status === 'archived').length

  return (
    <div className="app-shell">
      {mobileNav && <button className="mobile-scrim" aria-label="Đóng menu" onClick={() => setMobileNav(false)} />}
      <aside className={`sidebar ${mobileNav ? 'sidebar-open' : ''}`}>
        <a className="brand" href="#home" onClick={() => setMobileNav(false)}>
          <span className="brand-mark">✚</span>
          <span className="brand-copy"><strong>MedVault</strong><small>HOSPITAL WORKSPACE</small></span>
        </a>
        <div className="side-section-label">KHÔNG GIAN LÀM VIỆC</div>
        <nav className="side-nav" aria-label="Điều hướng chính">
          <a className="nav-item active" href="#records" onClick={() => setMobileNav(false)}><span className="nav-icon">▦</span>Tổng quan</a>
          <a className="nav-item" href="#records" onClick={() => setMobileNav(false)}><span className="nav-icon">▤</span>Hồ sơ bệnh án<span className="nav-count">{records.length}</span></a>
          <div className="nav-item muted" title="Tính năng chưa có API"><span className="nav-icon">◷</span>Nhật ký truy cập<span className="nav-soon">SẮP CÓ</span></div>
          <div className="nav-item muted" title="Tính năng chưa có API"><span className="nav-icon">⟳</span>Sao lưu & khôi phục<span className="nav-soon">SẮP CÓ</span></div>
        </nav>
        <div className="sidebar-spacer" />
        <div className="security-card"><span className="security-icon">♢</span><div><strong>Dữ liệu được bảo vệ</strong><p>Quyền truy cập theo khoa và vai trò.</p></div><span className="secure-dot" /></div>
        <button className="profile-card" onClick={clearSession} title="Đăng xuất">
          <span className="avatar">{initials(user.full_name)}</span>
          <span className="profile-copy"><strong>{user.full_name}</strong><small>{ROLE_NAMES[user.roles?.[0]] || 'Nhân viên'}</small></span>
          <span className="logout-icon">↪</span>
        </button>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <button className="mobile-menu" onClick={() => setMobileNav(true)} aria-label="Mở menu">☰</button>
          <div className="breadcrumb"><span>Không gian làm việc</span><b>/</b><strong>Hồ sơ bệnh án</strong></div>
          <div className="topbar-right"><span className="today-label">{new Intl.DateTimeFormat('vi-VN', { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date())}</span><span className="topbar-avatar">{initials(user.full_name)}</span></div>
        </header>

        <div className="page-content" id="records">
          <section className="welcome-row">
            <div><div className="eyebrow"><span className="live-dot" /> CỔNG HỒ SƠ Y TẾ AN TOÀN</div><h1>Chào buổi sáng, {user.full_name.split(' ').slice(-1)[0]}</h1><p className="page-intro">Theo dõi và quản lý hồ sơ trong phạm vi được cấp quyền.</p></div>
            {can('records:create') && <button className="primary-button" onClick={() => { setError(''); setModal({ type: 'create' }) }}><span>＋</span> Tạo hồ sơ mới</button>}
          </section>

          {error && <div className="alert error-alert" role="alert"><span>!</span>{error}<button onClick={() => setError('')} aria-label="Đóng">×</button></div>}
          {notice && <div className="toast" role="status"><span>✓</span>{notice}</div>}

          <section className="stats-grid" aria-label="Thống kê hồ sơ">
            <StatCard label="Hồ sơ trong danh sách" value={records.length} icon="▤" tone="blue" caption={isSystemAdmin ? 'Tổng quan mọi khoa' : `Phạm vi ${DEPARTMENT_NAMES[user.department] || user.department || 'được cấp'}`} />
            <StatCard label="Đang hoạt động" value={activeCount} icon="◉" tone="green" caption="Sẵn sàng tra cứu" />
            <StatCard label="Đã lưu trữ" value={archivedCount} icon="▣" tone="violet" caption="Được giữ an toàn" />
            <StatCard label="Tệp vừa tải lên" value={uploads.length} icon="↥" tone="amber" caption="Trong phiên làm việc này" />
          </section>

          <section className="records-panel">
            <div className="panel-heading"><div><div className="section-kicker">DANH MỤC</div><h2>Hồ sơ gần đây <span className="heading-count">{records.length}</span></h2><p>Các hồ sơ mới nhất bạn được phép xem.</p></div><button className="refresh-button" onClick={() => loadRecords(token).catch((err) => setError(err.message))} title="Làm mới danh sách">↻ <span>Làm mới</span></button></div>
            <div className="toolbar">
              <label className="search-box"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm mã hồ sơ, bệnh nhân…" aria-label="Tìm hồ sơ" /><kbd>⌘ K</kbd></label>
              <div className="filters">
                {isSystemAdmin && <select value={departmentFilter} onChange={(event) => setDepartmentFilter(event.target.value)} aria-label="Lọc theo khoa"><option value="all">Tất cả khoa</option>{DEPARTMENTS.map((department) => <option value={department} key={department}>{DEPARTMENT_NAMES[department]}</option>)}</select>}
                <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="Lọc theo trạng thái"><option value="all">Mọi trạng thái</option><option value="active">Đang hoạt động</option><option value="archived">Đã lưu trữ</option></select>
              </div>
            </div>
            <div className="table-wrap"><table><thead><tr><th>MÃ HỒ SƠ</th><th>THÔNG TIN</th><th>KHOA</th><th>NGÀY TẠO</th><th>TRẠNG THÁI</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
              <tbody>{visibleRecords.map((record, index) => <tr key={record.id} style={{ '--row-index': index }}>
                <td><span className="record-code"><span className="file-icon">▤</span>{record.record_number}</span></td>
                <td><div className="patient-cell"><strong>{record.title}</strong><small>Mã bệnh nhân · {record.patient_code}</small></div></td>
                <td><span className="department-pill">{DEPARTMENT_NAMES[record.department] || record.department}</span></td>
                <td className="date-cell">{formatDate(record.created_at)}</td>
                <td><span className={`status-pill ${record.status === 'active' ? 'status-active' : 'status-archived'}`}><span />{record.status === 'active' ? 'Hoạt động' : 'Lưu trữ'}</span></td>
                <td><div className="row-actions">
                  {can('files:upload') && <label className={`icon-button upload-button ${uploadingId === record.id ? 'is-busy' : ''}`} title="Tải tệp lên" aria-label="Tải tệp lên">{uploadingId === record.id ? '…' : '↥'}<input type="file" accept=".pdf,.png,.jpg,.jpeg,.txt,.csv" disabled={uploadingId === record.id} onChange={(event) => { handleUpload(record, event.target.files?.[0]); event.target.value = '' }} /></label>}
                  {can('records:update') && <button className="icon-button" title="Chỉnh sửa hồ sơ" onClick={() => { setError(''); setModal({ type: 'edit', record }) }}>✎</button>}
                  {can('files:download') && uploads.filter((file) => file.record_id === record.id).map((file) => <button className="icon-button download-action" key={file.id} title={`Tải ${file.original_filename} xuống`} onClick={() => handleDownload(file)}>↓</button>)}
                  {!can('records:update') && !can('files:upload') && <span className="read-only">Chỉ xem</span>}
                </div></td>
              </tr>)}</tbody></table>
              {!visibleRecords.length && <div className="empty-state"><span>⌕</span><strong>{records.length ? 'Không tìm thấy hồ sơ phù hợp' : 'Chưa có hồ sơ trong danh sách'}</strong><p>{records.length ? 'Thử thay đổi từ khóa hoặc bộ lọc.' : 'Hồ sơ sẽ xuất hiện ở đây khi được tạo trong khoa của bạn.'}</p></div>}
            </div>
            <div className="table-footer"><span>Đang hiển thị <strong>{visibleRecords.length}</strong> trong <strong>{records.length}</strong> hồ sơ đã tải</span>{hasMore && <button className="load-more" onClick={() => loadRecords(token, false).catch((err) => setError(err.message))}>Tải thêm hồ sơ →</button>}</div>
          </section>

          {uploads.length > 0 && <section className="uploads-panel"><div className="uploads-title"><div><div className="section-kicker">TỆP VỪA TẢI</div><h2>Trong phiên này</h2></div><span>{uploads.length} tệp</span></div><div className="uploads-list">{uploads.slice(0, 4).map((file) => <div className="upload-item" key={file.id}><span className="upload-file-icon">▧</span><span className="upload-file-copy"><strong>{file.original_filename}</strong><small>{file.record_number} · {(file.size_bytes / 1024 / 1024).toFixed(2)} MB</small></span><button className="text-button" onClick={() => handleDownload(file)}>Tải xuống ↓</button></div>)}</div><p className="hint-text">Tệp đính kèm hiện được liệt kê trong phiên này. API chưa cung cấp danh sách tệp đã lưu từ các phiên trước.</p></section>}
          <footer className="page-footer"><span>✚ <strong>MedVault</strong> · Bảo vệ dữ liệu y tế</span><span>Chỉ truy cập hồ sơ trong phạm vi được cấp quyền</span></footer>
        </div>
      </main>

      {modal && <RecordModal type={modal.type} record={modal.record} departments={filteredDepartmentOptions} saving={saving} onClose={() => setModal(null)} onSubmit={handleSaveRecord} />}
    </div>
  )
}

function StatCard({ label, value, icon, tone, caption }) {
  return <article className="stat-card"><div className="stat-top"><span>{label}</span><span className={`stat-icon ${tone}`}>{icon}</span></div><div className="stat-value">{value}</div><div className="stat-caption"><span className={`caption-dot ${tone}`} />{caption}</div></article>
}

function LoginScreen({ onSubmit, saving, error }) {
  return <main className="login-page"><div className="login-orb orb-one" /><div className="login-orb orb-two" /><section className="login-card">
    <a className="login-brand" href="#login"><span className="brand-mark">✚</span><span><strong>MedVault</strong><small>HOSPITAL WORKSPACE</small></span></a>
    <div className="login-kicker"><span className="live-dot" /> CỔNG HỒ SƠ Y TẾ AN TOÀN</div><h1>Chào mừng<br />bạn trở lại.</h1><p className="login-copy">Đăng nhập bằng tài khoản bệnh viện để truy cập hồ sơ được cấp quyền.</p>
    {error && <div className="alert error-alert" role="alert"><span>!</span>{error}</div>}
    <form className="login-form" onSubmit={onSubmit}><label>Tên đăng nhập<input name="username" autoComplete="username" placeholder="Nhập tên đăng nhập" maxLength="80" required autoFocus /></label><label>Mật khẩu<input type="password" name="password" autoComplete="current-password" placeholder="Nhập mật khẩu" maxLength="256" required /></label><button className="primary-button login-submit" disabled={saving}>{saving ? 'Đang đăng nhập…' : 'Đăng nhập'}<span>→</span></button></form>
    <div className="login-security"><span>♢</span><div><strong>Kết nối bảo mật</strong><small>Token truy cập ngắn hạn · Quyền theo vai trò</small></div></div>
    <p className="login-footer">Cần tài khoản? Liên hệ quản trị viên hệ thống.</p>
  </section><div className="login-aside"><div className="aside-motif">✚</div><p>HỒ SƠ CHĂM SÓC<br /><strong>ĐƯỢC BẢO VỆ.</strong></p><span>Không gian làm việc cho đội ngũ y tế.</span></div></main>
}

function RecordModal({ type, record, departments, saving, onClose, onSubmit }) {
  const editing = type === 'edit'
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="record-modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div className="modal-header"><div><div className="section-kicker">{editing ? 'CẬP NHẬT THÔNG TIN' : 'HỒ SƠ MỚI'}</div><h2 id="modal-title">{editing ? 'Chỉnh sửa hồ sơ' : 'Tạo hồ sơ bệnh án'}</h2><p>{editing ? 'Thay đổi tiêu đề hoặc trạng thái hồ sơ.' : 'Thông tin sẽ được lưu vào kho dữ liệu an toàn.'}</p></div><button className="modal-close" onClick={onClose} aria-label="Đóng">×</button></div>
      <form onSubmit={onSubmit} className="record-form">
        {!editing && <div className="form-row"><label>Mã hồ sơ<input name="record_number" placeholder="VD: CL-2026-001" maxLength="50" required /></label><label>Mã bệnh nhân<input name="patient_code" placeholder="VD: BN-00142" maxLength="50" required /></label></div>}
        <label>Tiêu đề hồ sơ<input name="title" defaultValue={record?.title || ''} placeholder="Nhập tiêu đề hồ sơ" maxLength="255" required autoFocus={editing} /></label>
        {editing ? <label>Trạng thái<select name="status" defaultValue={record.status}><option value="active">Đang hoạt động</option><option value="archived">Đã lưu trữ</option></select></label> : <label>Khoa phụ trách<select name="department" required defaultValue={departments.length === 1 ? departments[0] : ''}><option value="" disabled>Chọn khoa</option>{departments.map((department) => <option key={department} value={department}>{DEPARTMENT_NAMES[department] || department}</option>)}</select></label>}
        <div className="modal-actions"><button className="secondary-button" type="button" onClick={onClose}>Hủy</button><button className="primary-button" disabled={saving}>{saving ? 'Đang lưu…' : editing ? 'Lưu thay đổi' : 'Tạo hồ sơ'}<span>→</span></button></div>
      </form>
    </section>
  </div>
}

export default App
