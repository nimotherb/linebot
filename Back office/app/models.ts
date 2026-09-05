export type AppointmentStatus = '待確認' | '已確認' | '已完成';

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
  venueId?: number;
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
  phone?: string;
  phoneChangePending?: boolean;
  requestedPhone?: string;
  isOnline: boolean;
  privateProfile: boolean;
  returnRuleSetId?: number;
  photoUrl?: string;
  height?: string;
  weight?: string;
  role?: '攻擊手' | '守備方' | '無特定' | '攻守兼備';
};

export type Shift = {
  id: string;
  apiId?: number;
  staff: string;
  staffId?: string;
  date: string;
  start: string;
  endDate: string;
  end: string;
  source: '師傅連結' | '師傅上線' | '客服' | '店長' | 'Admin';
  locked?: boolean;
};

export type Customer = {
  id: string;
  apiId?: number;
  vipSerial: string;
  grade: 'SSR' | 'SR' | 'R' | 'N';
  name: string;
  lineName: string;
  phone: string;
  phones: string[];
  visits: number;
  spent: number;
  lastVisit: string;
  note: string;
};
