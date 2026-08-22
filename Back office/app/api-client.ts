import type { Appointment, AppointmentStatus, Customer, ServicePlan, Shift, StaffMember } from './mock-data';

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || 'https://linebot-3r2w.onrender.com').replace(/\/$/, '');

export type AdminIdentity = {
  id: number;
  username: string;
  display_name: string;
  role: 'admin' | 'manager' | 'clerk';
};

type RawAppointment = {
  id: number;
  order_id: string;
  customer_name: string;
  phone?: string;
  staff_id?: number;
  staff_name: string;
  service_plan_id?: number;
  service_name: string;
  start_time: string;
  end_time: string;
  status_label: AppointmentStatus;
  room_id?: number;
  room_name?: string;
  location_type: 'onsite' | 'external' | 'pending';
  total_amount: number;
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
  username: string;
  displayName: string;
  role: string;
  status: string;
  lastLogin: string;
};

export type BootstrapData = {
  user: AdminIdentity;
  appointments: RawAppointment[];
  services: RawService[];
  staff: RawStaff[];
  shifts: RawShift[];
  promotions: Array<{ id: number; name: string; calculation_type: string; value: number; active: boolean; starts_at?: string; ends_at?: string }>;
  rooms: Array<{ id: number; name: string; active: boolean }>;
  customers?: Array<{ id: number; vip_id: string; display_name?: string; phone?: string; visits: number; spent: number; last_visit?: string }>;
  admin_users?: AdminIdentity[];
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
});

export const mapShift = (item: RawShift): Shift => {
  const start = splitDateTime(item.start_time);
  const end = splitDateTime(item.end_time);
  return {
    id: String(item.id),
    apiId: item.id,
    staff: item.staff_name,
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
  id: item.vip_id,
  name: item.display_name || item.vip_id,
  lineName: item.display_name || '未取得',
  phone: item.phone || '未提供',
  visits: item.visits,
  spent: item.spent,
  lastVisit: item.last_visit || '—',
  note: '',
});

export const mapAdminUser = (item: AdminIdentity): AdminUserView => ({
  username: item.username,
  displayName: item.display_name,
  role: item.role === 'admin' ? '系統管理員' : item.role === 'manager' ? '店長' : '櫃台',
  status: '啟用',
  lastLogin: '—',
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

  createAppointment(payload: Record<string, unknown>) {
    return this.request<RawAppointment>('/api/admin/appointments', { method: 'POST', body: JSON.stringify(payload) });
  }

  updateAppointment(id: number, payload: Record<string, unknown>) {
    return this.request<RawAppointment>(`/api/admin/appointments/${id}`, { method: 'PATCH', body: JSON.stringify(payload) });
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

  createPromotion(payload: Record<string, unknown>) {
    return this.request<BootstrapData['promotions'][number]>('/api/admin/promotions', { method: 'POST', body: JSON.stringify(payload) });
  }

  createUser(payload: Record<string, unknown>) {
    return this.request<AdminIdentity>('/api/admin/users', { method: 'POST', body: JSON.stringify(payload) });
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
}
