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
  customerSerial?: string;
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
  basePrice?: number;
  discountAmount?: number;
  extraAmount?: number;
  promotionId?: string;
  promotionName?: string;
  expectedReturn?: number;
  returnStatus?: string;
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
  returnRuleSetId?: number;
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
  apiId?: number;
  vipSerial: string;
  name: string;
  lineName: string;
  phone: string;
  phones: string[];
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
  { id: 'AP-0822-001', date: '2026-08-22', start: '16:00', end: '17:30', customer: '王先生', phone: '0912•••678', staff: 'Harry', serviceId: 'svc-c', service: 'C・享受方案', room: '房間 1', location: '店內', status: '服務中', total: 2500, payment: '未付款', note: '偏好指壓，力道中等。' },
  { id: 'AP-0822-002', date: '2026-08-22', start: '16:30', end: '18:30', customer: '林先生', phone: '0988•••021', staff: '沐恩', serviceId: 'svc-d', service: 'D・極緻方案', room: '房間 2', location: '店內', status: '服務中', total: 3000, payment: '未付款' },
  { id: 'AP-0822-003', date: '2026-08-22', start: '18:00', end: '19:00', customer: '陳先生', phone: '0921•••166', staff: 'Eason', serviceId: 'svc-b', service: 'B・愉悅方案', room: '待確認', location: '待確認', status: '已確認', total: 2000, payment: '未付款', note: '店內房間若不足，客服需確認外出地點。' },
  { id: 'AP-0822-004', date: '2026-08-22', start: '19:30', end: '21:00', customer: '張先生', phone: '0933•••905', staff: '朗', serviceId: 'svc-c', service: 'C・享受方案', room: '房間 1', location: '店內', status: '已確認', total: 2500, payment: '未付款' },
  { id: 'AP-0822-005', date: '2026-08-22', start: '13:00', end: '14:00', customer: '何先生', phone: '0955•••100', staff: '小六', serviceId: 'svc-a', service: 'A・舒壓方案', room: '房間 1', location: '店內', status: '待結帳', total: 1500, payment: '未付款' },
  { id: 'AP-0822-006', date: '2026-08-22', start: '14:00', end: '15:00', customer: '周先生', phone: '0966•••813', staff: '彥', serviceId: 'svc-b', service: 'B・愉悅方案', room: '房間 2', location: '店內', status: '待結帳', total: 2000, payment: '未付款' },
  { id: 'AP-0823-001', date: '2026-08-23', start: '15:00', end: '17:00', customer: '許先生', phone: '0977•••522', staff: 'Harry', serviceId: 'svc-d', service: 'D・極緻方案', room: '房間 1', location: '店內', status: '已確認', total: 3000, payment: '未付款' },
];

export const staffMembers: StaffMember[] = [
  { id: 'ST-001', name: 'Harry', category: '圈內師傅', status: '在職', lineConnected: true, privateProfile: true },
  { id: 'ST-002', name: '沐恩', category: '雙性師傅', status: '在職', lineConnected: true, privateProfile: true },
  { id: 'ST-003', name: 'Eason', category: '直男師傅', status: '在職', lineConnected: true, privateProfile: true },
  { id: 'ST-004', name: '朗', category: '圈內師傅', status: '在職', lineConnected: true, privateProfile: true },
  { id: 'ST-005', name: '小六', category: '直男師傅', status: '在職', lineConnected: false, privateProfile: true },
  { id: 'ST-006', name: '彥', category: '雙性師傅', status: '在職', lineConnected: true, privateProfile: true },
  { id: 'ST-007', name: 'Max', category: '圈內師傅', status: '在職', lineConnected: true, privateProfile: true },
  { id: 'ST-008', name: 'Frank', category: '直男師傅', status: '暫時退役', lineConnected: true, privateProfile: true },
];

export const initialShifts: Shift[] = [
  { id: 'SH-001', staff: 'Harry', date: '2026-08-22', start: '17:30', end: '21:30', source: '師傅連結' },
  { id: 'SH-002', staff: '沐恩', date: '2026-08-22', start: '16:00', end: '22:00', source: '店長' },
  { id: 'SH-003', staff: 'Eason', date: '2026-08-22', start: '18:00', end: '22:00', source: '師傅連結' },
  { id: 'SH-004', staff: '朗', date: '2026-08-22', start: '19:00', end: '24:00', source: '師傅連結' },
  { id: 'SH-005', staff: 'Harry', date: '2026-08-23', start: '14:00', end: '22:00', source: '師傅連結' },
  { id: 'SH-006', staff: 'Max', date: '2026-08-24', start: '12:00', end: '20:00', source: '師傅連結' },
  { id: 'SH-007', staff: '小六', date: '2026-08-25', start: '16:00', end: '22:00', source: '店長' },
  { id: 'SH-008', staff: '彥', date: '2026-08-26', start: '14:00', end: '20:00', source: '師傅連結' },
  { id: 'SH-009', staff: '朗', date: '2026-08-27', start: '18:00', end: '24:00', source: '師傅連結' },
  { id: 'SH-010', staff: 'Eason', date: '2026-08-29', start: '15:00', end: '21:00', source: '師傅連結' },
];

export const customers: Customer[] = [
  { id: 'VIP-0001', vipSerial: 'VIP-0001', name: '王先生', lineName: 'Kai', phone: '0912•••678', phones: ['0912•••678'], visits: 8, spent: 19600, lastVisit: '2026-08-22', note: '偏好指壓，力道中等' },
  { id: 'VIP-0002', vipSerial: 'VIP-0002', name: '林先生', lineName: 'Lin', phone: '0988•••021', phones: ['0988•••021'], visits: 4, spent: 10800, lastVisit: '2026-08-22', note: '通常指定沐恩' },
  { id: 'VIP-0003', vipSerial: 'VIP-0003', name: '陳先生', lineName: 'Chen C.', phone: '0921•••166', phones: ['0921•••166'], visits: 2, spent: 4000, lastVisit: '2026-08-22', note: '可接受外出場地' },
  { id: 'VIP-0004', vipSerial: 'VIP-0004', name: '張先生', lineName: 'Sean', phone: '0933•••905', phones: ['0933•••905'], visits: 6, spent: 15000, lastVisit: '2026-08-22', note: '晚間時段' },
  { id: 'VIP-0005', vipSerial: 'VIP-0005', name: '何先生', lineName: 'Hao', phone: '0955•••100', phones: ['0955•••100'], visits: 1, spent: 1500, lastVisit: '2026-08-22', note: '新客' },
];

export const promotions = [
  { id: 'PR-BIRTHDAY', name: '生日月優惠', kind: '固定折扣', value: 300, period: '生日當月', active: true },
  { id: 'PR-NEW-STAFF', name: '新進師傅體驗優惠', kind: '固定折扣', value: 200, period: '期間限定', active: true },
  { id: 'PR-WEEKDAY', name: '平日下午優惠', kind: '固定折扣', value: 200, period: '平日 17:00 前', active: true },
  { id: 'PR-FIRST', name: '首次到店優惠', kind: '固定折扣', value: 200, period: '首次預約', active: true },
  { id: 'PR-001', name: '午夜服務費', kind: '固定加價', value: 600, period: '每日 00:00–06:00', active: true },
  { id: 'PR-002', name: '預約加時', kind: '每 30 分鐘', value: 500, period: '長期', active: true },
  { id: 'PR-003', name: '現場加時', kind: '每 30 分鐘', value: 700, period: '長期', active: true },
  { id: 'PR-004', name: '外出里程費', kind: '每公里', value: 80, period: '超過 3 公里', active: true },
];

export const adminUsers = [
  { username: 'admin', displayName: 'Admin', role: '系統管理員', status: '啟用', lastLogin: '今天 15:42' },
  { username: 'jerry', displayName: 'Jerry', role: '店長', status: '啟用', lastLogin: '今天 14:06' },
  { username: 'counter-01', displayName: '晚班櫃台', role: '櫃台', status: '啟用', lastLogin: '昨天 23:18' },
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
