export type AppointmentStatus = '待確認' | '已確認' | '已報到' | '服務中' | '待結帳' | '已完成' | '已取消';

export type ServicePlan = {
  id: string;
  apiId?: number;
  code: string;
  name: string;
  duration: number;
  price: number;
  canChooseStaff: boolean;
  location: '店內' | '外出';
  active: boolean;
};

export type Appointment = {
  id: string;
  apiId?: number;
  date: string;
  start: string;
  end: string;
  customer: string;
  phone: string;
  staff: string;
  staffId?: string;
  serviceId: string;
  service: string;
  room: string;
  roomId?: number;
  location: '店內' | '外出' | '待確認';
  status: AppointmentStatus;
  total: number;
  payment: '未付款' | '已付款' | '部分付款';
  note?: string;
};

export type StaffMember = {
  id: string;
  apiId?: number;
  name: string;
  category: '直男師傅' | '圈內師傅' | '雙性師傅';
  status: '在職' | '暫時退役';
  lineConnected: boolean;
  privateProfile: boolean;
};

export type Shift = {
  id: string;
  apiId?: number;
  staff: string;
  staffId?: string;
  date: string;
  start: string;
  end: string;
  source: '師傅連結' | '店長' | 'Admin';
  locked?: boolean;
};

export type Customer = {
  id: string;
  name: string;
  lineName: string;
  phone: string;
  visits: number;
  spent: number;
  lastVisit: string;
  note: string;
};

export const demoNow = '2026-08-22T16:00:00+08:00';

export const servicePlans: ServicePlan[] = [
  { id: 'svc-a', code: 'A', name: '舒壓方案', duration: 60, price: 1500, canChooseStaff: false, location: '店內', active: true },
  { id: 'svc-b', code: 'B', name: '愉悅方案', duration: 60, price: 2000, canChooseStaff: true, location: '店內', active: true },
  { id: 'svc-c', code: 'C', name: '享受方案', duration: 90, price: 2500, canChooseStaff: true, location: '店內', active: true },
  { id: 'svc-d', code: 'D', name: '極緻方案', duration: 120, price: 3000, canChooseStaff: true, location: '店內', active: true },
  { id: 'svc-out', code: 'OUT', name: '隨享外出方案', duration: 100, price: 3200, canChooseStaff: true, location: '外出', active: true },
];

export const initialAppointments: Appointment[] = [
  { id: 'AP-DEMO-001', date: '2026-08-22', start: '16:00', end: '17:30', customer: '合成客戶 A', phone: '合成展示資料', staff: '示範師傅 A', serviceId: 'svc-c', service: 'C・享受方案', room: '房間 1', location: '店內', status: '服務中', total: 2500, payment: '未付款', note: '此為合成展示資料。' },
  { id: 'AP-DEMO-002', date: '2026-08-22', start: '16:30', end: '18:30', customer: '合成客戶 B', phone: '合成展示資料', staff: '示範師傅 B', serviceId: 'svc-d', service: 'D・極緻方案', room: '房間 2', location: '店內', status: '服務中', total: 3000, payment: '未付款' },
  { id: 'AP-DEMO-003', date: '2026-08-22', start: '19:30', end: '21:00', customer: '合成客戶 C', phone: '合成展示資料', staff: '示範師傅 C', serviceId: 'svc-c', service: 'C・享受方案', room: '房間 1', location: '店內', status: '已確認', total: 2500, payment: '未付款' },
  { id: 'AP-DEMO-004', date: '2026-08-22', start: '13:00', end: '14:00', customer: '合成客戶 D', phone: '合成展示資料', staff: '示範師傅 A', serviceId: 'svc-a', service: 'A・舒壓方案', room: '房間 1', location: '店內', status: '待結帳', total: 1500, payment: '未付款' },
  { id: 'AP-DEMO-005', date: '2026-08-23', start: '15:00', end: '17:00', customer: '合成客戶 E', phone: '合成展示資料', staff: '示範師傅 A', serviceId: 'svc-d', service: 'D・極緻方案', room: '房間 1', location: '店內', status: '已確認', total: 3000, payment: '未付款' },
];

export const staffMembers: StaffMember[] = [
  { id: 'ST-DEMO-001', name: '示範師傅 A', category: '圈內師傅', status: '在職', lineConnected: true, privateProfile: false },
  { id: 'ST-DEMO-002', name: '示範師傅 B', category: '雙性師傅', status: '在職', lineConnected: true, privateProfile: false },
  { id: 'ST-DEMO-003', name: '示範師傅 C', category: '直男師傅', status: '在職', lineConnected: false, privateProfile: false },
  { id: 'ST-DEMO-004', name: '示範師傅 D', category: '圈內師傅', status: '暫時退役', lineConnected: false, privateProfile: false },
];

export const initialShifts: Shift[] = [
  { id: 'SH-DEMO-001', staff: '示範師傅 A', date: '2026-08-22', start: '17:30', end: '21:30', source: '師傅連結' },
  { id: 'SH-DEMO-002', staff: '示範師傅 B', date: '2026-08-22', start: '16:00', end: '22:00', source: '店長' },
  { id: 'SH-DEMO-003', staff: '示範師傅 C', date: '2026-08-24', start: '14:00', end: '20:00', source: '師傅連結' },
];

export const customers: Customer[] = [
  { id: 'VIP-DEMO-001', name: '合成客戶 A', lineName: 'DEMO-A', phone: '合成展示資料', visits: 3, spent: 7000, lastVisit: '2026-08-22', note: '此為合成展示資料' },
  { id: 'VIP-DEMO-002', name: '合成客戶 B', lineName: 'DEMO-B', phone: '合成展示資料', visits: 1, spent: 3000, lastVisit: '2026-08-22', note: '此為合成展示資料' },
];

export const promotions = [
  { id: 'PR-001', name: '午夜服務費', kind: '固定加價', value: 600, period: '每日 00:00–06:00', active: true },
  { id: 'PR-002', name: '預約加時', kind: '每 30 分鐘', value: 500, period: '長期', active: true },
  { id: 'PR-003', name: '現場加時', kind: '每 30 分鐘', value: 700, period: '長期', active: true },
  { id: 'PR-004', name: '外出里程費', kind: '每公里', value: 80, period: '超過 3 公里', active: true },
];

export const adminUsers = [
  { username: 'admin-demo', displayName: '示範系統管理員', role: '系統管理員', status: '啟用', lastLogin: '示範資料' },
  { username: 'manager-demo', displayName: '示範店長', role: '店長', status: '啟用', lastLogin: '示範資料' },
];

export const weekDays = [
  { date: '2026-08-22', day: '六', label: '8/22' },
  { date: '2026-08-23', day: '日', label: '8/23' },
  { date: '2026-08-24', day: '一', label: '8/24' },
  { date: '2026-08-25', day: '二', label: '8/25' },
  { date: '2026-08-26', day: '三', label: '8/26' },
  { date: '2026-08-27', day: '四', label: '8/27' },
  { date: '2026-08-28', day: '五', label: '8/28' },
];

export const nextWeekDays = [
  { date: '2026-08-29', day: '六', label: '8/29' },
  { date: '2026-08-30', day: '日', label: '8/30' },
  { date: '2026-08-31', day: '一', label: '8/31' },
  { date: '2026-09-01', day: '二', label: '9/1' },
  { date: '2026-09-02', day: '三', label: '9/2' },
  { date: '2026-09-03', day: '四', label: '9/3' },
  { date: '2026-09-04', day: '五', label: '9/4' },
];
