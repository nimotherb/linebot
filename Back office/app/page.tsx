'use client';

import { FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
import type { Appointment, Customer, ServicePlan, Shift, StaffMember } from './models';
import {
  AdminIdentity,
  AuditLogView,
  BootstrapData,
  mapAdminUser,
  mapAppointment,
  mapAuditLog,
  mapCustomer,
  mapPromotion,
  mapService,
  mapShift,
  mapStaff,
  PromotionView,
  RawBookingRequest,
  SpaApi,
  StaffIdentity,
  ReturnRuleSetView,
} from './api-client';
import { useNavigationLoading } from './components/NavigationLoading';

type SectionId = 'dashboard' | 'appointments' | 'schedule' | 'operations' | 'checkout' | 'customers' | 'staff' | 'services' | 'exports' | 'users' | 'staffPortal';
type ModalState =
  | { type: 'appointment' }
  | { type: 'appointmentDetail'; id: string }
  | { type: 'appointmentEdit'; id: string }
  | { type: 'shift'; origin: 'admin' | 'staff' }
  | { type: 'shiftDetail'; id: string; origin: 'admin' | 'staff' }
  | { type: 'checkout'; id: string }
  | { type: 'serviceCreate' }
  | { type: 'service'; id: string }
  | { type: 'promotion' }
  | { type: 'promotionEdit'; id: string }
  | { type: 'returnRule'; setId: number; ruleId: number }
  | { type: 'customer'; id: string }
  | { type: 'staff' }
  | { type: 'staffEdit'; id: string }
  | { type: 'staffDelete'; id: string }
  | { type: 'bookingRequest'; id: number }
  | { type: 'user' }
  | { type: 'account' }
  | null;

type BulkEntity = 'appointments' | 'booking_requests' | 'shifts' | 'customers' | 'staff' | 'services' | 'promotions' | 'rooms' | 'venues' | 'users' | 'audit_logs';

const navGroups: { label: string; items: { id: SectionId; label: string; glyph: string }[] }[] = [
  {
    label: '營運',
    items: [
      { id: 'dashboard', label: '今日總覽', glyph: '◫' },
      { id: 'appointments', label: '預約管理', glyph: '◷' },
      { id: 'schedule', label: '師傅排班', glyph: '▦' },
      { id: 'operations', label: '現場進度', glyph: '◎' },
      { id: 'checkout', label: '結帳管理', glyph: '＄' },
    ],
  },
  {
    label: '資料與設定',
    items: [
      { id: 'customers', label: '客戶管理', glyph: '◇' },
      { id: 'staff', label: '員工管理', glyph: '♙' },
      { id: 'services', label: '服務與優惠', glyph: '✦' },
      { id: 'exports', label: '資料匯出', glyph: '⇩' },
      { id: 'users', label: '帳號與權限', glyph: '⚿' },
    ],
  },
];

const headings: Record<SectionId, { eyebrow: string; title: string; description: string }> = {
  dashboard: { eyebrow: 'TODAY', title: '歡迎回到伊果SPA', description: '目前登入：員工' },
  appointments: { eyebrow: 'APPOINTMENTS', title: '預約管理', description: '建立、搜尋、改期與人工修正預約。' },
  schedule: { eyebrow: 'WEEKLY ROSTER', title: '師傅排班', description: '本週與下週班表，距開始 90 分鐘後鎖定。' },
  operations: { eyebrow: 'SERVICE FLOW', title: '訂單進度', description: '待確認、已確認與已完成三種狀態。' },
  checkout: { eyebrow: 'CHECKOUT', title: '完成訂單', description: '記錄現金或轉帳；按完成即視為回帳完成。' },
  customers: { eyebrow: 'CUSTOMERS', title: '客戶管理', description: 'LINE 顯示名稱、電話、歷史紀錄與客服備註。' },
  staff: { eyebrow: 'TEAM', title: '員工管理', description: '員工建檔、公開照片、暫時退役與永久刪除。' },
  services: { eyebrow: 'PRICING', title: '服務與優惠', description: '方案價格、期間與附加費都可隨時調整。' },
  exports: { eyebrow: 'DATA CENTER', title: '資料中心', description: '依日期範圍匯出 Excel 相容 CSV 或純文字。' },
  users: { eyebrow: 'ACCESS CONTROL', title: '帳號與權限', description: '管理 Admin、店長與客服角色。' },
  staffPortal: { eyebrow: 'STAFF LINK PREVIEW', title: '師傅安全登入班表', description: '使用資料庫中的師傅與班表預覽 LINE 專屬登入入口。' },
};

const formatCurrency = (value: number) => `NT$ ${value.toLocaleString('zh-TW')}`;
const toMinutes = (clock: string) => {
  if (clock === '24:00') return 1440;
  const [hours, minutes] = clock.split(':').map(Number);
  return hours * 60 + minutes;
};
const CLOCK_OPTIONS = Array.from({ length: 48 }, (_, index) => {
  const hour = String(Math.floor(index / 2)).padStart(2, '0');
  const minute = index % 2 ? '30' : '00';
  return `${hour}:${minute}`;
});
const shiftDurationMinutes = (shift: Shift) => Math.max(0, Math.round((
  new Date(`${shift.endDate}T${shift.end}:00+08:00`).getTime()
  - new Date(`${shift.date}T${shift.start}:00+08:00`).getTime()
) / 60000));
const shiftTimeLabel = (shift: Shift) => `${shift.start}–${shift.endDate === shift.date ? '' : `${shift.endDate.slice(5).replace('-', '/')} `}${shift.end}`;
const staffPhotoDataUrl = (file: File) => new Promise<string>((resolve, reject) => {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) return reject(new Error('只接受 JPEG、PNG 或 WebP 圖片。'));
  if (file.size > 3 * 1024 * 1024) return reject(new Error('照片大小必須小於 3 MB。'));
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result));
  reader.onerror = () => reject(new Error('照片讀取失敗。'));
  reader.readAsDataURL(file);
});
const TAIPEI_TIME_ZONE = 'Asia/Taipei';
const taipeiParts = (date: Date) => Object.fromEntries(
  new Intl.DateTimeFormat('en-US', {
    timeZone: TAIPEI_TIME_ZONE,
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).filter((part) => part.type !== 'literal').map((part) => [part.type, part.value]),
) as Record<string, string>;
const taipeiDateValue = (date: Date) => {
  const parts = taipeiParts(date);
  return `${parts.year}-${parts.month}-${parts.day}`;
};
const buildBusinessWeek = (weekOffset: number, reference = new Date()) => {
  const parts = taipeiParts(reference);
  const localDate = new Date(Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day)));
  const daysSinceMonday = (localDate.getUTCDay() + 6) % 7;
  localDate.setUTCDate(localDate.getUTCDate() - daysSinceMonday + weekOffset * 7);
  const dayNames = ['日', '一', '二', '三', '四', '五', '六'];
  return Array.from({ length: 7 }, (_, index) => {
    const day = new Date(localDate);
    day.setUTCDate(localDate.getUTCDate() + index);
    return {
      date: day.toISOString().slice(0, 10),
      day: dayNames[day.getUTCDay()],
      label: `${day.getUTCMonth() + 1}/${day.getUTCDate()}`,
    };
  });
};
const nextBookableSlot = () => {
  const threshold = Date.now() + 90 * 60 * 1000;
  const rounded = new Date(Math.ceil(threshold / (30 * 60 * 1000)) * 30 * 60 * 1000);
  const parts = taipeiParts(rounded);
  return { date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}` };
};
const isShiftLocked = (shift: Shift) => {
  if (typeof shift.locked === 'boolean') return shift.locked;
  const shiftStart = new Date(`${shift.date}T${shift.start}:00+08:00`).getTime();
  const cutoff = Date.now() + 90 * 60 * 1000;
  return shiftStart <= cutoff;
};

function Modal({ title, subtitle, children, onClose, wide = false }: { title: string; subtitle?: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className={wide ? 'modal-card wide' : 'modal-card'} role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <header className="modal-header">
          <div><p className="eyebrow">EQUAL SPA</p><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
          <button className="close-button" onClick={onClose} aria-label="關閉">×</button>
        </header>
        {children}
      </section>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone = status === '待確認' ? 'warning' : status === '已完成' || status === '已付款' ? 'done' : status === '已停用' ? 'muted-status' : 'confirmed';
  return <span className={`status ${tone}`}>{status}</span>;
}

function ClockSelect({ name, defaultValue = '00:00' }: { name: string; defaultValue?: string }) {
  return <select name={name} defaultValue={defaultValue} required>{CLOCK_OPTIONS.map((value) => <option key={value} value={value}>{value}</option>)}</select>;
}

export default function Home() {
  const todayIso = taipeiDateValue(new Date());
  const currentWeekDays = buildBusinessWeek(0);
  const followingWeekDays = buildBusinessWeek(1);
  const bookingDefault = nextBookableSlot();
  const shiftEndDefault = (() => {
    const value = new Date(`${bookingDefault.date}T${bookingDefault.time}:00+08:00`);
    value.setMinutes(value.getMinutes() + 60);
    const parts = taipeiParts(value);
    return { date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}` };
  })();
  const todayLabel = new Intl.DateTimeFormat('zh-TW', { timeZone: TAIPEI_TIME_ZONE, year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' }).format(new Date());
  const [active, setActive] = useState<SectionId>('dashboard');
  const [role, setRole] = useState<'admin' | 'manager' | 'clerk' | 'staff' | 'viewer'>('viewer');
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [bookingRequests, setBookingRequests] = useState<RawBookingRequest[]>([]);
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [plans, setPlans] = useState<ServicePlan[]>([]);
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [promotions, setPromotions] = useState<PromotionView[]>([]);
  const [adminUsers, setAdminUsers] = useState<ReturnType<typeof mapAdminUser>[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogView[]>([]);
  const [rooms, setRooms] = useState<{ id: number; name: string }[]>([]);
  const [venues, setVenues] = useState<NonNullable<BootstrapData['venues']>>([]);
  const [modal, setModal] = useState<ModalState>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [appointmentSearch, setAppointmentSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('全部');
  const [customerSearch, setCustomerSearch] = useState('');
  const [staffCategoryFilter, setStaffCategoryFilter] = useState<'全部' | StaffMember['category']>('全部');
  const [staffPage, setStaffPage] = useState(1);
  const [scheduleCategoryFilter, setScheduleCategoryFilter] = useState<'全部' | StaffMember['category']>('全部');
  const [schedulePage, setSchedulePage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<Partial<Record<BulkEntity, number[]>>>({});
  const [week, setWeek] = useState<'current' | 'next'>('current');
  const [appMode, setAppMode] = useState<'checking' | 'unavailable' | 'login' | 'live' | 'staff' | 'staffLink'>('checking');
  const [connectionError, setConnectionError] = useState('');
  const [token, setToken] = useState('');
  const [identity, setIdentity] = useState<AdminIdentity | null>(null);
  const [staffIdentity, setStaffIdentity] = useState<StaffIdentity | null>(null);
  const [returnRuleSets, setReturnRuleSets] = useState<ReturnRuleSetView[]>([]);
  const [exportStart, setExportStart] = useState(currentWeekDays[0].date);
  const [exportEnd, setExportEnd] = useState(todayIso);
  const [loginError, setLoginError] = useState('');
  const [loginBusy, setLoginBusy] = useState(false);
  const [staffToken, setStaffToken] = useState('');
  const [staffPortalName, setStaffPortalName] = useState('師傅');
  const [staffPortalError, setStaffPortalError] = useState('');
  const { runNavigation, startNavigation, stopNavigation } = useNavigationLoading();

  const api = useMemo(() => new SpaApi(token), [token]);

  const navigateTo = (section: SectionId) => {
    if (section === active) return;
    runNavigation(() => {
      setActive(section);
      setModal(null);
      window.scrollTo({ top: 0, behavior: 'auto' });
    }, '正在切換頁面…');
  };

  const applyBootstrap = (data: BootstrapData, mode: 'live' | 'staff' = 'live') => {
    setIdentity(data.user || null);
    setStaffIdentity(data.staff_user || null);
    setRole(data.user?.role || 'staff');
    setAppointments(data.appointments.map(mapAppointment));
    setBookingRequests(data.booking_requests || []);
    setShifts(data.shifts.map(mapShift));
    setPlans(data.services.map(mapService));
    setStaff(data.staff.map(mapStaff));
    setPromotions(data.promotions.map(mapPromotion));
    setRooms(data.rooms.map((room) => ({ id: room.id, name: room.name })));
    setVenues(data.venues || []);
    setCustomers((data.customers || []).map(mapCustomer));
    setAdminUsers((data.admin_users || []).map(mapAdminUser));
    setReturnRuleSets(data.return_rule_sets || []);
    setAuditLogs((data.audit_logs || []).map(mapAuditLog));
    setConnectionError('');
    setAppMode(mode);
    const requestedId = Number(new URLSearchParams(window.location.search).get('booking_request') || 0);
    if (mode === 'live' && requestedId && (data.booking_requests || []).some((item) => item.id === requestedId)) {
      setActive('appointments');
      setModal({ type: 'bookingRequest', id: requestedId });
    }
  };

  useEffect(() => {
    let activeRequest = true;
    const initialize = async () => {
      const searchParams = new URLSearchParams(window.location.search);
      const lineLoginToken = searchParams.get('staff_login');
      if (lineLoginToken) {
        try {
          const result = await new SpaApi().staffLineLogin(lineLoginToken);
          const data = await new SpaApi(result.access_token).staffBootstrap();
          if (!activeRequest) return;
          window.sessionStorage.setItem('equalspa-staff-token', result.access_token);
          window.sessionStorage.removeItem('equalspa-admin-token');
          window.history.replaceState({}, '', window.location.pathname);
          setToken(result.access_token);
          applyBootstrap(data, 'staff');
        } catch (error) {
          if (!activeRequest) return;
          setStaffPortalError(error instanceof Error ? error.message : 'LINE 登入連結已失效');
          setAppMode('staffLink');
        }
        return;
      }
      const scheduleToken = searchParams.get('staff_token');
      if (scheduleToken) {
        setStaffToken(scheduleToken);
        try {
          const data = await new SpaApi().publicSchedule(scheduleToken);
          if (!activeRequest) return;
          setStaffPortalName(data.staff.name);
          setShifts(data.shifts.map((shift) => mapShift({ ...shift, staff_name: data.staff.name })));
        } catch (error) {
          setStaffPortalError(error instanceof Error ? error.message : '班表連結無效');
        }
        setAppMode('staffLink');
        return;
      }
      const savedAdminToken = window.sessionStorage.getItem('equalspa-admin-token');
      const savedStaffToken = window.sessionStorage.getItem('equalspa-staff-token');
      if (!savedAdminToken && !savedStaffToken) {
        setConnectionError('');
        setAppMode('login');
        return;
      }
      const backendReady = await SpaApi.probe();
      if (!activeRequest) return;
      if (!backendReady) {
        setConnectionError('目前無法連線至 FastAPI／MySQL，畫面不會顯示任何測試資料。請稍後重試。');
        setAppMode('unavailable');
        return;
      }
      if (savedAdminToken) {
        try {
          const data = await new SpaApi(savedAdminToken).bootstrap();
          if (!activeRequest) return;
          setToken(savedAdminToken);
          applyBootstrap(data, 'live');
          return;
        } catch { window.sessionStorage.removeItem('equalspa-admin-token'); }
      }
      if (savedStaffToken) {
        try {
          const data = await new SpaApi(savedStaffToken).staffBootstrap();
          if (!activeRequest) return;
          setToken(savedStaffToken);
          applyBootstrap(data, 'staff');
          return;
        } catch { window.sessionStorage.removeItem('equalspa-staff-token'); }
      }
      setConnectionError('');
      setAppMode('login');
    };
    initialize();
    return () => { activeRequest = false; };
  }, []);

  const login = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoginBusy(true);
    setLoginError('');
    startNavigation('正在登入後台…');
    const data = new FormData(event.currentTarget);
    let redirecting = false;
    try {
      const result = await new SpaApi().login(String(data.get('username')), String(data.get('pin')));
      window.sessionStorage.setItem('equalspa-admin-token', result.access_token);
      window.sessionStorage.removeItem('equalspa-staff-token');
      setToken(result.access_token);
      setIdentity(result.user);
      setStaffIdentity(null);
      setRole(result.user.role);
      setAppMode('live');
      setActive('dashboard');
      setModal(null);
      window.scrollTo({ top: 0, behavior: 'auto' });
      redirecting = true;
      window.location.replace(new URL('/', window.location.origin).toString());
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : '登入失敗');
    } finally {
      if (!redirecting) {
        setLoginBusy(false);
        stopNavigation();
      }
    }
  };

  const loginStaff = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoginBusy(true);
    setLoginError('');
    startNavigation('正在切換員工帳號…');
    const data = new FormData(event.currentTarget);
    const phone = String(data.get('staffPhone') || '').trim();
    let redirecting = false;
    try {
      const result = await new SpaApi().staffLogin({ phone });
      window.sessionStorage.setItem('equalspa-staff-token', result.access_token);
      window.sessionStorage.removeItem('equalspa-admin-token');
      setToken(result.access_token);
      setIdentity(null);
      setStaffIdentity(result.staff);
      setRole('staff');
      setAppMode('staff');
      setActive('dashboard');
      setModal(null);
      window.scrollTo({ top: 0, behavior: 'auto' });
      redirecting = true;
      window.location.replace(new URL('/', window.location.origin).toString());
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : '員工身分切換失敗');
    } finally {
      if (!redirecting) {
        setLoginBusy(false);
        stopNavigation();
      }
    }
  };

  const logout = async () => {
    startNavigation('正在登出並返回登入畫面…');
    try { if (token) await api.logout(appMode === 'staff' ? 'staff' : 'admin'); } catch {}
    window.sessionStorage.removeItem('equalspa-admin-token');
    window.sessionStorage.removeItem('equalspa-staff-token');
    setToken('');
    setIdentity(null);
    setStaffIdentity(null);
    setRole('viewer');
    setActive('dashboard');
    setAppMode('login');
    setLoginError('');
    stopNavigation();
  };

  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 3200);
  };

  const todayAppointments = appointments.filter((item) => item.date === todayIso);
  const pendingCheckout = appointments.filter((item) => item.status === '已確認');
  const completedRevenue = todayAppointments.filter((item) => item.status === '已完成' || item.payment === '已付款').reduce((sum, item) => sum + item.total, 0);
  const selectedAppointment = modal && 'id' in modal ? appointments.find((item) => item.id === modal.id) : undefined;
  const selectedShift = modal && 'id' in modal ? shifts.find((item) => item.id === modal.id) : undefined;
  const selectedCustomer = modal?.type === 'customer' ? customers.find((item) => item.id === modal.id) : undefined;
  const selectedBookingRequest = modal?.type === 'bookingRequest' ? bookingRequests.find((item) => item.id === modal.id) : undefined;
  const isViewer = appMode === 'unavailable';
  const isStaffUser = appMode === 'staff';
  const canManageAll = appMode === 'live' && (role === 'admin' || role === 'manager');
  const canManageShifts = appMode === 'live' && ['admin', 'manager', 'clerk'].includes(role);
  const canOverrideTimeRules = Boolean(identity?.can_override_time_rules);
  const canCreateUsers = appMode === 'live' && (role === 'admin' || role === 'manager');
  const canEditAppointments = appMode === 'live';
  const canCreateAppointments = appMode === 'live' || isStaffUser;
  const sensitiveVisible = appMode === 'live';
  const currentLoginLabel = isStaffUser ? '員工' : role === 'admin' ? 'Admin' : role === 'manager' ? '店長' : role === 'clerk' ? '客服' : '';
  const hiddenForViewer = new Set<SectionId>(['checkout', 'customers', 'exports', 'users']);
  const hiddenForStaff = new Set<SectionId>(['checkout', 'customers', 'exports', 'users']);
  const visibleNavGroups = navGroups.map((group) => ({ ...group, items: group.items.filter((item) => isViewer ? !hiddenForViewer.has(item.id) : isStaffUser ? !hiddenForStaff.has(item.id) : true) }));

  const filteredAppointments = useMemo(() => appointments.filter((item) => {
    const query = appointmentSearch.trim().toLowerCase();
    const matchesQuery = !query || [item.id, item.customer, item.phone, item.staff].some((value) => value.toLowerCase().includes(query));
    return matchesQuery && (statusFilter === '全部' || item.status === statusFilter);
  }), [appointmentSearch, appointments, statusFilter]);

  const filteredCustomers = useMemo(() => customers.filter((customer) => {
    const query = customerSearch.trim().toLowerCase();
    return !query || [customer.vipSerial, customer.name, customer.lineName, ...customer.phones].some((value) => value.toLowerCase().includes(query));
  }), [customerSearch, customers]);

  const filteredStaff = useMemo(() => staff.filter((member) => staffCategoryFilter === '全部' || member.category === staffCategoryFilter), [staff, staffCategoryFilter]);
  const staffPageCount = Math.max(1, Math.ceil(filteredStaff.length / 10));
  const pagedStaff = filteredStaff.slice((staffPage - 1) * 10, staffPage * 10);
  useEffect(() => { setStaffPage((current) => Math.min(current, staffPageCount)); }, [staffPageCount]);
  useEffect(() => { setStaffPage(1); }, [staffCategoryFilter]);
  const filteredScheduleStaff = useMemo(() => staff.filter((member) => (
    (appMode === 'live' || member.status === '在職')
    && (scheduleCategoryFilter === '全部' || member.category === scheduleCategoryFilter)
  )), [appMode, scheduleCategoryFilter, staff]);
  const schedulePageCount = Math.max(1, Math.ceil(filteredScheduleStaff.length / 10));
  const pagedScheduleStaff = filteredScheduleStaff.slice((schedulePage - 1) * 10, schedulePage * 10);
  useEffect(() => { setSchedulePage((current) => Math.min(current, schedulePageCount)); }, [schedulePageCount]);
  useEffect(() => { setSchedulePage(1); }, [scheduleCategoryFilter]);

  const toggleSelected = (entity: BulkEntity, id: number) => {
    setSelectedIds((current) => {
      const ids = current[entity] || [];
      return { ...current, [entity]: ids.includes(id) ? ids.filter((value) => value !== id) : [...ids, id] };
    });
  };

  const setPageSelected = (entity: BulkEntity, ids: number[], checked: boolean) => {
    setSelectedIds((current) => {
      const existing = current[entity] || [];
      return { ...current, [entity]: checked ? Array.from(new Set([...existing, ...ids])) : existing.filter((id) => !ids.includes(id)) };
    });
  };

  const bulkDeleteSelected = async (entity: BulkEntity, label: string) => {
    const ids = selectedIds[entity] || [];
    if (!ids.length) return notify(`請先勾選要刪除的${label}。`);
    const reason = window.prompt(`將永久刪除 ${ids.length} 筆${label}，請輸入刪除原因：`, '後台批量整理');
    if (!reason?.trim() || !window.confirm(`確定永久刪除已勾選的 ${ids.length} 筆${label}？此操作無法復原。`)) return;
    try {
      await api.bulkDelete(entity, ids, reason.trim());
      const data = await api.bootstrap();
      applyBootstrap(data, 'live');
      setSelectedIds((current) => ({ ...current, [entity]: [] }));
      notify(`已永久刪除 ${ids.length} 筆${label}。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : `批量刪除${label}失敗`);
    }
  };

  const BulkTools = ({ entity, ids, label }: { entity: BulkEntity; ids: number[]; label: string }) => {
    if (!canManageAll || ids.length === 0) return null;
    const selected = selectedIds[entity] || [];
    const allChecked = ids.every((id) => selected.includes(id));
    return <div className="bulk-tools"><label><input type="checkbox" checked={allChecked} onChange={(event) => setPageSelected(entity, ids, event.target.checked)} />全選本頁</label><span>已選 {selected.length} 筆</span><button className="danger-button" type="button" disabled={!selected.length} onClick={() => bulkDeleteSelected(entity, label)}>永久刪除所選</button></div>;
  };

  const addAppointment = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const plan = plans.find((item) => item.id === data.get('serviceId'));
    if (!plan) return;
    const date = String(data.get('date'));
    const start = String(data.get('start'));
    const selectedStaffMember = staff.find((item) => item.id === String(data.get('staff')));
    if (!selectedStaffMember) return notify('請選擇師傅。');
    const room = String(data.get('room'));

    if (appMode === 'live' || appMode === 'staff') {
      try {
        const roomRecord = rooms.find((item) => item.name === room);
        const venueRecord = venues.find((item) => item.name === room);
        const payload = {
          customer_name: String(data.get('customer')),
          phone: String(data.get('phone')),
          service_plan_id: plan.apiId,
          start_time: `${date}T${start}:00`,
          staff_id: selectedStaffMember.apiId,
          room_id: roomRecord?.id,
          venue_id: venueRecord?.id,
          promotion_id: Number(data.get('promotionId') || 0) || null,
          location_type: roomRecord ? 'onsite' : venueRecord ? 'external' : 'pending',
          notes: String(data.get('note') || ''),
        };
        const created = appMode === 'staff' ? await api.staffCreateAppointment(payload) : await api.createAppointment(payload);
        const item = mapAppointment(created);
        setAppointments((current) => [item, ...current]);
        setModal(null);
        notify(`已建立 ${item.id}，資料已寫入 MySQL。`);
      } catch (error) {
        notify(error instanceof Error ? error.message : '建立預約失敗');
      }
      return;
    }
    notify('目前未連線至資料庫，不能建立預約。');
  };

  const addShift = async (event: FormEvent<HTMLFormElement>, origin: 'admin' | 'staff') => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const startDate = String(data.get('startDate'));
    const endDate = String(data.get('endDate'));
    const start = String(data.get('start'));
    const end = String(data.get('end'));
    const selectedMember = origin === 'staff' ? staff.find((item) => item.name === staffPortalName) : staff.find((item) => item.id === String(data.get('staff')));
    const staffName = origin === 'staff' ? staffPortalName : selectedMember?.name || '未指定';
    const startIso = `${startDate}T${start}:00`;
    const endIso = `${endDate}T${end}:00`;
    const startAt = new Date(`${startIso}+08:00`).getTime();
    const endAt = new Date(`${endIso}+08:00`).getTime();
    if (!Number.isFinite(startAt) || !Number.isFinite(endAt) || endAt <= startAt) return notify('排班結束時間必須晚於開始時間。');
    if (origin === 'staff' && startAt <= Date.now() + 90 * 60 * 1000) return notify('開始時間已進入 90 分鐘鎖定範圍，請聯絡店長。');
    if (appMode === 'staffLink' && origin === 'staff') {
      try {
        const created = await new SpaApi().publicCreateShift(staffToken, { start_time: startIso, end_time: endIso });
        setShifts((current) => [...current, mapShift({ ...created, staff_name: staffPortalName })]);
        notify(`已新增 ${start}–${end} 排班。`);
      } catch (error) {
        notify(error instanceof Error ? error.message : '新增排班失敗');
      }
      return;
    }
    if (appMode === 'staff' && origin === 'staff') {
      try {
        const created = await api.staffCreateShift({ start_time: startIso, end_time: endIso });
        setShifts((current) => [...current, mapShift(created)]);
        setModal(null);
        notify(`已新增 ${start}–${end} 排班。`);
      } catch (error) {
        notify(error instanceof Error ? error.message : '新增排班失敗');
      }
      return;
    }
    if (appMode === 'live' && origin === 'admin') {
      try {
        const created = await api.createShift({ staff_id: selectedMember?.apiId, start_time: startIso, end_time: endIso });
        setShifts((current) => [...current, mapShift(created)]);
        setModal(null);
        notify(`已新增 ${staffName} 的 ${start}–${end} 排班，並寫入 MySQL。`);
      } catch (error) {
        notify(error instanceof Error ? error.message : '新增排班失敗');
      }
      return;
    }
    notify('目前未連線至資料庫，不能新增排班。');
  };

  const saveService = async (event: FormEvent<HTMLFormElement>, id: string) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const plan = plans.find((item) => item.id === id);
    const updatedFields = { name: String(data.get('name')), duration: Number(data.get('duration')), price: Number(data.get('price')), active: data.get('active') === 'on' };
    if (appMode === 'live' && plan?.apiId) {
      try {
        const updated = await api.updateService(plan.apiId, { name: updatedFields.name, duration_minutes: updatedFields.duration, price: updatedFields.price, active: updatedFields.active });
        setPlans((current) => current.map((item) => item.id === id ? mapService(updated) : item));
        setModal(null);
        notify('方案已更新並保存到 MySQL。');
      } catch (error) {
        notify(error instanceof Error ? error.message : '方案更新失敗');
      }
      return;
    }
    notify('目前未連線至資料庫，不能修改方案。');
  };

  const addService = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const created = await api.createService({
        code: String(data.get('code') || '').trim(),
        name: String(data.get('name') || '').trim(),
        duration_minutes: Number(data.get('duration')),
        price: Number(data.get('price')),
        description: String(data.get('description') || ''),
        location_type: data.get('location') === '外出' ? 'external' : 'onsite',
        can_choose_staff: data.get('canChooseStaff') === 'on',
      });
      setPlans((current) => [...current, mapService(created)]);
      setModal(null);
      notify('新方案已同步到後台、官網編輯器與預約系統。');
    } catch (error) {
      notify(error instanceof Error ? error.message : '新增方案失敗');
    }
  };

  const createRoomPrompt = async () => {
    const name = window.prompt('新增房間名稱：', '新房間')?.trim();
    if (!name) return;
    try { const created = await api.createRoom(name); setRooms((current) => [...current, created]); notify('房間已新增。'); }
    catch (error) { notify(error instanceof Error ? error.message : '新增房間失敗'); }
  };

  const editRoomPrompt = async (room: { id: number; name: string }) => {
    const name = window.prompt('修改房間名稱：', room.name)?.trim();
    if (!name || name === room.name) return;
    try { const updated = await api.updateRoom(room.id, { name }); setRooms((current) => current.map((item) => item.id === room.id ? updated : item)); notify('房間已更新。'); }
    catch (error) { notify(error instanceof Error ? error.message : '更新房間失敗'); }
  };

  const createVenuePrompt = async () => {
    const name = window.prompt('新增場地名稱：', '外租旅館')?.trim();
    if (!name) return;
    const address = window.prompt('場地地址（可留空）：', '')?.trim() || '';
    try { const created = await api.createVenue({ name, address, active: true }); setVenues((current) => [...current, created]); notify('場地已新增。'); }
    catch (error) { notify(error instanceof Error ? error.message : '新增場地失敗'); }
  };

  const editVenuePrompt = async (venue: NonNullable<BootstrapData['venues']>[number]) => {
    const name = window.prompt('修改場地名稱：', venue.name)?.trim();
    if (!name) return;
    const address = window.prompt('修改場地地址（可留空）：', venue.address || '')?.trim() || '';
    try { const updated = await api.updateVenue(venue.id, { name, address, active: venue.active }); setVenues((current) => current.map((item) => item.id === venue.id ? updated : item)); notify('場地已更新。'); }
    catch (error) { notify(error instanceof Error ? error.message : '更新場地失敗'); }
  };

  const finishCheckout = async (event: FormEvent<HTMLFormElement>, id: string) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const paymentMethod = String(data.get('paymentMethod'));
    const appointment = appointments.find((item) => item.id === id);
    if (appMode === 'live' && appointment?.apiId) {
      try {
        const result = await api.checkout(appointment.apiId, { amount: appointment.total, method: paymentMethod === '現金' ? 'cash' : 'transfer', received_by_staff_id: paymentMethod === '現金' && appointment.staffId ? Number(appointment.staffId) : null, note: String(data.get('note') || '') });
        const updated = mapAppointment(result.appointment);
        setAppointments((current) => current.map((item) => item.id === id ? updated : item));
        setModal(null);
        notify('訂單已完成，付款與回帳同步記錄。');
      } catch (error) {
        notify(error instanceof Error ? error.message : '結帳失敗');
      }
      return;
    }
    notify('目前未連線至資料庫，不能完成結帳。');
  };

  const removeShift = async (shift: Shift, origin: 'admin' | 'staff', reason = '') => {
    if (origin === 'staff' && isShiftLocked(shift)) return notify('此班已鎖定，已提示聯絡店長處理。');
    if (origin === 'admin' && isShiftLocked(shift) && !canOverrideTimeRules) return notify('此班已鎖定，請由店長、Admin 或具強制權限的客服處理。');
    if (appMode === 'staffLink' && origin === 'staff' && shift.apiId) {
      try {
        await new SpaApi().publicDeleteShift(staffToken, shift.apiId);
        setShifts((current) => current.filter((item) => item.id !== shift.id));
        notify('排班已撤銷。');
      } catch (error) {
        notify(error instanceof Error ? error.message : '撤銷排班失敗');
      }
      return;
    }
    if (appMode === 'staff' && origin === 'staff' && shift.apiId) {
      try {
        await api.staffDeleteShift(shift.apiId);
        setShifts((current) => current.filter((item) => item.id !== shift.id));
        setModal(null);
        notify('排班已撤銷。');
      } catch (error) {
        notify(error instanceof Error ? error.message : '撤銷排班失敗');
      }
      return;
    }
    if (appMode === 'live' && origin === 'admin' && shift.apiId) {
      try {
        await api.deleteShift(shift.apiId, reason);
        setShifts((current) => current.filter((item) => item.id !== shift.id));
        setModal(null);
        notify(isShiftLocked(shift) ? '已使用強制權限撤銷排班。' : '排班已撤銷。');
      } catch (error) {
        notify(error instanceof Error ? error.message : '撤銷排班失敗');
      }
      return;
    }
    notify('目前未連線至資料庫，不能撤銷排班。');
  };

  const exportCsv = async (kind: 'appointments' | 'shifts' | 'customers') => {
    if (appMode === 'live') {
      try {
        await api.download(kind, exportStart, exportEnd);
        notify('已從 MySQL 匯出 CSV。');
      } catch (error) {
        notify(error instanceof Error ? error.message : '匯出失敗');
      }
      return;
    }
    notify('目前未連線至資料庫，不能匯出資料。');
  };

  const updateAppointmentStatus = async (appointment: Appointment, status: Appointment['status']) => {
    if (appMode === 'live' && appointment.apiId) {
      try {
        const updated = await api.updateAppointment(appointment.apiId, { status });
        setAppointments((current) => current.map((item) => item.id === appointment.id ? mapAppointment(updated) : item));
        setModal(null);
        notify(`預約已更新為「${status}」並保存。`);
      } catch (error) {
        notify(error instanceof Error ? error.message : '更新預約失敗');
      }
      return;
    }
    notify('目前未連線至資料庫，不能更新預約。');
  };

  const saveAppointmentEdit = async (event: FormEvent<HTMLFormElement>, appointment: Appointment) => {
    event.preventDefault();
    if (!appointment.apiId || appMode !== 'live') return;
    const data = new FormData(event.currentTarget);
    const roomName = String(data.get('room'));
    const roomRecord = rooms.find((item) => item.name === roomName);
    const venueRecord = venues.find((item) => item.name === roomName);
    const payload: Record<string, unknown> = {
      customer_name: String(data.get('customer')),
      phone: String(data.get('phone')),
      start_time: `${data.get('date')}T${data.get('start')}:00`,
      service_plan_id: Number(data.get('serviceId')),
      promotion_id: Number(data.get('promotionId') || 0),
      staff_id: Number(data.get('staffId')),
      room_id: roomRecord?.id || null,
      venue_id: venueRecord?.id || null,
      location_type: roomRecord ? 'onsite' : venueRecord ? 'external' : 'pending',
      status: String(data.get('status')),
      notes: String(data.get('note') || ''),
      force_reason: String(data.get('reason') || ''),
    };
    if (canManageAll) {
      payload.base_price = Number(data.get('basePrice') || 0);
      payload.discount_amount = Number(data.get('discountAmount') || 0);
      payload.extra_amount = Number(data.get('extraAmount') || 0);
      payload.total_amount = Number(data.get('totalAmount') || 0);
    }
    try {
      const updated = await api.updateAppointment(appointment.apiId, payload);
      setAppointments((current) => current.map((item) => item.id === appointment.id ? mapAppointment(updated) : item));
      setModal(null);
      notify(canManageAll ? '整張訂單已更新並留下操作紀錄。' : '訂單可調整欄位已更新。');
    } catch (error) {
      notify(error instanceof Error ? error.message : '訂單更新失敗');
    }
  };

  const saveCustomer = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedCustomer?.apiId || appMode !== 'live') return;
    const data = new FormData(event.currentTarget);
    const phones = String(data.get('phones') || '').split(/[\s,，、]+/).map((value) => value.trim()).filter(Boolean);
    try {
      const updated = await api.updateCustomer(selectedCustomer.apiId, {
        display_name: String(data.get('displayName') || '').trim(),
        phones,
        customer_grade: String(data.get('customerGrade') || 'N') as Customer['grade'],
      });
      const mapped = mapCustomer(updated);
      setCustomers((current) => current.map((item) => item.id === selectedCustomer.id ? mapped : item));
      setModal(null);
      notify('客戶名稱與手機 ID 已更新。');
    } catch (error) {
      notify(error instanceof Error ? error.message : '客戶資料更新失敗');
    }
  };

  const addStaff = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const name = String(data.get('name'));
    const categoryLabel = String(data.get('category')) as '直男師傅' | '圈內師傅' | '雙性師傅';
    if (appMode === 'live') {
      try {
        const category = categoryLabel === '直男師傅' ? 'straight' : categoryLabel === '雙性師傅' ? 'bisexual' : 'gay';
        let created = await api.createStaff({ name, category, line_user_id: String(data.get('lineUserId') || '') || null, phone: String(data.get('phone') || '') || null, return_rule_set_id: Number(data.get('returnRuleSetId') || 0) || null, photo_url: String(data.get('photoUrl') || '').trim() || null, height: Number(data.get('height') || 0) || null, weight: Number(data.get('weight') || 0) || null, role: String(data.get('role') || '') || null });
        const photo = data.get('photoFile');
        if (photo instanceof File && photo.size > 0) created = await api.uploadStaffPhoto(created.id, await staffPhotoDataUrl(photo));
        setStaff((current) => [...current, mapStaff(created)]);
        setModal(null);
        notify(`${name} 已建立並保存到 MySQL。`);
      } catch (error) {
        notify(error instanceof Error ? error.message : '新增員工失敗');
      }
      return;
    }
    notify('目前未連線至資料庫，不能新增員工。');
  };

  const saveStaffProfile = async (event: FormEvent<HTMLFormElement>, member: typeof staff[number]) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const categoryLabel = String(data.get('category')) as typeof member.category;
    const category = categoryLabel === '直男師傅' ? 'straight' : categoryLabel === '雙性師傅' ? 'bisexual' : 'gay';
    const photo = data.get('photoFile');
    try {
      if (appMode === 'live' && member.apiId) {
        let updated = await api.updateStaff(member.apiId, {
          name: String(data.get('name')).trim(),
          category,
          photo_url: String(data.get('photoUrl') || '').trim() || null,
          height: Number(data.get('height') || 0) || null,
          weight: Number(data.get('weight') || 0) || null,
          role: String(data.get('role') || '') || null,
        });
        if (photo instanceof File && photo.size > 0) updated = await api.uploadStaffPhoto(member.apiId, await staffPhotoDataUrl(photo));
        setStaff((current) => current.map((item) => item.id === member.id ? mapStaff(updated) : item));
      } else {
        const uploaded = photo instanceof File && photo.size > 0 ? await staffPhotoDataUrl(photo) : String(data.get('photoUrl') || '').trim();
        setStaff((current) => current.map((item) => item.id === member.id ? { ...item, name: String(data.get('name')).trim(), category: categoryLabel, photoUrl: uploaded || undefined, height: String(data.get('height') || '') || undefined, weight: String(data.get('weight') || '') || undefined, role: String(data.get('role') || '') as StaffMember['role'] || undefined } : item));
      }
      setModal(null);
      notify(`${member.name} 的公開資料與照片已更新。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '師傅資料更新失敗');
    }
  };

  const toggleStaffStatus = async (member: typeof staff[number]) => {
    const nextStatus = member.status === '在職' ? '暫時退役' : '在職';
    if (appMode === 'live' && member.apiId) {
      try {
        const updated = await api.updateStaffStatus(member.apiId, { employment_status: nextStatus === '在職' ? 'active' : 'retired', reason: nextStatus === '在職' ? '管理後台恢復在職' : '管理後台暫時退役' });
        setStaff((current) => current.map((item) => item.id === member.id ? mapStaff(updated) : item));
        notify(`${member.name} 已${nextStatus === '在職' ? '恢復在職' : '設為暫時退役'}，歷史資料保留。`);
      } catch (error) {
        notify(error instanceof Error ? error.message : '更新員工狀態失敗');
      }
      return;
    }
    notify('目前未連線至資料庫，不能更新員工狀態。');
  };

  const unlinkStaffLine = async (member: typeof staff[number]) => {
    if (!member.apiId || !canManageAll || !member.lineConnected) return;
    if (!window.confirm(`確定解除 ${member.name} 目前的 LINE 連結？既有訂單與班表會保留。`)) return;
    try {
      const updated = await api.unlinkStaffLine(member.apiId);
      setStaff((current) => current.map((item) => item.id === member.id ? mapStaff(updated) : item));
      notify(`${member.name} 的 LINE 連結已解除，原 LINE 已無法登入。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '解除 LINE 連結失敗');
    }
  };

  const linkStaffLine = async (event: FormEvent<HTMLFormElement>, member: typeof staff[number]) => {
    event.preventDefault();
    if (!member.apiId || !canManageAll) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const lineUserId = String(data.get('lineUserId') || '').trim();
    const actionLabel = member.lineConnected ? '撤銷原連結並改綁' : '串接';
    if (!window.confirm(`確定${actionLabel} ${member.name} 的 LINE？成功時系統會立即傳送通知。`)) return;
    try {
      const updated = await api.linkStaffLine(member.apiId, lineUserId);
      setStaff((current) => current.map((item) => item.id === member.id ? mapStaff(updated) : item));
      notify(`${member.name} 的 LINE 已串接，測試通知已成功送達。`);
      form.reset();
    } catch (error) {
      notify(error instanceof Error ? error.message : 'LINE 串接失敗');
    }
  };

  const confirmBookingRequest = async (request: RawBookingRequest) => {
    try {
      const result = await api.confirmBookingRequest(request.id);
      setBookingRequests((current) => current.map((item) => item.id === request.id ? result.booking_request : item));
      setAppointments((current) => [mapAppointment(result.appointment), ...current.filter((item) => item.apiId !== result.appointment.id)]);
      setModal(null);
      notify(`${request.request_id} 已確認並成立正式訂單。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '確認預約通知失敗');
    }
  };

  const cancelBookingRequest = async (request: RawBookingRequest) => {
    if (!window.confirm(`確定取消預約通知 ${request.request_id}？`)) return;
    try {
      const updated = await api.cancelBookingRequest(request.id, '後台客服取消');
      setBookingRequests((current) => current.map((item) => item.id === request.id ? updated : item));
      setModal(null);
      notify(`${request.request_id} 已取消。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '取消預約通知失敗');
    }
  };

  const saveBookingRequest = async (event: FormEvent<HTMLFormElement>, request: RawBookingRequest) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const updated = await api.updateBookingRequest(request.id, {
        customer_name: String(data.get('customerName') || '').trim(),
        phone: String(data.get('phone') || '').trim(),
        staff_id: Number(data.get('staffId') || 0) || null,
        service_plan_id: Number(data.get('servicePlanId') || 0),
        promotion_id: Number(data.get('promotionId') || 0) || null,
        start_time: String(data.get('startTime')),
        notes: String(data.get('notes') || '').trim() || null,
        review_note: String(data.get('reviewNote') || '').trim() || null,
      });
      setBookingRequests((current) => current.map((item) => item.id === request.id ? updated : item));
      setModal(null);
      notify(`${request.request_id} 已更新，仍等待確認。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '修改預約通知失敗');
    }
  };

  const permanentlyDeleteStaff = async (event: FormEvent<HTMLFormElement>, member: StaffMember) => {
    event.preventDefault();
    if (!member.apiId || !canManageAll) return notify('永久刪除只開放店長或 Admin 使用。');
    const data = new FormData(event.currentTarget);
    const reason = String(data.get('reason') || '').trim();
    try {
      await api.deleteStaff(member.apiId, reason);
      setStaff((current) => current.filter((item) => item.id !== member.id));
      setModal(null);
      notify(`${member.name} 已永久刪除。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '永久刪除員工失敗');
    }
  };

  const assignReturnRuleSet = async (member: typeof staff[number], setId: number) => {
    if (!member.apiId || !canManageAll) return;
    try {
      const updated = await api.updateStaff(member.apiId, { return_rule_set_id: setId });
      setStaff((current) => current.map((item) => item.id === member.id ? mapStaff(updated) : item));
      notify(`${member.name} 已套用所選回帳表。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '回帳表指派失敗');
    }
  };

  const addPromotion = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    if (appMode === 'live') {
      try {
        const created = await api.createPromotion({
          name: String(data.get('name')),
          calculation_type: String(data.get('calculationType')),
          value: Number(data.get('value')),
          starts_at: data.get('startsAt') ? `${data.get('startsAt')}T00:00:00` : null,
          ends_at: data.get('endsAt') ? `${data.get('endsAt')}T23:59:59` : null,
        });
        setPromotions((current) => [...current, mapPromotion(created)]);
        setModal(null);
        notify('優惠規則已保存到 MySQL。');
      } catch (error) {
        notify(error instanceof Error ? error.message : '新增優惠失敗');
      }
      return;
    }
    notify('目前未連線至資料庫，不能新增優惠。');
  };

  const savePromotion = async (event: FormEvent<HTMLFormElement>, id: string) => {
    event.preventDefault();
    const item = promotions.find((promotion) => promotion.id === id);
    if (!item?.apiId || !canManageAll) return;
    const data = new FormData(event.currentTarget);
    try {
      const updated = await api.updatePromotion(item.apiId, { name: String(data.get('name')), calculation_type: String(data.get('calculationType')), value: Number(data.get('value')), active: data.get('active') === 'on', description: String(data.get('description') || '') });
      setPromotions((current) => current.map((promotion) => promotion.id === id ? mapPromotion(updated) : promotion));
      setModal(null);
      notify('優惠已更新並同步給 LINE Bot 選單。');
    } catch (error) {
      notify(error instanceof Error ? error.message : '優惠更新失敗');
    }
  };

  const saveOwnAccount = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!identity) return;
    const data = new FormData(event.currentTarget);
    const newPin = String(data.get('newPin') || '');
    const confirmPin = String(data.get('confirmPin') || '');
    if (newPin && newPin !== confirmPin) return notify('兩次輸入的新 PIN 不一致。');
    try {
      await api.updateOwnAccount({
        current_pin: String(data.get('currentPin') || ''),
        username: String(data.get('username') || '').trim(),
        display_name: String(data.get('displayName') || '').trim(),
        new_pin: newPin || undefined,
      });
      window.sessionStorage.removeItem('equalspa-admin-token');
      setModal(null);
      setToken('');
      setIdentity(null);
      setRole('viewer');
      setAppMode('login');
      notify('帳密已更新，請使用新資料重新登入。');
    } catch (error) {
      notify(error instanceof Error ? error.message : '帳密更新失敗');
    }
  };

  const saveReturnRule = async (event: FormEvent<HTMLFormElement>, setId: number, ruleId: number) => {
    event.preventDefault();
    if (!canManageAll) return;
    const data = new FormData(event.currentTarget);
    try {
      await api.updateReturnRule(ruleId, { name: String(data.get('name')), amount: Number(data.get('amount')), duration_minutes: Number(data.get('duration')), active: data.get('active') === 'on' });
      setReturnRuleSets((current) => current.map((set) => set.id === setId ? { ...set, rules: set.rules.map((rule) => rule.id === ruleId ? { ...rule, name: String(data.get('name')), amount: Number(data.get('amount')), duration_minutes: Number(data.get('duration')), active: data.get('active') === 'on' } : rule) } : set));
      setModal(null);
      notify('回帳規則已更新。');
    } catch (error) {
      notify(error instanceof Error ? error.message : '回帳規則更新失敗');
    }
  };

  const addAdminUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canCreateUsers) {
      notify('只有 Admin 或店長可以新增後台使用者。');
      return;
    }
    const data = new FormData(event.currentTarget);
    if (appMode === 'live') {
      try {
        const roleName = role === 'manager' ? '客服' : String(data.get('role'));
        const created = await api.createUser({
          display_name: String(data.get('displayName')),
          username: String(data.get('username')),
          role: roleName === 'Admin' ? 'admin' : roleName === '店長' ? 'manager' : 'clerk',
          pin: String(data.get('pin')),
          can_override_time_rules: roleName === '客服' && data.get('canOverrideTimeRules') === 'on',
        });
        setAdminUsers((current) => [...current, mapAdminUser(created)]);
        setModal(null);
        notify('後台使用者已建立；PIN 只保存 Argon2 雜湊。');
      } catch (error) {
        notify(error instanceof Error ? error.message : '新增使用者失敗');
      }
      return;
    }
    notify('目前未連線至資料庫，不能新增使用者。');
  };

  const deactivateAdminUser = async (user: (typeof adminUsers)[number]) => {
    if (!user.isActive || appMode !== 'live') return;
    const allowed = role === 'admin' || role === 'manager';
    if (!allowed || user.id === identity?.id) return notify('你沒有權限刪除這個帳號。');
    if (!window.confirm(`確定要永久刪除 ${user.displayName}（@${user.username}）嗎？`)) return;
    try {
      await api.deactivateUser(user.id);
      setAdminUsers((current) => current.filter((item) => item.id !== user.id));
      notify(`${user.displayName} 已永久刪除，既有登入也已失效。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '刪除帳號失敗');
    }
  };

  const toggleTimeOverridePermission = async (user: (typeof adminUsers)[number]) => {
    if (appMode !== 'live' || user.roleKey !== 'clerk' || !canCreateUsers) return;
    try {
      const updated = mapAdminUser(await api.updateUserPermissions(user.id, !user.canOverrideTimeRules));
      setAdminUsers((current) => current.map((item) => item.id === updated.id ? updated : item));
      notify(updated.canOverrideTimeRules ? `${user.displayName} 已可強制略過時間與撞期限制。` : `${user.displayName} 已恢復一般時間與撞期限制。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '更新客服強制權限失敗');
    }
  };

  const renderDashboard = () => {
    const confirmedToday = todayAppointments.filter((item) => item.status === '已確認');
    const completedToday = todayAppointments.filter((item) => item.status === '已完成');
    const pendingVenue = todayAppointments.filter((item) => item.location === '待確認' || item.room === '待確認');
    const metrics = [
      { label: '今日預約', value: String(todayAppointments.length), note: `含 ${confirmedToday.length} 筆已確認` },
      { label: '已確認', value: String(confirmedToday.length), note: `${confirmedToday.filter((item) => item.location === '店內').length} 筆店內服務` },
      { label: '已完成', value: String(completedToday.length), note: isViewer ? '金額已隱藏' : `共 ${formatCurrency(completedToday.reduce((sum, item) => sum + item.total, 0))}` },
      sensitiveVisible
        ? { label: '今日營收', value: completedRevenue.toLocaleString('zh-TW'), note: '依已完成訂單計算', currency: true }
        : isStaffUser
          ? { label: '我的訂單金額', value: completedRevenue.toLocaleString('zh-TW'), note: '僅顯示自己的訂單', currency: true }
          : { label: '帳務資訊', value: '—', note: '登入授權帳號後顯示' },
    ];
    return (
      <div className="content-grid">
        <div className="main-column">
          <section className="metric-grid" aria-label="今日摘要">
            {metrics.map((metric) => <article className="metric-card" key={metric.label}><p>{metric.label}</p><strong>{metric.currency && <small>NT$</small>}{metric.value}</strong><span>{metric.note}</span></article>)}
          </section>
          <section className="panel schedule-panel">
            <div className="panel-heading"><div><p className="eyebrow">TODAY’S FLOW</p><h2>今日預約進度</h2></div><button className="text-button" onClick={() => navigateTo('appointments')}>查看全部 →</button></div>
            <div className="appointment-list">
              {todayAppointments.slice(0, 6).map((appointment) => (
                <button className="appointment-row interactive" key={appointment.id} onClick={() => setModal({ type: 'appointmentDetail', id: appointment.id })}>
                  <div className="time-block"><strong>{appointment.start}</strong><span>{appointment.end}</span></div>
                  <div className="staff-block"><span className="staff-avatar">{appointment.staff.slice(0, 1)}</span><div><strong>{appointment.staff}</strong><span>{appointment.customer}</span></div></div>
                  <div className="service-block"><strong>{appointment.service}</strong><span>{appointment.room}</span></div>
                  <StatusPill status={appointment.status} /><span className="row-arrow">›</span>
                </button>
              ))}
              {todayAppointments.length === 0 && <div className="empty-state">今天尚無預約。</div>}
            </div>
          </section>
        </div>
        <aside className="right-column">
          <section className="panel room-panel">
            <div className="panel-heading compact"><div><p className="eyebrow">ROOM STATUS</p><h2>今日房間安排</h2></div><span className="room-count">{confirmedToday.filter((item) => item.location === '店內').length} / {rooms.length}</span></div>
            {rooms.map((room) => { const appointment = confirmedToday.find((item) => item.room === room.name); return <div className={appointment ? 'room-card occupied' : 'room-card'} key={room.id}><span>{room.name}</span><strong>{appointment ? `${appointment.staff}・已確認` : '尚無安排'}</strong><small>{appointment ? `${appointment.start}–${appointment.end}` : '等待預約'}</small></div>; })}
            {rooms.length === 0 && <div className="empty-state">資料庫尚未建立房間資料。</div>}
            {pendingVenue.length > 0 && <div className="notice">今天有 {pendingVenue.length} 筆預約尚未分配場地，請由客服確認。</div>}
          </section>
          <section className="panel action-panel">
            <p className="eyebrow">NEEDS ATTENTION</p><h2>需要處理</h2>
            <button onClick={() => sensitiveVisible ? navigateTo('checkout') : notify('帳務資訊需使用客服、店長或 Admin 帳號登入。')}><span className="action-number">{pendingCheckout.length}</span><div><strong>可完成訂單</strong><small>{sensitiveVisible ? '記錄付款後直接完成' : '帳務內容已隱藏'}</small></div><b>→</b></button>
            <button onClick={() => navigateTo('appointments')}><span className="action-number amber">{pendingVenue.length}</span><div><strong>場地待確認</strong><small>{pendingVenue.length ? '請開啟預約明細處理' : '目前沒有待確認場地'}</small></div><b>→</b></button>
          </section>
        </aside>
      </div>
    );
  };

  const renderAppointments = () => (
    <div className="appointments-layout">
    {appMode === 'live' && <section className="panel table-panel booking-request-panel">
      <div className="panel-heading"><div><p className="eyebrow">REVIEW QUEUE</p><h2>待確認預約通知</h2></div><span className="subtle-label">{bookingRequests.filter((item) => item.status === 'pending').length} 筆待處理</span></div>
      <BulkTools entity="booking_requests" ids={bookingRequests.filter((item) => item.status === 'pending').map((item) => item.id)} label="預約通知" />
      <div className="booking-request-list">
        {bookingRequests.filter((item) => item.status === 'pending').map((item) => <article className="booking-request-card" key={item.id}>
          <label className="selection-check"><input type="checkbox" checked={(selectedIds.booking_requests || []).includes(item.id)} onChange={() => toggleSelected('booking_requests', item.id)} /><span>選取</span></label><div><strong>{item.request_id}・{item.customer_name}</strong><small>{item.start_time.replace('T', ' ').slice(0, 16)}・{item.staff_name}・{item.service_name}</small><span>這是預約通知，尚未占用師傅或房間。</span></div>
          <div className="booking-request-actions"><button className="primary-button" onClick={() => confirmBookingRequest(item)}>確認</button><button className="secondary-button" onClick={() => setModal({ type: 'bookingRequest', id: item.id })}>修改</button><button className="danger-button" onClick={() => cancelBookingRequest(item)}>取消</button></div>
        </article>)}
        {bookingRequests.every((item) => item.status !== 'pending') && <div className="empty-state">目前沒有待確認的預約通知。</div>}
      </div>
    </section>}
    <section className="panel table-panel">
      <div className="toolbar">
        <div className="search-box"><span>⌕</span><input value={appointmentSearch} onChange={(event) => setAppointmentSearch(event.target.value)} placeholder="搜尋訂單、客戶、電話或師傅" /></div>
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>{['全部', '待確認', '已確認', '已完成'].map((status) => <option key={status}>{status}</option>)}</select>
        {appMode === 'live' && <button className="secondary-button" onClick={() => exportCsv('appointments')}>⇩ 匯出</button>}
      </div>
      <BulkTools entity="appointments" ids={filteredAppointments.flatMap((item) => item.apiId ? [item.apiId] : [])} label="預約／訂單" />
      <div className="data-table appointment-table">
        <div className="table-head"><span>時間／訂單</span><span>客戶</span><span>師傅／方案</span><span>場地</span><span>狀態</span><span>金額</span></div>
        {filteredAppointments.map((item) => (
          <div className="table-row interactive" role="button" tabIndex={0} key={item.id} onClick={() => setModal({ type: 'appointmentDetail', id: item.id })}>
            <span><label className="selection-check" onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={!!item.apiId && (selectedIds.appointments || []).includes(item.apiId)} onChange={() => item.apiId && toggleSelected('appointments', item.apiId)} /><span>選取</span></label><strong>{item.date.slice(5)}　{item.start}–{item.end}</strong><small>{item.id}</small></span>
            <span><strong>{item.customer}</strong><small>{item.phone}</small></span>
            <span><strong>{item.staff}</strong><small>{item.service}</small></span>
            <span><strong>{item.location}</strong><small>{item.room}</small></span>
            <span><StatusPill status={item.status} /></span>
            <span><strong>{isViewer ? '—' : formatCurrency(item.total)}</strong><small>{isViewer ? '敏感資訊已隱藏' : item.payment}</small></span>
          </div>
        ))}
      </div>
      {filteredAppointments.length === 0 && <div className="empty-state">沒有符合條件的預約。</div>}
    </section>
    </div>
  );

  const renderSchedule = () => {
    const days = week === 'current' ? currentWeekDays : followingWeekDays;
    const rosterStaff = pagedScheduleStaff;
    const visibleDates = new Set(days.map((item) => item.date));
    const visibleStaffIds = new Set(rosterStaff.map((item) => item.id));
    const visibleStaffNames = new Set(rosterStaff.map((item) => item.name));
    const visibleShiftIds = shifts
      .filter((item) => visibleDates.has(item.date) && (item.staffId ? visibleStaffIds.has(item.staffId) : visibleStaffNames.has(item.staff)))
      .flatMap((item) => item.apiId ? [item.apiId] : []);
    return (
      <>
        <section className="rule-banner"><div><strong>90 分鐘鎖定規則</strong><span>師傅端距開始 90 分鐘內不可新增、修改或撤銷；店長與 Admin 可填寫原因強制處理。</span></div>{appMode === 'live' && <button onClick={() => navigateTo('staffPortal')}>預覽師傅畫面</button>}</section>
        <section className="panel roster-panel">
          <div className="toolbar"><div className="segmented"><button className={week === 'current' ? 'active' : ''} onClick={() => setWeek('current')}>本週</button><button className={week === 'next' ? 'active' : ''} onClick={() => setWeek('next')}>下週</button></div><select value={scheduleCategoryFilter} onChange={(event) => setScheduleCategoryFilter(event.target.value as typeof scheduleCategoryFilter)}><option value="全部">全部師傅</option><option value="圈內師傅">圈內</option><option value="直男師傅">直男</option><option value="雙性師傅">雙性</option></select><div className="filter-note"><strong>{filteredScheduleStaff.length}</strong><span>位符合篩選</span></div><div className="toolbar-spacer" />{appMode === 'live' && <button className="secondary-button" onClick={() => exportCsv('shifts')}>⇩ 匯出班表</button>}{(canManageShifts || isStaffUser) && <button className="primary-button" onClick={() => setModal({ type: 'shift', origin: isStaffUser ? 'staff' : 'admin' })}>＋ 新增排班</button>}</div>
          <BulkTools entity="shifts" ids={visibleShiftIds} label="排班" />
          <div className="roster-grid" style={{ gridTemplateColumns: `120px repeat(${days.length}, minmax(112px, 1fr))` }}>
            <div className="roster-corner">師傅</div>
            {days.map((day) => <div className={day.date === todayIso ? 'roster-day today' : 'roster-day'} key={day.date}><strong>{day.day}</strong><span>{day.label}</span></div>)}
            {rosterStaff.map((member) => (
              <div className="roster-row" key={member.id} style={{ gridColumn: `1 / span ${days.length + 1}`, gridTemplateColumns: `120px repeat(${days.length}, minmax(112px, 1fr))` }}>
                <div className="roster-name"><span className="staff-avatar">{member.name.slice(0, 1)}</span><div><strong>{member.name}</strong><small>{member.category.replace('師傅', '')}</small></div></div>
                {days.map((day) => {
                  const dayShifts = shifts.filter((item) => (item.staffId ? item.staffId === member.id : item.staff === member.name) && item.date === day.date);
                  return <div className="roster-cell" key={day.date}>{dayShifts.map((shift) => <button className={isShiftLocked(shift) ? 'shift-card locked' : 'shift-card'} key={shift.id} onClick={() => (canManageShifts || isStaffUser) && setModal({ type: 'shiftDetail', id: shift.id, origin: isStaffUser ? 'staff' : 'admin' })}>{canManageAll && shift.apiId && <label className="selection-check" onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={(selectedIds.shifts || []).includes(shift.apiId)} onChange={() => toggleSelected('shifts', shift.apiId!)} /><span>選取</span></label>}<strong>{shiftTimeLabel(shift)}</strong><small>{isShiftLocked(shift) && !canOverrideTimeRules ? '已鎖定' : shift.source}</small></button>)}</div>;
                })}
              </div>
            ))}
          </div>
          {filteredScheduleStaff.length > 0 && <div className="pagination"><button disabled={schedulePage <= 1} onClick={() => setSchedulePage((page) => page - 1)}>上一頁</button><span>第 {schedulePage} / {schedulePageCount} 頁・每頁 10 位</span><button disabled={schedulePage >= schedulePageCount} onClick={() => setSchedulePage((page) => page + 1)}>下一頁</button></div>}
          <div className="legend"><span><i className="legend-dot normal" />可調整／可跨日</span><span><i className="legend-dot locked" />一般帳號於 90 分鐘內鎖定</span><span>排班沒有最低時數</span></div>
        </section>
      </>
    );
  };

  const renderOperations = () => {
    const columns = ['待確認', '已確認', '已完成'];
    return <><BulkTools entity="appointments" ids={appointments.flatMap((item) => item.apiId ? [item.apiId] : [])} label="訂單" /><div className="kanban">{columns.map((status) => <section className="kanban-column" key={status}><header><div><strong>{status}</strong><span>{appointments.filter((item) => item.status === status).length}</span></div></header><div className="kanban-list">{appointments.filter((item) => item.status === status).map((item) => <button className="kanban-card" key={item.id} onClick={() => setModal({ type: 'appointmentDetail', id: item.id })}><label className="selection-check" onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={!!item.apiId && (selectedIds.appointments || []).includes(item.apiId)} onChange={() => item.apiId && toggleSelected('appointments', item.apiId)} /><span>選取</span></label><span className="kanban-time">{item.start}–{item.end}</span><strong>{item.customer}・{item.staff}</strong><small>{item.service}</small><small>{item.room}</small></button>)}{appointments.filter((item) => item.status === status).length === 0 && <div className="kanban-empty">目前沒有項目</div>}</div></section>)}</div></>;
  };

  const renderCheckout = () => (
    <div className="checkout-stack">
      <div className="checkout-layout">
        <section className="panel checkout-list"><div className="panel-heading"><div><p className="eyebrow">CONFIRMED</p><h2>可完成訂單</h2></div><span className="room-count">{pendingCheckout.length}</span></div>{pendingCheckout.map((item) => <button className="checkout-row" key={item.id} onClick={() => setModal({ type: 'checkout', id: item.id })}><div><span>{item.end} 預計結束</span><strong>{item.customer}</strong><small>{item.id}・{item.staff}</small></div><div><strong>{formatCurrency(item.total)}</strong><small>{item.service}</small></div><b>記錄付款並完成 →</b></button>)}{pendingCheckout.length === 0 && <div className="empty-state">目前沒有可完成的訂單。</div>}</section>
        <aside className="panel settlement-card"><p className="eyebrow">SIMPLE FLOW</p><h2>完成即回帳</h2><p>選擇現金或轉帳並按下「確認完成訂單」後，狀態會直接改為已完成，也視為已回帳。</p></aside>
      </div>
    </div>
  );

  const renderCustomers = () => (
    <section className="panel table-panel"><div className="toolbar"><div className="search-box"><span>⌕</span><input value={customerSearch} onChange={(event) => setCustomerSearch(event.target.value)} placeholder="搜尋名稱、手機或內部識別" /></div><button className="secondary-button" onClick={() => exportCsv('customers')}>⇩ 匯出客戶</button></div><BulkTools entity="customers" ids={filteredCustomers.flatMap((item) => item.apiId ? [item.apiId] : [])} label="客戶" /><div className="data-table customer-table"><div className="table-head"><span>客戶名稱</span><span>內部識別</span><span>手機 ID</span><span>到訪</span><span>累計消費</span><span>最近到訪</span></div>{filteredCustomers.map((customer) => <div className="table-row customer-edit-row interactive" role="button" tabIndex={0} key={customer.id} onClick={() => setModal({ type: 'customer', id: customer.id })}><span><label className="selection-check" onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={!!customer.apiId && (selectedIds.customers || []).includes(customer.apiId)} onChange={() => customer.apiId && toggleSelected('customers', customer.apiId)} /><span>選取</span></label><strong>{customer.name}</strong><small>名稱可由後台或 LINE 建立</small></span><span><strong>{customer.vipSerial}</strong><small>僅限內部管理查看</small></span><span><strong>{customer.phones.join('、') || '未提供'}</strong><small>{customer.phones.length > 1 ? `${customer.phones.length} 支手機` : '主要手機'}</small></span><span><strong>{customer.visits} 次</strong></span><span><strong>{formatCurrency(customer.spent)}</strong></span><span><strong>{customer.lastVisit}</strong><small>{customer.note}</small></span></div>)}</div></section>
  );

  const renderStaff = () => (
    <section className="panel table-panel">
      <div className="toolbar"><select value={staffCategoryFilter} onChange={(event) => setStaffCategoryFilter(event.target.value as typeof staffCategoryFilter)}><option>全部</option><option>直男師傅</option><option>圈內師傅</option><option>雙性師傅</option></select><div className="filter-note"><strong>{filteredStaff.length}</strong><span>位符合篩選</span></div><div className="toolbar-spacer" />{canManageAll && <button className="primary-button" onClick={() => setModal({ type: 'staff' })}>＋ 新增員工</button>}</div>
      <BulkTools entity="staff" ids={pagedStaff.flatMap((item) => item.apiId ? [item.apiId] : [])} label="師傅" />
      <div className="staff-card-grid">{pagedStaff.map((member) => <article className={member.status === '暫時退役' ? 'staff-card retired' : 'staff-card'} key={member.id}>
        <header>{member.photoUrl ? <img className="large-avatar staff-photo" src={member.photoUrl} alt={`${member.name}師傅`} /> : <span className="large-avatar">{member.name.slice(0, 1)}</span>}<label className="selection-check"><input type="checkbox" checked={!!member.apiId && (selectedIds.staff || []).includes(member.apiId)} onChange={() => member.apiId && toggleSelected('staff', member.apiId)} /><span>選取</span></label><StatusPill status={member.status} /></header>
        <h3>{member.name}</h3><p>{member.category}・{[member.height && `${member.height} cm`, member.weight && `${member.weight} kg`, member.role].filter(Boolean).join('・') || member.id}</p>
        <div className="staff-meta"><span>{member.lineConnected ? 'LINE 已串接' : 'LINE 待串接'}</span><span>{member.isOnline ? '目前上線' : '目前下線'}</span><span>{isViewer || isStaffUser ? '公開基本資料' : '私密資料已分離'}</span></div>
        {canManageAll && returnRuleSets.length > 0 && <label className="staff-rule-select">回帳表<select value={member.returnRuleSetId || returnRuleSets[0]?.id || ''} onChange={(event) => assignReturnRuleSet(member, Number(event.target.value))}>{returnRuleSets.filter((set) => set.active).map((set) => <option key={set.id} value={set.id}>{set.name}</option>)}</select></label>}
        {canManageAll && <div className="staff-card-actions"><button className="text-button" onClick={() => setModal({ type: 'staffEdit', id: member.id })}>資料／照片</button><button className="text-button" onClick={() => toggleStaffStatus(member)}>{member.status === '在職' ? '暫時退役' : '恢復在職'}</button>{member.lineConnected && <button className="text-button" onClick={() => unlinkStaffLine(member)}>解除 LINE</button>}<button className="danger-text" onClick={() => setModal({ type: 'staffDelete', id: member.id })}>永久刪除</button></div>}
      </article>)}</div>
      {filteredStaff.length > 0 && <div className="pagination"><button disabled={staffPage <= 1} onClick={() => setStaffPage((page) => page - 1)}>上一頁</button><span>第 {staffPage} / {staffPageCount} 頁・每頁 10 位</span><button disabled={staffPage >= staffPageCount} onClick={() => setStaffPage((page) => page + 1)}>下一頁</button></div>}
      {filteredStaff.length === 0 && <div className="empty-state">資料庫目前沒有符合條件的師傅資料。</div>}
      {sensitiveVisible && <div className="privacy-note"><strong>健康資訊不顯示於此畫面</strong><span>私密欄位存放在獨立資料表，且不包含在一般匯出中。永久刪除師傅後，歷史訂單只保留當時的師傅名稱。</span></div>}
    </section>
  );

  const renderServices = () => (
    <div className="services-layout">
      <section className="panel"><div className="panel-heading"><div><p className="eyebrow">SERVICE PLANS</p><h2>服務方案</h2></div>{canManageAll && <button className="secondary-button" onClick={() => setModal({ type: 'serviceCreate' })}>＋ 新增方案</button>}</div><BulkTools entity="services" ids={plans.flatMap((item) => item.apiId ? [item.apiId] : [])} label="服務方案" /><div className="plan-grid">{plans.map((plan) => <article className={plan.active ? 'plan-card' : 'plan-card inactive'} key={plan.id}><label className="selection-check"><input type="checkbox" checked={!!plan.apiId && (selectedIds.services || []).includes(plan.apiId)} onChange={() => plan.apiId && toggleSelected('services', plan.apiId)} /><span>選取</span></label><header><span>{plan.code}</span><small>{plan.location}</small></header><h3>{plan.name}</h3><p>{plan.duration} 分鐘</p><strong>{formatCurrency(plan.price)}</strong><footer><span>{plan.canChooseStaff ? '可指定師傅' : '不指定優惠'}</span>{canManageAll && <button onClick={() => setModal({ type: 'service', id: plan.id })}>編輯</button>}</footer></article>)}</div></section>
      <section className="panel"><div className="panel-heading"><div><p className="eyebrow">PROMOTIONS</p><h2>優惠與附加費</h2></div>{canManageAll && <button className="secondary-button" onClick={() => setModal({ type: 'promotion' })}>＋ 新增規則</button>}</div><BulkTools entity="promotions" ids={promotions.flatMap((item) => item.apiId ? [item.apiId] : [])} label="優惠／附加費" /><div className="promotion-list">{promotions.map((promotion) => <article key={promotion.id}><label className="selection-check"><input type="checkbox" checked={!!promotion.apiId && (selectedIds.promotions || []).includes(promotion.apiId)} onChange={() => promotion.apiId && toggleSelected('promotions', promotion.apiId)} /><span>選取</span></label><span className="promo-icon">{promotion.kind.includes('折扣') ? '−' : '＋'}</span><div><strong>{promotion.name}</strong><small>{promotion.kind}・{promotion.period}</small></div><b>{promotion.kind === '百分比折扣' ? `${promotion.value}%` : formatCurrency(promotion.value)}</b><StatusPill status={promotion.active ? '啟用' : '停用'} />{canManageAll && <button className="text-button" onClick={() => setModal({ type: 'promotionEdit', id: promotion.id })}>編輯</button>}</article>)}</div></section>
      <section className="panel"><div className="panel-heading"><div><p className="eyebrow">ROOMS</p><h2>店內房間</h2></div>{canManageAll && <button className="secondary-button" onClick={createRoomPrompt}>＋ 新增房間</button>}</div><BulkTools entity="rooms" ids={rooms.map((item) => item.id)} label="房間" /><div className="settings-list">{rooms.map((room) => <article key={room.id}><label className="selection-check"><input type="checkbox" checked={(selectedIds.rooms || []).includes(room.id)} onChange={() => toggleSelected('rooms', room.id)} /><span>選取</span></label><div><strong>{room.name}</strong><small>店內房間</small></div>{canManageAll && <button className="text-button" onClick={() => editRoomPrompt(room)}>編輯</button>}</article>)}</div></section>
      <section className="panel"><div className="panel-heading"><div><p className="eyebrow">VENUES</p><h2>外租／外出場地</h2></div>{canManageAll && <button className="secondary-button" onClick={createVenuePrompt}>＋ 新增場地</button>}</div><BulkTools entity="venues" ids={venues.map((item) => item.id)} label="外部場地" /><div className="settings-list">{venues.map((venue) => <article key={venue.id}><label className="selection-check"><input type="checkbox" checked={(selectedIds.venues || []).includes(venue.id)} onChange={() => toggleSelected('venues', venue.id)} /><span>選取</span></label><div><strong>{venue.name}</strong><small>{venue.address || '地址尚未填寫'}</small></div>{canManageAll && <button className="text-button" onClick={() => editVenuePrompt(venue)}>編輯</button>}</article>)}</div></section>
    </div>
  );

  const renderExports = () => (
    <div className="exports-layout">
      <section className="panel export-control">
        <div className="panel-heading"><div><p className="eyebrow">EXPORT RANGE</p><h2>選擇資料期間</h2></div></div>
        <div className="form-grid two"><label>開始日期<input type="date" value={exportStart} onChange={(event) => setExportStart(event.target.value)} /></label><label>結束日期<input type="date" value={exportEnd} min={exportStart} onChange={(event) => setExportEnd(event.target.value)} /></label></div>
        <div className="export-card-grid"><button onClick={() => exportCsv('appointments')}><span>預約與訂單</span><strong>{appointments.length} 筆資料庫紀錄</strong><small>CSV・Excel 可開啟</small></button><button onClick={() => exportCsv('shifts')}><span>師傅排班</span><strong>{shifts.length} 筆資料庫紀錄</strong><small>CSV・Excel 可開啟</small></button><button onClick={() => exportCsv('customers')}><span>客戶資料</span><strong>{customers.length} 筆資料庫紀錄</strong><small>不含私密健康資訊</small></button></div>
      </section>
      <aside className="panel audit-panel"><p className="eyebrow">AUDIT LOG</p><h2>最近操作紀錄</h2><BulkTools entity="audit_logs" ids={auditLogs.map((item) => item.id)} label="操作紀錄" />{auditLogs.map((item) => <article key={item.id}><label className="selection-check"><input type="checkbox" checked={(selectedIds.audit_logs || []).includes(item.id)} onChange={() => toggleSelected('audit_logs', item.id)} /><span>選取</span></label><span>{item.actorName.slice(0, 1)}</span><div><strong>{item.actorName}・{item.action} {item.entityType}{item.entityId ? ` #${item.entityId}` : ''}</strong><small>{item.reason || '未填寫原因'}・{item.createdAt.replace('T', ' ').slice(0, 16)}</small></div></article>)}{auditLogs.length === 0 && <div className="empty-state">資料庫目前沒有操作紀錄。</div>}</aside>
    </div>
  );

  const renderUsers = () => (
    <div className="users-layout">
      <section className="panel table-panel">
        <div className="panel-heading"><div><p className="eyebrow">ADMIN USERS</p><h2>後台帳號與權限</h2></div>{canCreateUsers && <button className="primary-button" onClick={() => setModal({ type: 'user' })}>＋ 新增使用者</button>}</div>
        <BulkTools entity="users" ids={adminUsers.filter((item) => item.id !== identity?.id).map((item) => item.id)} label="後台帳號" />
        <div className="data-table users-table">
          <div className="table-head"><span>使用者</span><span>角色</span><span>狀態</span><span>最近登入</span><span>權限操作</span></div>
          {adminUsers.map((user) => {
            const canDeactivate = user.isActive && user.id !== identity?.id && (role === 'admin' || role === 'manager');
            return <div className="table-row static" key={user.username}>
              <span>{user.id !== identity?.id && <label className="selection-check"><input type="checkbox" checked={(selectedIds.users || []).includes(user.id)} onChange={() => toggleSelected('users', user.id)} /><span>選取</span></label>}<strong>{user.displayName}</strong><small>@{user.username}{user.id === identity?.id ? '・目前帳號' : ''}</small></span>
              <span><strong>{user.role}</strong></span>
              <span><StatusPill status={user.status} /></span>
              <span><strong>{user.lastLogin}</strong></span>
              <span className="access-actions">{user.roleKey === 'clerk' && user.isActive && <button className={user.canOverrideTimeRules ? 'access-warning active' : 'access-warning'} onClick={() => toggleTimeOverridePermission(user)}>{user.canOverrideTimeRules ? '關閉強制時間權限' : '開啟強制時間權限'}</button>}{canDeactivate ? <button className="access-danger" onClick={() => deactivateAdminUser(user)}>永久刪除</button> : <small>{user.id === identity?.id ? '目前帳號' : '不可操作'}</small>}</span>
            </div>;
          })}
        </div>
      </section>
      <aside className="panel security-card"><p className="eyebrow">LOGIN SECURITY</p><h2>數字 PIN 安全設定</h2><ul><li>PIN 只保存 Argon2 雜湊</li><li>連續錯誤 5 次鎖定 15 分鐘</li><li>Bearer 工作階段 8 小時到期</li><li>永久刪除後立即撤銷既有登入</li></ul><div className="security-footnote">你可從左下角「登入資訊」自行修改帳號、名稱與 PIN。</div></aside>
      <section className="panel permission-panel"><div className="panel-heading"><div><p className="eyebrow">ROLE MATRIX</p><h2>權限對照</h2></div></div><div className="permission-grid"><strong>功能</strong><strong>Admin</strong><strong>店長</strong><strong>客服</strong>{['預約與結帳', '新增／撤銷排班', '略過時間與撞期限制', '新增／退役／永久刪除員工', '修改價格優惠', '新增帳號', '停用客服帳號', '系統與稽核'].flatMap((label, index) => [<span key={`${label}-label`}>{label}</span>, <b key={`${label}-admin`}>✓</b>, <b key={`${label}-manager`}>{index === 7 ? '查看' : index === 5 ? '限客服' : '✓'}</b>, <b className="limited" key={`${label}-clerk`}>{index === 2 ? '可個別開啟' : index < 2 ? '部分' : '—'}</b>])}</div></section>
    </div>
  );

  const renderStaffPortal = () => {
    const previewStaff = staff.find((item) => item.status === '在職');
    const previewShifts = previewStaff ? shifts.filter((item) => item.staffId === previewStaff.id) : [];
    return <div className="portal-layout"><section className="phone-preview"><header><span className="brand-seal">E</span><div><small>伊果 SPA 師傅班表</small><strong>{previewStaff ? `${previewStaff.name}，辛苦了` : '尚無在職師傅'}</strong></div><span className="link-badge">資料庫預覽</span></header><div className="portal-rule"><strong>排班提醒</strong><span>排班可跨日且沒有最低時數；開始前 90 分鐘內不可自行變更。</span></div><div className="portal-week"><div className="portal-week-head"><strong>我的班表</strong></div>{previewShifts.map((shift) => <div className="portal-shift" key={shift.id}><span><strong>{shift.date.slice(5).replace('-', '/')}</strong><small>{shift.date === todayIso ? '今天' : '已排班'}</small></span><div><strong>{shiftTimeLabel(shift)}</strong><small>共 {Number((shiftDurationMinutes(shift) / 60).toFixed(2))} 小時</small></div><StatusPill status={isShiftLocked(shift) ? '已鎖定' : '可調整'} /></div>)}{previewShifts.length === 0 && <div className="empty-state">此師傅目前沒有班表。</div>}</div></section><aside className="panel portal-notes"><p className="eyebrow">SIGNED LINE LINK</p><h2>LINE 安全登入，不是公開網址</h2><p>由 LINE Bot 傳送每位師傅自己的不可猜測登入連結，只能看到與修改自己的班表。</p><div><strong>可查看</strong><span>自己的本週／下週班表</span></div><div><strong>可操作</strong><span>新增任意長度、可跨日的班；撤銷未鎖定班</span></div><div><strong>看不到</strong><span>其他師傅、客戶電話、健康資料、營收</span></div></aside></div>;
  };

  const renderActiveSection = () => {
    switch (active) {
      case 'appointments': return renderAppointments();
      case 'schedule': return renderSchedule();
      case 'operations': return renderOperations();
      case 'checkout': return renderCheckout();
      case 'customers': return renderCustomers();
      case 'staff': return renderStaff();
      case 'services': return renderServices();
      case 'exports': return renderExports();
      case 'users': return renderUsers();
      case 'staffPortal': return renderStaffPortal();
      default: return renderDashboard();
    }
  };

  if (appMode === 'checking') {
    return <main className="auth-shell"><section className="auth-card"><span className="brand-seal">E</span><p className="eyebrow">EQUAL SPA</p><h1>正在讀取管理資料</h1><p>正在連線 FastAPI 與 MySQL。</p><div className="auth-loading" /></section></main>;
  }

  if (appMode === 'login' || appMode === 'unavailable') {
    return <main className="auth-shell"><section className="auth-card auth-login-card"><span className="brand-seal">E</span><p className="eyebrow">EQUAL SPA</p><h1>登入伊果 SPA 營運後台</h1><p>客服、店長與 Admin 使用管理帳號；師傅只需輸入自己的手機 ID。</p>{connectionError && <div className="auth-error">{connectionError}</div>}<div className="account-login-grid auth-login-grid"><form className="modal-form account-login-card" onSubmit={login}><p className="eyebrow">MANAGEMENT</p><h3>客服／店長／Admin</h3><label>登入帳號<input name="username" required autoCapitalize="none" autoComplete="username" placeholder="例如：admin" autoFocus /></label><label>數字 PIN<input name="pin" required type="password" inputMode="numeric" pattern="[0-9]+" minLength={4} autoComplete="current-password" /></label><button className="primary-button full" disabled={loginBusy}>{loginBusy ? '登入中…' : '管理帳號登入'}</button></form><form className="modal-form account-login-card" onSubmit={loginStaff}><p className="eyebrow">STAFF</p><h3>師傅手機 ID 登入</h3><label>手機 ID<input name="staffPhone" required inputMode="tel" pattern="09[0-9]{8}" autoComplete="tel" placeholder="09xxxxxxxx" /></label><button className="secondary-button full" disabled={loginBusy}>{loginBusy ? '登入中…' : '以員工身分進入'}</button></form></div>{loginError && <div className="auth-error modal-auth-error">{loginError}</div>}<small>從 LINE Bot 開啟師傅後台時，仍會使用安全連結直接登入。</small></section></main>;
  }

  if (appMode === 'staffLink') {
    return <main className="staff-standalone"><section className="staff-portal-card"><header><span className="brand-seal">E</span><div><small>伊果 SPA 師傅班表</small><strong>{staffPortalName}，辛苦了</strong></div><span className="link-badge">專屬連結</span></header><div className="portal-rule"><strong>排班提醒</strong><span>可跨日且沒有最低時數；開始前 90 分鐘內不可自行新增或撤銷，請聯絡店長。</span></div>{staffPortalError ? <div className="auth-error">{staffPortalError}</div> : <><form className="public-shift-form" onSubmit={(event) => addShift(event, 'staff')}><label>開始日期<input name="startDate" type="date" min={todayIso} defaultValue={bookingDefault.date} required /></label><label>開始時間<ClockSelect name="start" defaultValue={bookingDefault.time} /></label><label>結束日期<input name="endDate" type="date" min={todayIso} defaultValue={shiftEndDefault.date} required /></label><label>結束時間<ClockSelect name="end" defaultValue={shiftEndDefault.time} /></label><button className="primary-button" type="submit">新增排班</button></form><div className="portal-week"><div className="portal-week-head"><strong>我的班表</strong><span>{shifts.length} 段</span></div>{shifts.map((shift) => <article className="portal-shift public-shift" key={shift.id}><span><strong>{shift.date.slice(5).replace('-', '/')}</strong><small>{isShiftLocked(shift) ? '已鎖定' : '可調整'}</small></span><div><strong>{shiftTimeLabel(shift)}</strong><small>共 {Number((shiftDurationMinutes(shift) / 60).toFixed(2))} 小時</small></div><button className="danger-text" disabled={isShiftLocked(shift)} onClick={() => removeShift(shift, 'staff')}>{isShiftLocked(shift) ? '洽店長' : '撤銷'}</button></article>)}{shifts.length === 0 && <div className="empty-state">本週與下週尚未排班。</div>}</div></>}</section>{toast && <div className="toast" role="status"><span>✓</span>{toast}</div>}</main>;
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <button className="brand-mark" onClick={() => navigateTo('dashboard')}><span className="brand-seal">E</span><div><strong>伊果 SPA</strong><small>EQUAL OPERATIONS</small></div></button>
        <div className="nav-scroll">{visibleNavGroups.map((group) => <nav aria-label={group.label} key={group.label}><p>{group.label}</p>{group.items.map((item) => <button className={active === item.id ? 'nav-item active' : 'nav-item'} key={item.id} onClick={() => navigateTo(item.id)}><span className="nav-glyph">{item.glyph}</span>{item.label}</button>)}</nav>)}</div>
        {appMode === 'live' && <button className={active === 'staffPortal' ? 'portal-link active' : 'portal-link'} onClick={() => navigateTo('staffPortal')}><span>↗</span><div><strong>師傅班表連結</strong><small>LINE 安全登入預覽</small></div></button>}
        <div className="sidebar-user account-entry" onClick={() => setModal({ type: 'account' })} role="button" tabIndex={0}><span className="avatar">{role === 'admin' ? 'A' : role === 'manager' ? 'J' : role === 'clerk' ? '客' : role === 'staff' ? '師' : '？'}</span><div><strong>{identity?.display_name || staffIdentity?.name || '登入資訊'}</strong><small>{role === 'admin' ? '系統管理員' : role === 'manager' ? '店長' : role === 'clerk' ? '客服' : role === 'staff' ? '員工' : '未登入'}</small></div>{(appMode === 'live' || appMode === 'staff') ? <button className="logout-button" onClick={(event) => { event.stopPropagation(); logout(); }}>登出</button> : <button className="logout-button" onClick={(event) => { event.stopPropagation(); setModal({ type: 'account' }); }}>登入</button>}</div>
      </aside>

      <section className="workspace">
        <div className={(appMode === 'live' || appMode === 'staff') ? 'prototype-ribbon live-ribbon' : 'prototype-ribbon'}><span>{appMode === 'live' ? '管理帳號' : appMode === 'staff' ? '員工模式' : '資料庫未連線'}</span>{appMode === 'live' ? '操作會經 FastAPI 權限驗證並保存到 MySQL。' : appMode === 'staff' ? '只顯示自己的班表與訂單，帳務總覽已隱藏。' : connectionError}</div>
        <header className="topbar"><div><p className="eyebrow">{active === 'dashboard' ? todayLabel : headings[active].eyebrow}</p><h1>{headings[active].title}</h1><span>{active === 'dashboard' ? `目前登入：${currentLoginLabel}` : headings[active].description}</span></div><div className="topbar-actions"><button className="icon-button" aria-label="通知" onClick={() => notify('目前沒有新的系統通知。')}>●</button>{canCreateAppointments && !['staffPortal', 'users'].includes(active) && <button className="primary-button" onClick={() => setModal({ type: 'appointment' })}>＋ 新增預約</button>}</div></header>
        {renderActiveSection()}
      </section>

      {toast && <div className="toast" role="status"><span>✓</span>{toast}</div>}

      {modal?.type === 'account' && <Modal title="登入資訊" subtitle={identity ? '可自行修改顯示名稱、登入帳號與數字 PIN。' : '師傅只使用手機 ID；客服與管理者使用帳號及 PIN。'} onClose={() => setModal(null)} wide>{identity ? <form className="modal-form" onSubmit={saveOwnAccount}><div className="form-grid two"><label>顯示名稱<input name="displayName" defaultValue={identity.display_name} required /></label><label>登入帳號<input name="username" defaultValue={identity.username} required autoCapitalize="none" /></label><label>目前 PIN<input name="currentPin" required type="password" inputMode="numeric" pattern="[0-9]+" minLength={4} /></label><label>新 PIN（不修改可留空）<input name="newPin" type="password" inputMode="numeric" pattern="[0-9]*" minLength={4} maxLength={12} /></label><label>再次輸入新 PIN<input name="confirmPin" type="password" inputMode="numeric" pattern="[0-9]*" minLength={4} maxLength={12} /></label></div><div className="form-note">儲存後會撤銷目前工作階段，請使用新帳密重新登入。</div><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button className="primary-button">更新帳密</button></footer></form> : <><div className="account-login-grid"><form className="modal-form account-login-card" onSubmit={login}><p className="eyebrow">MANAGEMENT</p><h3>客服／店長／Admin</h3><label>登入帳號<input name="username" required autoCapitalize="none" autoComplete="username" placeholder="例如：admin" /></label><label>數字 PIN<input name="pin" required type="password" inputMode="numeric" pattern="[0-9]+" minLength={4} autoComplete="current-password" /></label><button className="primary-button full" disabled={loginBusy}>{loginBusy ? '登入中…' : '管理帳號登入'}</button></form><form className="modal-form account-login-card" onSubmit={loginStaff}><p className="eyebrow">STAFF</p><h3>師傅手機 ID 登入</h3><label>手機 ID<input name="staffPhone" required inputMode="tel" pattern="09[0-9]{8}" autoComplete="tel" placeholder="09xxxxxxxx" /></label><button className="secondary-button full" disabled={loginBusy}>{loginBusy ? '登入中…' : '以員工身分進入'}</button></form></div>{loginError && <div className="auth-error modal-auth-error">{loginError}</div>}<div className="form-note">從 LINE Bot 開啟師傅後台時會以安全連結直接登入，不會再出現登入畫面。</div></>}</Modal>}

      {modal?.type === 'appointment' && <Modal title="新增預約" subtitle={canOverrideTimeRules ? '目前帳號可略過提前時間及師傅／房間撞期限制。' : '一般帳號最少提前 90 分鐘，並檢查師傅與房間衝突。'} onClose={() => setModal(null)} wide><form className="modal-form" onSubmit={addAppointment}><div className="form-grid two"><label>客戶姓名<input name="customer" required placeholder="例如：王先生" /></label><label>手機號碼<input name="phone" required inputMode="numeric" pattern="09[0-9]{8}" placeholder="09xxxxxxxx" /></label><label>日期<input name="date" type="date" min={canOverrideTimeRules ? undefined : todayIso} defaultValue={bookingDefault.date} required /></label><label>開始時間<input name="start" type="time" defaultValue={bookingDefault.time} required /></label><label>服務方案<select name="serviceId" defaultValue={plans.find((item) => item.code === 'C')?.id}>{plans.filter((item) => item.active).map((plan) => <option value={plan.id} key={plan.id}>{plan.code}・{plan.name}｜{plan.duration} 分｜{formatCurrency(plan.price)}</option>)}</select></label><label>優惠<select name="promotionId" defaultValue="0"><option value="0">不使用優惠</option>{promotions.filter((item) => item.active && item.kind.includes('折扣')).map((item) => <option key={item.id} value={item.apiId}>{item.name}｜{item.kind === '百分比折扣' ? `${item.value}%` : `折 ${formatCurrency(item.value)}`}</option>)}</select></label><label>指派師傅<select name="staff" defaultValue={staff.find((item) => item.status === '在職')?.id}>{staff.filter((item) => item.status === '在職').map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label>場地／房間<select name="room" defaultValue={rooms[0]?.name}>{rooms.map((room) => <option key={room.id}>{room.name}</option>)}{venues.filter((venue) => venue.active).map((venue) => <option key={`venue-${venue.id}`}>{venue.name}</option>)}<option>待確認</option></select></label><label className="span-two">客服備註<textarea name="note" rows={3} placeholder="不公開給客戶的內部備註" /></label></div><div className="form-note">{canOverrideTimeRules ? '這筆訂單會以管理強制權限建立，仍會留下稽核紀錄。' : '例如 09:00 當下最早可預約 10:30；後端也會阻止重疊或過近的時間。'}</div><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button className="primary-button" type="submit">建立預約</button></footer></form></Modal>}

      {modal?.type === 'appointmentDetail' && selectedAppointment && <Modal title={selectedAppointment.id} subtitle={`${selectedAppointment.date}　${selectedAppointment.start}–${selectedAppointment.end}`} onClose={() => setModal(null)}><div className="detail-stack"><div className="detail-hero"><div><span>客戶</span><strong>{selectedAppointment.customer}</strong><small>{selectedAppointment.customerSerial ? `${selectedAppointment.customerSerial}（內部識別）・` : ''}{selectedAppointment.phone}</small></div><StatusPill status={selectedAppointment.status} /></div><dl><div><dt>師傅</dt><dd>{selectedAppointment.staff}</dd></div><div><dt>服務方案</dt><dd>{selectedAppointment.service}</dd></div><div><dt>優惠</dt><dd>{selectedAppointment.promotionName || '未使用'}</dd></div><div><dt>場地</dt><dd>{selectedAppointment.location}・{selectedAppointment.room}</dd></div><div><dt>應收金額</dt><dd>{formatCurrency(selectedAppointment.total)}</dd></div><div><dt>付款狀態</dt><dd>{selectedAppointment.payment}</dd></div></dl>{selectedAppointment.note && <div className="detail-note"><strong>客服備註</strong><p>{selectedAppointment.note}</p></div>}<div className="status-actions">{canEditAppointments && <button onClick={() => setModal({ type: 'appointmentEdit', id: selectedAppointment.id })}>編輯整張訂單</button>}{canEditAppointments && selectedAppointment.status !== '已完成' && <button onClick={() => setModal({ type: 'checkout', id: selectedAppointment.id })}>記錄付款並完成</button>}</div></div></Modal>}

      {modal?.type === 'appointmentEdit' && selectedAppointment && <Modal title={`編輯 ${selectedAppointment.id}`} subtitle={canManageAll ? '店長與 Admin 可修改整張訂單所有欄位。' : '客服可調整預約與服務內容，金額需由店長或 Admin 處理。'} onClose={() => setModal(null)} wide><form className="modal-form" onSubmit={(event) => saveAppointmentEdit(event, selectedAppointment)}><div className="form-grid two"><label>客戶姓名<input name="customer" defaultValue={selectedAppointment.customer} required /></label><label>手機號碼<input name="phone" defaultValue={selectedAppointment.phone} required /></label><label>日期<input name="date" type="date" defaultValue={selectedAppointment.date} required /></label><label>開始時間<input name="start" type="time" defaultValue={selectedAppointment.start} required /></label><label>服務方案<select name="serviceId" defaultValue={selectedAppointment.serviceId}>{plans.map((plan) => <option key={plan.id} value={plan.apiId}>{plan.code}・{plan.name}</option>)}</select></label><label>優惠<select name="promotionId" defaultValue={selectedAppointment.promotionId || '0'}><option value="0">不使用優惠</option>{promotions.map((promotion) => <option key={promotion.id} value={promotion.apiId}>{promotion.name}</option>)}</select></label><label>指派師傅<select name="staffId" defaultValue={selectedAppointment.staffId}>{staff.filter((item) => item.status === '在職').map((item) => <option key={item.id} value={item.apiId}>{item.name}</option>)}</select></label><label>場地／房間<select name="room" defaultValue={selectedAppointment.room}>{rooms.map((room) => <option key={room.id}>{room.name}</option>)}{venues.map((venue) => <option key={`venue-${venue.id}`}>{venue.name}</option>)}<option>待確認</option></select></label><label>訂單狀態<select name="status" defaultValue={selectedAppointment.status}>{['待確認', '已確認', '已完成'].map((status) => <option key={status}>{status}</option>)}</select></label>{canManageAll && <><label>原價<input name="basePrice" type="number" min="0" defaultValue={selectedAppointment.basePrice || 0} /></label><label>折扣<input name="discountAmount" type="number" min="0" defaultValue={selectedAppointment.discountAmount || 0} /></label><label>加價<input name="extraAmount" type="number" min="0" defaultValue={selectedAppointment.extraAmount || 0} /></label><label>訂單總額<input name="totalAmount" type="number" min="0" defaultValue={selectedAppointment.total} /></label></>}<label className="span-two">客服備註<textarea name="note" rows={3} defaultValue={selectedAppointment.note || ''} /></label><label className="span-two">修改原因<input name="reason" placeholder="例如：客戶改期、人工修正優惠" /></label></div><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button className="primary-button">儲存訂單</button></footer></form></Modal>}

      {modal?.type === 'shift' && <Modal title={modal.origin === 'staff' ? '新增我的排班' : '新增師傅排班'} subtitle={modal.origin === 'staff' || !canOverrideTimeRules ? '可跨日且沒有最低時數；一般帳號需遵守 90 分鐘鎖定與撞期規則。' : '可跨日且沒有最低時數；目前帳號可略過時間與撞期限制。'} onClose={() => setModal(null)}><form className="modal-form" onSubmit={(event) => addShift(event, modal.origin)}><div className="form-grid">{modal.origin === 'admin' && <label>師傅<select name="staff" defaultValue={staff.find((item) => item.status === '在職')?.id}>{staff.filter((item) => item.status === '在職').map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>}<div className="form-grid two"><label>開始日期<input name="startDate" type="date" min={modal.origin === 'staff' || !canOverrideTimeRules ? todayIso : undefined} defaultValue={bookingDefault.date} required /></label><label>開始時間<ClockSelect name="start" defaultValue={bookingDefault.time} /></label><label>結束日期<input name="endDate" type="date" defaultValue={shiftEndDefault.date} required /></label><label>結束時間<ClockSelect name="end" defaultValue={shiftEndDefault.time} /></label></div></div><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button className="primary-button" type="submit">確認排班</button></footer></form></Modal>}

      {modal?.type === 'shiftDetail' && selectedShift && <Modal title={`${selectedShift.staff} 的排班`} subtitle={`${selectedShift.date} ${selectedShift.start} 至 ${selectedShift.endDate} ${selectedShift.end}`} onClose={() => setModal(null)}><div className="detail-stack"><div className="detail-hero"><div><span>建立來源</span><strong>{selectedShift.source}</strong><small>共 {Number((shiftDurationMinutes(selectedShift) / 60).toFixed(2))} 小時</small></div><StatusPill status={isShiftLocked(selectedShift) && !canOverrideTimeRules ? '已鎖定' : '可調整'} /></div>{isShiftLocked(selectedShift) && !canOverrideTimeRules && <div className="locked-message">此班已進入開始前 90 分鐘範圍。請由店長、Admin 或具強制權限的客服處理。</div>}{modal.origin === 'staff' ? <button className="danger-button full" onClick={() => removeShift(selectedShift, 'staff')}>{isShiftLocked(selectedShift) ? '聯絡店長處理' : '撤銷這段排班'}</button> : <form onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); removeShift(selectedShift, 'admin', String(data.get('reason') || '')); }}><label className="field-label">撤銷備註<textarea name="reason" rows={3} placeholder="選填，例如：師傅臨時請假" /></label><button className="danger-button full" type="submit">撤銷排班</button></form>}</div></Modal>}

      {modal?.type === 'checkout' && selectedAppointment && <Modal title="完成訂單" subtitle={`${selectedAppointment.id}・${selectedAppointment.customer}`} onClose={() => setModal(null)}><form className="modal-form" onSubmit={(event) => finishCheckout(event, selectedAppointment.id)}><div className="receipt"><div><span>{selectedAppointment.service}</span><strong>{formatCurrency(selectedAppointment.basePrice || selectedAppointment.total)}</strong></div><div><span>{selectedAppointment.promotionName || '優惠折扣'}</span><strong>− {formatCurrency(selectedAppointment.discountAmount || 0)}</strong></div><div><span>其他加價</span><strong>＋ {formatCurrency(selectedAppointment.extraAmount || 0)}</strong></div><div className="receipt-total"><span>應收總額</span><strong>{formatCurrency(selectedAppointment.total)}</strong></div></div><label>付款方式<select name="paymentMethod" defaultValue="現金"><option>現金</option><option>轉帳</option></select></label><label>完成備註<textarea name="note" rows={3} placeholder="例如：現金已收妥" /></label><div className="form-note">按下完成後即視為款項已回帳，不再需要師傅或第三人另外確認。</div><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>稍後處理</button><button className="primary-button" type="submit">確認完成訂單</button></footer></form></Modal>}

      {modal?.type === 'serviceCreate' && <Modal title="新增服務方案" subtitle="新增後會同步提供後台、官網編輯器、預約網頁與 LINE Bot 使用。" onClose={() => setModal(null)}><form className="modal-form" onSubmit={addService}><div className="form-grid two"><label>方案代碼<input name="code" required placeholder="例如 A" /></label><label>方案名稱<input name="name" required /></label><label>服務分鐘<input name="duration" type="number" min="1" required /></label><label>售價<input name="price" type="number" min="0" required /></label><label>服務地點<select name="location"><option>店內</option><option>外出</option></select></label></div><label>方案說明<textarea name="description" rows={3} /></label><label className="checkbox-field"><input name="canChooseStaff" type="checkbox" defaultChecked />可指定師傅</label><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button className="primary-button">新增方案</button></footer></form></Modal>}
      {modal?.type === 'service' && (() => { const plan = plans.find((item) => item.id === modal.id); return plan ? <Modal title={`編輯 ${plan.code} 方案`} subtitle="正式版會保存生效日期與每次價格修改紀錄。" onClose={() => setModal(null)}><form className="modal-form" onSubmit={(event) => saveService(event, plan.id)}><label>方案名稱<input name="name" defaultValue={plan.name} required /></label><div className="form-grid two"><label>服務分鐘<input name="duration" type="number" min="30" step="10" defaultValue={plan.duration} required /></label><label>售價<input name="price" type="number" min="0" step="100" defaultValue={plan.price} required /></label></div><label className="checkbox-field"><input name="active" type="checkbox" defaultChecked={plan.active} />啟用此方案</label><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button className="primary-button" type="submit">儲存變更</button></footer></form></Modal> : null; })()}

      {modal?.type === 'promotion' && <Modal title="新增優惠或附加費" subtitle="規則會保留生效期間與計算方式。" onClose={() => setModal(null)}><form className="modal-form" onSubmit={addPromotion}><label>規則名稱<input name="name" required placeholder="例如：週年慶折扣" /></label><div className="form-grid two"><label>計算方式<select name="calculationType"><option value="fixed_discount">固定折扣</option><option value="percent_discount">百分比折扣</option><option value="fixed_fee">固定加價</option><option value="per_30_minutes">每 30 分鐘</option><option value="per_km">每公里</option></select></label><label>金額／百分比<input name="value" type="number" min="0" required /></label><label>生效日期<input name="startsAt" type="date" defaultValue={todayIso} /></label><label>結束日期<input name="endsAt" type="date" min={todayIso} /></label></div><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button className="primary-button">新增規則</button></footer></form></Modal>}

      {modal?.type === 'promotionEdit' && (() => { const promotion = promotions.find((item) => item.id === modal.id); const typeValue = promotion?.kind === '百分比折扣' ? 'percent_discount' : promotion?.kind === '固定折扣' ? 'fixed_discount' : promotion?.kind === '每 30 分鐘' ? 'per_30_minutes' : promotion?.kind === '每公里' ? 'per_km' : 'fixed_fee'; return promotion ? <Modal title={`編輯 ${promotion.name}`} subtitle="儲存後，後台預約與 LINE Bot 優惠輪播會共用此規則。" onClose={() => setModal(null)}><form className="modal-form" onSubmit={(event) => savePromotion(event, promotion.id)}><label>規則名稱<input name="name" defaultValue={promotion.name} required /></label><label>說明<input name="description" placeholder="顯示在 LINE Flex 卡片上的適用說明" /></label><div className="form-grid two"><label>計算方式<select name="calculationType" defaultValue={typeValue}><option value="fixed_discount">固定折扣</option><option value="percent_discount">百分比折扣</option><option value="fixed_fee">固定加價</option><option value="per_30_minutes">每 30 分鐘</option><option value="per_km">每公里</option></select></label><label>金額／百分比<input name="value" type="number" min="0" defaultValue={promotion.value} required /></label></div><label className="checkbox-field"><input name="active" type="checkbox" defaultChecked={promotion.active} />啟用此優惠</label><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button className="primary-button">儲存優惠</button></footer></form></Modal> : null; })()}

      {modal?.type === 'returnRule' && (() => { const set = returnRuleSets.find((item) => item.id === modal.setId); const rule = set?.rules.find((item) => item.id === modal.ruleId); return set && rule ? <Modal title={`編輯 ${set.name}`} subtitle={`${rule.service_code}・${rule.name}`} onClose={() => setModal(null)}><form className="modal-form" onSubmit={(event) => saveReturnRule(event, set.id, rule.id)}><label>顯示名稱<input name="name" defaultValue={rule.name} required /></label><div className="form-grid two"><label>回帳金額<input name="amount" type="number" min="0" step="100" defaultValue={rule.amount} required /></label><label>服務分鐘<input name="duration" type="number" min="30" defaultValue={rule.duration_minutes} required /></label></div><label className="checkbox-field"><input name="active" type="checkbox" defaultChecked={rule.active} />啟用此回帳規則</label><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button className="primary-button">儲存回帳規則</button></footer></form></Modal> : null; })()}

      {modal?.type === 'staff' && <Modal title="新增員工" subtitle="基本資料與 LINE 串接都會保存到正式資料庫。" onClose={() => setModal(null)}><form className="modal-form" onSubmit={addStaff}><label>姓名／稱呼<input name="name" required /></label><label>手機 ID<input name="phone" inputMode="tel" placeholder="師傅手機 ID 登入使用" /></label><label>師傅分類<select name="category"><option>直男師傅</option><option>圈內師傅</option><option>雙性師傅</option></select></label><div className="form-grid two"><label>身高（cm）<input name="height" type="number" min="100" max="250" /></label><label>體重（kg）<input name="weight" type="number" min="30" max="250" /></label></div><label>角色<select name="role" defaultValue=""><option value="">尚未設定</option><option>攻擊手</option><option>守備方</option><option>無特定</option><option>攻守兼備</option></select></label><label>公開照片網址<input name="photoUrl" type="url" placeholder="https://..." /></label><label>或從電腦上傳照片<input name="photoFile" type="file" accept="image/jpeg,image/png,image/webp" /></label><div className="form-note">若同時填網址並選擇檔案，會以上傳檔案為準；限 JPEG、PNG、WebP，最大 3 MB。</div><label>回帳表<select name="returnRuleSetId">{returnRuleSets.filter((set) => set.active).map((set) => <option key={set.id} value={set.id}>{set.name}</option>)}</select></label><label>LINE User ID（選填）<input name="lineUserId" pattern="U[0-9a-fA-F]{32}" minLength={33} maxLength={33} placeholder="U 開頭的 33 位 LINE User ID" /></label><div className="form-note">若填寫 LINE ID，只有測試通知成功送達才會建立並完成串接。</div><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button className="primary-button">建立員工</button></footer></form></Modal>}

      {modal?.type === 'staffEdit' && (() => { const member = staff.find((item) => item.id === modal.id); return member ? <Modal title={`編輯 ${member.name}`} subtitle="可編輯身高、體重、角色及撤銷後重新串接 LINE。" onClose={() => setModal(null)}><form className="modal-form" onSubmit={(event) => saveStaffProfile(event, member)}><label>姓名／稱呼<input name="name" defaultValue={member.name} required /></label><label>師傅分類<select name="category" defaultValue={member.category}><option>直男師傅</option><option>圈內師傅</option><option>雙性師傅</option></select></label><div className="form-grid two"><label>身高（cm）<input name="height" type="number" min="100" max="250" defaultValue={member.height || ''} /></label><label>體重（kg）<input name="weight" type="number" min="30" max="250" defaultValue={member.weight || ''} /></label></div><label>角色<select name="role" defaultValue={member.role || ''}><option value="">尚未設定</option><option>攻擊手</option><option>守備方</option><option>無特定</option><option>攻守兼備</option></select></label>{member.photoUrl && <img className="staff-edit-preview" src={member.photoUrl} alt={`${member.name}目前公開照片`} />}<label>公開照片網址<input name="photoUrl" type="url" defaultValue={member.photoUrl || ''} placeholder="https://..." /></label><label>或從電腦上傳新照片<input name="photoFile" type="file" accept="image/jpeg,image/png,image/webp" /></label><div className="form-note">選擇新檔案時會覆蓋網址欄位的照片。限 JPEG、PNG、WebP，最大 3 MB。</div><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button>{canManageAll && <button type="button" className="danger-button" onClick={() => setModal({ type: 'staffDelete', id: member.id })}>永久刪除</button>}<button className="primary-button">儲存公開資料</button></footer></form><form className="modal-form line-link-form" onSubmit={(event) => linkStaffLine(event, member)}><div className="form-note"><strong>{member.lineConnected ? '目前 LINE 已串接' : '目前 LINE 尚未串接'}</strong><br />{member.lineConnected ? '輸入新的 LINE User ID 會先撤銷舊連結，再傳送測試通知並改綁。' : '只有測試通知成功送達才會完成串接。'}</div><label>新的 LINE User ID<input name="lineUserId" required pattern="U[0-9a-fA-F]{32}" minLength={33} maxLength={33} placeholder="U 開頭的 33 位 LINE User ID" /></label><footer className="modal-actions">{member.lineConnected && <button type="button" className="danger-button" onClick={() => unlinkStaffLine(member)}>僅解除目前 LINE</button>}<button className="primary-button" type="submit">{member.lineConnected ? '撤銷後改綁並傳通知' : '串接並傳送測試通知'}</button></footer></form></Modal> : null; })()}

      {modal?.type === 'staffDelete' && (() => { const member = staff.find((item) => item.id === modal.id); return member ? <Modal title={`永久刪除 ${member.name}`} subtitle="這項操作無法復原。" onClose={() => setModal(null)}><form className="modal-form" onSubmit={(event) => permanentlyDeleteStaff(event, member)}><div className="locked-message">永久刪除會移除 LINE 綁定、登入連結、班表與私密資料；歷史訂單只保留當時的師傅名稱快照。</div><label>刪除原因<input name="reason" required minLength={3} maxLength={500} placeholder="例如：重複建立的錯誤帳戶" /></label><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button className="danger-button" type="submit">確認永久刪除</button></footer></form></Modal> : null; })()}

      {modal?.type === 'bookingRequest' && selectedBookingRequest && <Modal title={`處理 ${selectedBookingRequest.request_id}`} subtitle="這是預約通知；儲存修改不會成立訂單，按確認後才會建立正式訂單。" onClose={() => setModal(null)} wide><form className="modal-form" onSubmit={(event) => saveBookingRequest(event, selectedBookingRequest)}><div className="form-grid two"><label>客戶名稱<input name="customerName" defaultValue={selectedBookingRequest.customer_name} required /></label><label>手機號碼<input name="phone" defaultValue={selectedBookingRequest.phone} pattern="09[0-9]{8}" required /></label><label>預約時間<input name="startTime" type="datetime-local" defaultValue={selectedBookingRequest.start_time.slice(0, 16)} required /></label><label>指定師傅<select name="staffId" defaultValue={selectedBookingRequest.staff_id || ''}><option value="">未指定</option>{staff.filter((item) => item.status === '在職').map((item) => <option key={item.id} value={item.apiId}>{item.name}</option>)}</select></label><label>服務方案<select name="servicePlanId" defaultValue={selectedBookingRequest.service_plan_id}>{plans.filter((item) => item.active).map((item) => <option key={item.id} value={item.apiId}>{item.code}・{item.name}</option>)}</select></label><label>優惠<select name="promotionId" defaultValue={selectedBookingRequest.promotion_id || ''}><option value="">不使用優惠</option>{promotions.filter((item) => item.active).map((item) => <option key={item.id} value={item.apiId}>{item.name}</option>)}</select></label></div><label>客戶備註<textarea name="notes" rows={3} defaultValue={selectedBookingRequest.notes || ''} /></label><label>客服處理備註<textarea name="reviewNote" rows={2} defaultValue={selectedBookingRequest.review_note || ''} /></label><footer className="modal-actions"><button type="button" className="danger-button" onClick={() => cancelBookingRequest(selectedBookingRequest)}>取消通知</button><button className="secondary-button" type="submit">儲存修改</button><button className="primary-button" type="button" onClick={() => confirmBookingRequest(selectedBookingRequest)}>確認並成立訂單</button></footer></form></Modal>}

      {modal?.type === 'user' && canCreateUsers && <Modal title="新增後台使用者" subtitle={role === 'manager' ? '店長只能新增客服（管理）帳號。' : 'Admin 可新增 Admin、店長或客服帳號。'} onClose={() => setModal(null)}><form className="modal-form" onSubmit={addAdminUser}><label>顯示名稱<input name="displayName" required /></label><label>登入帳號<input name="username" required autoCapitalize="none" /></label>{role === 'manager' ? <label>角色<input name="role" value="客服" disabled /></label> : <label>角色<select name="role"><option>Admin</option><option>店長</option><option>客服</option></select></label>}<label>初始數字 PIN<input name="pin" required inputMode="numeric" pattern="[0-9]+" minLength={4} maxLength={12} type="password" placeholder="至少 4 位" /></label><label className="checkbox-row"><input name="canOverrideTimeRules" type="checkbox" />若角色為客服，允許略過預約、排班的時間與撞期限制</label><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button className="primary-button">建立帳號</button></footer></form></Modal>}
      {modal?.type === 'customer' && selectedCustomer && <Modal title={`編輯 ${selectedCustomer.name}`} subtitle="內部識別由等級與主要手機後四碼組成，客人不會看到。" onClose={() => setModal(null)}><form className="modal-form" onSubmit={saveCustomer}><label>客戶等級<select name="customerGrade" defaultValue={selectedCustomer.grade} disabled={!canManageAll}><option>SSR</option><option>SR</option><option>R</option><option>N</option></select>{!canManageAll && <input type="hidden" name="customerGrade" value={selectedCustomer.grade} />}</label><label>內部識別<input value={selectedCustomer.vipSerial} disabled /></label><label>客戶名稱<input name="displayName" defaultValue={selectedCustomer.name} required placeholder="可由後台建立或採用 LINE 顯示名稱" /></label><label>手機 ID<textarea name="phones" rows={4} defaultValue={selectedCustomer.phones.join('\n')} required placeholder={"0912345678\n0987654321"} /></label><div className="form-note">每行一支手機；第一支是主要聯絡號碼。每支手機只能屬於一位客戶。只有 Admin／店長可調整等級；SSR／SR 不會因官網再次預約而自動降級。</div><footer className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button className="primary-button">儲存客戶資料</button></footer></form></Modal>}
    </main>
  );
}
