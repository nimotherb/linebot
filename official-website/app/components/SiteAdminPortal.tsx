'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import SiteAdminEditor from './SiteAdminEditor';
import type { SiteAdminApi, SiteContentPayload, SiteDraft, StaffProfile } from './SiteAdminEditor';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'https://linebot-3r2w.onrender.com';
const TOKEN_KEY = 'equalspa_site_studio_token';

type AdminRole = 'admin' | 'manager' | 'clerk';
type AdminIdentity = {
  id: number;
  username: string;
  display_name: string;
  role: AdminRole;
  is_active: boolean;
};

type LoginPayload = {
  access_token: string;
  user: AdminIdentity;
};

async function apiRequest<T>(path: string, token?: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  const text = await response.text();
  let payload: unknown = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { detail: text };
    }
  }
  if (!response.ok) {
    const detail = typeof payload === 'object' && payload && 'detail' in payload
      ? String((payload as { detail: unknown }).detail)
      : '連線失敗，請稍後再試。';
    throw new Error(detail);
  }
  return payload as T;
}

function roleLabel(role: AdminRole) {
  return role === 'admin' ? '系統管理員' : role === 'manager' ? '店長' : '客服';
}

export default function SiteAdminPortal() {
  const [token, setToken] = useState('');
  const [user, setUser] = useState<AdminIdentity | null>(null);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [manageUsers, setManageUsers] = useState(false);
  const [users, setUsers] = useState<AdminIdentity[]>([]);
  const [usersBusy, setUsersBusy] = useState(false);

  const clearSession = useCallback(() => {
    window.localStorage.removeItem(TOKEN_KEY);
    setToken('');
    setUser(null);
    setManageUsers(false);
  }, []);

  const notify = useCallback((message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(''), 3600);
  }, []);

  useEffect(() => {
    const storedToken = window.localStorage.getItem(TOKEN_KEY);
    if (!storedToken) {
      setChecking(false);
      return;
    }
    apiRequest<AdminIdentity>('/api/admin/auth/me', storedToken)
      .then((identity) => {
        if (identity.role !== 'admin' && identity.role !== 'manager') {
          throw new Error('此帳號沒有官網編輯權限。');
        }
        setToken(storedToken);
        setUser(identity);
      })
      .catch(() => window.localStorage.removeItem(TOKEN_KEY))
      .finally(() => setChecking(false));
  }, []);

  const request = useCallback(async <T,>(path: string, init: RequestInit = {}) => {
    try {
      return await apiRequest<T>(path, token, init);
    } catch (requestError) {
      if (requestError instanceof Error && /登入|工作階段|驗證|401/.test(requestError.message)) {
        clearSession();
      }
      throw requestError;
    }
  }, [clearSession, token]);

  const editorApi = useMemo<SiteAdminApi>(() => ({
    getAdminSiteContent: () => request<SiteContentPayload>('/api/admin/site-content'),
    saveSiteDraft: (content: SiteDraft, expectedVersion: number) => request<SiteContentPayload>('/api/admin/site-content/draft', {
      method: 'PUT',
      body: JSON.stringify({ content, expected_version: expectedVersion }),
    }),
    publishSiteContent: (expectedVersion: number) => request<SiteContentPayload>('/api/admin/site-content/publish', {
      method: 'POST',
      body: JSON.stringify({ expected_version: expectedVersion }),
    }),
    listStaff: () => request<StaffProfile[]>('/api/admin/staff'),
    createStaff: (payload: Record<string, unknown>) => request<StaffProfile>('/api/admin/staff', { method: 'POST', body: JSON.stringify(payload) }),
    updateStaff: (id: number, payload: Record<string, unknown>) => request<StaffProfile>(`/api/admin/staff/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    updateStaffStatus: (id: number, employmentStatus: StaffProfile['employment_status'], reason: string) => request<StaffProfile>(`/api/admin/staff/${id}/status`, { method: 'PATCH', body: JSON.stringify({ employment_status: employmentStatus, reason }) }),
    uploadStaffPhoto: (id: number, dataUrl: string) => request<StaffProfile>(`/api/admin/staff/${id}/photo`, { method: 'PUT', body: JSON.stringify({ data_url: dataUrl }) }),
    permanentlyDeleteStaff: (id: number) => request<{ ok: boolean }>(`/api/admin/staff/${id}?reason=${encodeURIComponent('官網編輯器永久刪除')}`, { method: 'DELETE' }),
  }), [request]);

  const login = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    const data = new FormData(event.currentTarget);
    try {
      const result = await apiRequest<LoginPayload>('/api/admin/auth/login', undefined, {
        method: 'POST',
        body: JSON.stringify({ username: String(data.get('username')).trim(), pin: String(data.get('pin')) }),
      });
      if (result.user.role !== 'admin' && result.user.role !== 'manager') {
        await apiRequest('/api/admin/auth/logout', result.access_token, { method: 'POST' }).catch(() => undefined);
        throw new Error('官網編輯器僅開放 Admin 與店長使用。');
      }
      window.localStorage.setItem(TOKEN_KEY, result.access_token);
      setToken(result.access_token);
      setUser(result.user);
      event.currentTarget.reset();
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : '登入失敗，請確認帳號與 PIN。');
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    if (token) {
      await apiRequest('/api/admin/auth/logout', token, { method: 'POST' }).catch(() => undefined);
    }
    clearSession();
  };

  const openUserManager = async () => {
    if (user?.role !== 'admin') return;
    setManageUsers(true);
    setUsersBusy(true);
    setError('');
    try {
      setUsers(await request<AdminIdentity[]>('/api/admin/users'));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '帳戶資料讀取失敗。');
    } finally {
      setUsersBusy(false);
    }
  };

  const createUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (user?.role !== 'admin') return;
    setUsersBusy(true);
    setError('');
    const data = new FormData(event.currentTarget);
    try {
      const created = await request<AdminIdentity>('/api/admin/users', {
        method: 'POST',
        body: JSON.stringify({
          display_name: String(data.get('display_name')).trim(),
          username: String(data.get('username')).trim().toLowerCase(),
          role: String(data.get('role')),
          pin: String(data.get('pin')),
        }),
      });
      setUsers((current) => [...current, created]);
      event.currentTarget.reset();
      notify(`已建立 ${created.display_name} 的登入帳戶。`);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : '帳戶建立失敗。');
    } finally {
      setUsersBusy(false);
    }
  };

  if (checking) {
    return <main className="studio-login-shell"><div className="studio-login-loader" aria-label="驗證登入狀態" /></main>;
  }

  if (!user || !token) {
    return <main className="studio-login-shell">
      <section className="studio-login-card">
        <a className="studio-login-brand" href="/"><i>E</i><span><b>EQUAL SPA</b><small>SITE STUDIO</small></span></a>
        <div className="studio-login-copy"><small>AUTHORIZED CONTENT WORKSPACE</small><h1>官網編輯器登入</h1><p>請使用伊果 SPA 的管理帳號與數字 PIN。登入成功後會直接進入內容編輯器。</p></div>
        <form onSubmit={login}>
          <label>登入帳號<input name="username" required autoCapitalize="none" autoComplete="username" placeholder="輸入管理帳號" /></label>
          <label>數字 PIN<input name="pin" required type="password" inputMode="numeric" pattern="[0-9]+" minLength={4} maxLength={32} autoComplete="current-password" placeholder="••••" /></label>
          {error && <p className="studio-login-error" role="alert">{error}</p>}
          <button type="submit" disabled={busy}>{busy ? '驗證中…' : '登入官網編輯器'}</button>
        </form>
        <footer><span>僅限 Admin 與店長</span><a href="/">返回官網</a></footer>
      </section>
    </main>;
  }

  return <div className="studio-session-shell">
    <SiteAdminEditor api={editorApi} notify={notify} userRole={user.role === 'admin' ? 'admin' : 'manager'} />
    <aside className="studio-session-card">
      <span>{user.display_name.slice(0, 1).toUpperCase()}</span>
      <div><b>{user.display_name}</b><small>{roleLabel(user.role)} · @{user.username}</small></div>
      {user.role === 'admin' && <button type="button" onClick={openUserManager}>帳戶管理</button>}
      <button type="button" onClick={logout}>登出</button>
    </aside>
    {notice && <div className="studio-toast" role="status">{notice}</div>}
    {manageUsers && user.role === 'admin' && <div className="studio-account-overlay" role="dialog" aria-modal="true" aria-labelledby="account-manager-title">
      <section className="studio-account-modal">
        <header><div><small>ADMIN ONLY</small><h2 id="account-manager-title">登入帳戶管理</h2><p>只有 Admin 可以新增帳戶。PIN 只會以安全雜湊保存。</p></div><button type="button" onClick={() => { setManageUsers(false); setError(''); }} aria-label="關閉帳戶管理">×</button></header>
        <div className="studio-account-layout">
          <form onSubmit={createUser}>
            <h3>新增使用帳戶</h3>
            <label>顯示名稱<input name="display_name" required /></label>
            <label>登入帳號<input name="username" required autoCapitalize="none" pattern="[a-zA-Z0-9._-]+" minLength={3} /></label>
            <label>帳戶角色<select name="role" defaultValue="clerk"><option value="clerk">客服</option><option value="manager">店長</option><option value="admin">Admin</option></select></label>
            <label>初始數字 PIN<input name="pin" required type="password" inputMode="numeric" pattern="[0-9]+" minLength={4} maxLength={32} /></label>
            {error && <p className="studio-login-error" role="alert">{error}</p>}
            <button type="submit" disabled={usersBusy}>{usersBusy ? '處理中…' : '建立帳戶'}</button>
          </form>
          <div className="studio-account-list"><h3>現有帳戶</h3>{usersBusy && users.length === 0 ? <p>讀取中…</p> : users.map((item) => <article key={item.id}><span>{item.display_name.slice(0, 1).toUpperCase()}</span><div><b>{item.display_name}</b><small>@{item.username} · {roleLabel(item.role)}</small></div><em>{item.is_active ? '啟用中' : '已停用'}</em></article>)}</div>
        </div>
      </section>
    </div>}
  </div>;
}
