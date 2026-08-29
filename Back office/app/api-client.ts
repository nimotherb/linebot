import type { Appointment, AppointmentStatus, Customer, ServicePlan, Shift, StaffMember } from './models';

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || 'https://linebot-3r2w.onrender.com').replace(/\/$/, '');

export type AdminIdentity = {
  id: number;
  username: string;
  display_name: string;
  role: 'admin' | 'manager' | 'clerk';
  is_active?: boolean;
};

export type StaffIdentity = { id: number; name: string; role: 'staff' };

type RawAppointment = {
  id: number;
  order_id: string;
  customer_serial?: string;
  customer_name: string;
  phone?: string;
  staff_id?: number;
  staff_name: string;
  service_plan_id?: number;
  service_name: string;
  promotion_id?: number;
  promotion_name?: string;
  start_time: string;
  end_time: string;
  status_label: AppointmentStatus;
  room_id?: number;
  room_name?: string;
  location_type: 'onsite' | 'external' | 'pending';
  total_amount: number;
  base_price?: number;
  discount_amount?: number;
  extra_amount?: number;
  expected_return_amount?: number;
  staff_return_status?: string;
  notes?: string;
  payment_status?: string;
};

type RawService = {
  id: number;
  code: string;
  name: string;
  duration_minutes: number;
  price: number;
  can_choose_staff: boolean;
  location_type: 'onsite' | 'external';
  active: boolean;
};

type RawStaff = {
  id: number;
  name: string;
  category?: 'straight' | 'gay' | 'bisexual';
  employment_status: 'active' | 'retired';
  line_connected: boolean;
  return_rule_set_id?: number;
  photo_url?: string;
  height?: string;
  weight?: string;
};

type RawShift = {
  id: number;
  staff_id: number;
  staff_name?: string;
  start_time: string;
  end_time: string;
  source: 'staff_link' | 'admin' | 'manager';
  locked: boolean;
};

export type PromotionView = {
  id: string;
  apiId?: number;
  name: string;
  kind: string;
  value: number;
  period: string;
  active: boolean;
};

export type AdminUserView = {
  id: number;
  username: string;
  displayName: string;
  role: string;
  roleKey: AdminIdentity['role'];
  status: string;
  isActive: boolean;
  lastLogin: string;
};

export type AuditLogView = {
  id: number;
  actorName: string;
  action: string;
  entityType: string;
  entityId?: string;
  reason?: string;
  createdAt: string;
};

export type BootstrapData = {
  mode?: 'public' | 'staff';
  user: AdminIdentity | null;
  staff_user?: StaffIdentity;
  appointments: RawAppointment[];
  services: RawService[];
  staff: RawStaff[];
  shifts: RawShift[];
  promotions: Array<{ id: number; name: string; calculation_type: string; value: number; active: boolean; starts_at?: string; ends_at?: string }>;
  rooms: Array<{ id: number; name: string; active: boolean }>;
  customers?: Array<{ id: number; vip_serial: string; display_name?: string; primary_phone?: string; phones: string[]; visits: number; spent: number; last_visit?: string }>;
  admin_users?: AdminIdentity[];
  return_rule_sets?: ReturnRuleSetView[];
  audit_logs?: Array<{
    id: number;
    actor_name: string;
    action: string;
    entity_type: string;
    entity_id?: string;
    reason?: string;
    created_at: string;
  }>;
};

export type ReturnRuleSetView = {
  id: number;
  code: string;
  name: string;
  active: boolean;
  rules: Array<{ id: number; service_code: string; name: string; amount: number; duration_minutes: number; active: boolean }>;
};

export type PublicBookingOptions = {
  services: RawService[];
  promotions: BootstrapData['promotions'];
  minimum_lead_minutes: number;
  support_url: string;
  liff_id?: string;
  line_login_enabled: boolean;
};

export type PublicBookingAvailability = {
  start_time: string;
  end_time: string;
  can_choose_staff: boolean;
  staff: Array<{ id: number; name: string; category?: RawStaff['category'] }>;
};

export type PublicBookingResult = {
  duplicate: boolean;
  appointment: RawAppointment;
};

const splitDateTime = (value: string) => {
  const [date, time = ''] = value.split('T');
  return { date, time: time.slice(0, 5) };
};

export const mapAppointment = (item: RawAppointment): Appointment => {
  const start = splitDateTime(item.start_time);
  const end = splitDateTime(item.end_time);
  return {
    id: item.order_id,
    apiId: item.id,
    date: start.date,
    start: start.time,
    end: end.time,
    customerSerial: item.customer_serial,
    customer: item.customer_name,
    phone: item.phone || '未提供',
    staff: item.staff_name || '我的班表',
    staffId: item.staff_id ? String(item.staff_id) : undefined,
    serviceId: item.service_plan_id ? String(item.service_plan_id) : '',
    service: item.service_name,
    room: item.room_name || (item.location_type === 'external' ? '外出場地' : '待確認'),
    roomId: item.room_id,
    location: item.location_type === 'onsite' ? '店內' : item.location_type === 'external' ? '外出' : '待確認',
    status: item.status_label,
    total: item.total_amount,
    basePrice: item.base_price ?? item.total_amount,
    discountAmount: item.discount_amount ?? 0,
    extraAmount: item.extra_amount ?? 0,
    promotionId: item.promotion_id ? String(item.promotion_id) : undefined,
    promotionName: item.promotion_name,
    expectedReturn: item.expected_return_amount ?? 0,
    returnStatus: item.staff_return_status,
    payment: item.payment_status === 'paid' || item.status_label === '已完成' ? '已付款' : '未付款',
    note: item.notes,
  };
};

export const mapService = (item: RawService): ServicePlan => ({
  id: String(item.id),
  apiId: item.id,
  code: item.code,
  name: item.name,
  duration: item.duration_minutes,
  price: item.price,
  canChooseStaff: item.can_choose_staff,
  location: item.location_type === 'external' ? '外出' : '店內',
  active: item.active,
});

const categoryLabel = (category?: RawStaff['category']): StaffMember['category'] => (
  category === 'straight' ? '直男師傅' : category === 'bisexual' ? '雙性師傅' : '圈內師傅'
);

export const mapStaff = (item: RawStaff): StaffMember => ({
  id: String(item.id),
  apiId: item.id,
  name: item.name,
  category: categoryLabel(item.category),
  status: item.employment_status === 'retired' ? '暫時退役' : '在職',
  lineConnected: item.line_connected,
  privateProfile: true,
  returnRuleSetId: item.return_rule_set_id,
  photoUrl: item.photo_url,
  height: item.height,
  weight: item.weight,
});

export const mapShift = (item: RawShift): Shift => {
  const start = splitDateTime(item.start_time);
  const end = splitDateTime(item.end_time);
  return {
    id: String(item.id),
    apiId: item.id,
    staff: item.staff_name || '我的班表',
    staffId: String(item.staff_id),
    date: start.date,
    start: start.time,
    end: end.time,
    source: item.source === 'staff_link' ? '師傅連結' : item.source === 'manager' ? '店長' : 'Admin',
    locked: item.locked,
  };
};

const promotionKind: Record<string, string> = {
  fixed_discount: '固定折扣',
  percent_discount: '百分比折扣',
  fixed_fee: '固定加價',
  per_30_minutes: '每 30 分鐘',
  per_km: '每公里',
};

export const mapPromotion = (item: BootstrapData['promotions'][number]): PromotionView => ({
  id: String(item.id),
  apiId: item.id,
  name: item.name,
  kind: promotionKind[item.calculation_type] || item.calculation_type,
  value: item.value,
  period: item.starts_at || item.ends_at ? `${item.starts_at || '即日起'}～${item.ends_at || '持續'}` : '長期',
  active: item.active,
});

export const mapCustomer = (item: NonNullable<BootstrapData['customers']>[number]): Customer => ({
  id: item.vip_serial,
  apiId: item.id,
  vipSerial: item.vip_serial,
  name: item.display_name || '未命名客戶',
  lineName: item.display_name || '未取得',
  phone: item.primary_phone || item.phones[0] || '未提供',
  phones: item.phones || [],
  visits: item.visits,
  spent: item.spent,
  lastVisit: item.last_visit || '—',
  note: '',
});

export const mapAdminUser = (item: AdminIdentity): AdminUserView => ({
  id: item.id,
  username: item.username,
  displayName: item.display_name,
  role: item.role === 'admin' ? '系統管理員' : item.role === 'manager' ? '店長' : '客服',
  roleKey: item.role,
  status: item.is_active === false ? '已停用' : '啟用',
  isActive: item.is_active !== false,
  lastLogin: '—',
});

export const mapAuditLog = (item: NonNullable<BootstrapData['audit_logs']>[number]): AuditLogView => ({
  id: item.id,
  actorName: item.actor_name,
  action: item.action,
  entityType: item.entity_type,
  entityId: item.entity_id,
  reason: item.reason,
  createdAt: item.created_at,
});

export class SpaApi {
  constructor(private token = '') {}

  static async probe(): Promise<boolean> {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/health`, { signal: controller.signal });
      return response.ok;
    } catch {
      return false;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        ...init.headers,
      },
    });
    if (!response.ok) {
      let message = `伺服器回應 ${response.status}`;
      try {
        const payload = await response.json();
        message = payload.detail || message;
      } catch {}
      throw new Error(message);
    }
    return response.json() as Promise<T>;
  }

  login(username: string, pin: string) {
    return this.request<{ access_token: string; user: AdminIdentity }>('/api/admin/auth/login', {
      method: 'POST', body: JSON.stringify({ username, pin }),
    });
  }

  bootstrap() { return this.request<BootstrapData>('/api/admin/bootstrap'); }

  publicBootstrap() { return this.request<BootstrapData>('/api/public/bootstrap'); }

  publicBookingOptions() {
    return this.request<PublicBookingOptions>('/api/public/booking/options');
  }

  publicBookingAvailability(servicePlanId: number, startTime: string) {
    const query = new URLSearchParams({ service_plan_id: String(servicePlanId), start_time: startTime });
    return this.request<PublicBookingAvailability>(`/api/public/booking/availability?${query}`);
  }

  createPublicBooking(payload: Record<string, unknown>) {
    return this.request<PublicBookingResult>('/api/public/booking/appointments', {
      method: 'POST', body: JSON.stringify(payload),
    });
  }

  staffLogin(payload: { staff_id: number; phone: string }) {
    return this.request<{ access_token: string; staff: StaffIdentity }>('/api/staff/auth/login', { method: 'POST', body: JSON.stringify(payload) });
  }

  staffLineLogin(token: string) {
    return this.request<{ access_token: string; staff: StaffIdentity }>('/api/staff/auth/line', { method: 'POST', body: JSON.stringify({ token }) });
  }

  staffBootstrap() { return this.request<BootstrapData>('/api/staff/bootstrap'); }

  logout(path: 'admin' | 'staff' = 'admin') {
    return this.request<{ ok: boolean }>(`/api/${path}/auth/logout`, { method: 'POST' });
  }

  createAppointment(payload: Record<string, unknown>) {
    return this.request<RawAppointment>('/api/admin/appointments', { method: 'POST', body: JSON.stringify(payload) });
  }

  updateAppointment(id: number, payload: Record<string, unknown>) {
    return this.request<RawAppointment>(`/api/admin/appointments/${id}`, { method: 'PATCH', body: JSON.stringify(payload) });
  }

  updateCustomer(id: number, payload: { display_name: string; phones: string[] }) {
    return this.request<NonNullable<BootstrapData['customers']>[number]>(`/api/admin/customers/${id}`, { method: 'PATCH', body: JSON.stringify(payload) });
  }

  createShift(payload: Record<string, unknown>) {
    return this.request<RawShift>('/api/admin/shifts', { method: 'POST', body: JSON.stringify(payload) });
  }

  deleteShift(id: number, reason = '') {
    const query = reason ? `?reason=${encodeURIComponent(reason)}` : '';
    return this.request<{ ok: boolean }>(`/api/admin/shifts/${id}${query}`, { method: 'DELETE' });
  }

  updateService(id: number, payload: Record<string, unknown>) {
    return this.request<RawService>(`/api/admin/services/${id}`, { method: 'PATCH', body: JSON.stringify(payload) });
  }

  checkout(id: number, payload: Record<string, unknown>) {
    return this.request<{ appointment: RawAppointment }>(`/api/admin/appointments/${id}/checkout`, { method: 'POST', body: JSON.stringify(payload) });
  }

  createStaff(payload: Record<string, unknown>) {
    return this.request<RawStaff>('/api/admin/staff', { method: 'POST', body: JSON.stringify(payload) });
  }

  updateStaffStatus(id: number, payload: Record<string, unknown>) {
    return this.request<RawStaff>(`/api/admin/staff/${id}/status`, { method: 'PATCH', body: JSON.stringify(payload) });
  }

  updateStaff(id: number, payload: Record<string, unknown>) {
    return this.request<RawStaff>(`/api/admin/staff/${id}`, { method: 'PATCH', body: JSON.stringify(payload) });
  }

  deleteStaff(id: number, reason: string) {
    const query = new URLSearchParams({ reason });
    return this.request<{ ok: boolean; deleted_staff_id: number; deleted_staff_name: string }>(`/api/admin/staff/${id}?${query}`, { method: 'DELETE' });
  }

  createPromotion(payload: Record<string, unknown>) {
    return this.request<BootstrapData['promotions'][number]>('/api/admin/promotions', { method: 'POST', body: JSON.stringify(payload) });
  }

  updatePromotion(id: number, payload: Record<string, unknown>) {
    return this.request<BootstrapData['promotions'][number]>(`/api/admin/promotions/${id}`, { method: 'PATCH', body: JSON.stringify(payload) });
  }

  updateReturnRule(id: number, payload: Record<string, unknown>) {
    return this.request<Record<string, unknown>>(`/api/admin/return-rules/${id}`, { method: 'PATCH', body: JSON.stringify(payload) });
  }

  staffCreateAppointment(payload: Record<string, unknown>) {
    return this.request<RawAppointment>('/api/staff/appointments', { method: 'POST', body: JSON.stringify(payload) });
  }

  staffCompleteAppointment(id: number) {
    return this.request<RawAppointment>(`/api/staff/appointments/${id}/complete`, { method: 'PATCH' });
  }

  staffCreateShift(payload: { start_time: string; end_time: string }) {
    return this.request<RawShift>('/api/staff/shifts', { method: 'POST', body: JSON.stringify(payload) });
  }

  staffDeleteShift(shiftId: number) {
    return this.request<{ ok: boolean }>(`/api/staff/shifts/${shiftId}`, { method: 'DELETE' });
  }

  createUser(payload: Record<string, unknown>) {
    return this.request<AdminIdentity>('/api/admin/users', { method: 'POST', body: JSON.stringify(payload) });
  }

  deactivateUser(id: number) {
    return this.request<AdminIdentity>(`/api/admin/users/${id}`, { method: 'DELETE' });
  }

  publicSchedule(token: string) {
    return this.request<{ staff: { id: number; name: string }; rules: { minimum_hours: number; lock_minutes: number }; shifts: RawShift[] }>(`/api/staff/schedule/${encodeURIComponent(token)}`);
  }

  publicCreateShift(token: string, payload: { start_time: string; end_time: string }) {
    return this.request<RawShift>(`/api/staff/schedule/${encodeURIComponent(token)}`, { method: 'POST', body: JSON.stringify(payload) });
  }

  publicDeleteShift(token: string, shiftId: number) {
    return this.request<{ ok: boolean }>(`/api/staff/schedule/${encodeURIComponent(token)}/${shiftId}`, { method: 'DELETE' });
  }

  async download(dataset: 'appointments' | 'shifts' | 'customers', start?: string, end?: string) {
    const query = new URLSearchParams();
    if (start) query.set('start', `${start}T00:00:00`);
    if (end) query.set('end', `${end}T23:59:59`);
    const response = await fetch(`${API_BASE_URL}/api/admin/export/${dataset}?${query}`, {
      headers: { Authorization: `Bearer ${this.token}` },
    });
    if (!response.ok) throw new Error('匯出失敗');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `equalspa-${dataset}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  // ==========================================
  // 官網內容管理 (SITE STUDIO) API
  // ==========================================

  // 1. 取得目前草稿與發布狀態 (Admin / 店長專用)
  async getAdminSiteContent() {
    return this.request<Record<string, unknown>>('/api/admin/site-content', { method: 'GET' });
  }

  // 2. 儲存草稿
  async saveSiteDraft(content: Record<string, unknown>, expectedVersion: number) {
    try {
      const result = await fetch(`${API_BASE_URL}/api/admin/site-content/draft`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${this.token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          content: content,
          expected_version: expectedVersion
        })
      });
      
      if (result.status === 409) {
        throw new Error('版本衝突：有其他人員剛剛修改了內容，請重新載入以獲取最新版本');
      }
      if (result.status === 403) {
        throw new Error('權限不足：只有店長或系統管理員可以修改官網內容');
      }
      if (!result.ok) throw new Error('儲存草稿失敗');
      
      return await result.json();
    } catch (error: unknown) {
      throw new Error(error instanceof Error ? error.message : '儲存草稿失敗');
    }
  }

  // 3. 正式發布
  async publishSiteContent(expectedVersion: number) {
    try {
      const result = await fetch(`${API_BASE_URL}/api/admin/site-content/publish`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          expected_version: expectedVersion
        })
      });

      if (result.status === 409) {
        throw new Error('版本衝突：草稿狀態已變更，請確認後再發布');
      }
      if (!result.ok) throw new Error('發布失敗');
      
      return await result.json();
    } catch (error: unknown) {
      throw new Error(error instanceof Error ? error.message : '發布失敗');
    }
  }
}
