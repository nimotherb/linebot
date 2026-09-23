export type AppointmentStatus = '待確認' | '已確認' | '已完成' | '已取消';

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
  location: '店內' | '外出' | '待確認' | '已取消';
  status: AppointmentStatus;
  total: number;
  basePrice?: number;
  discountAmount?: number;
  extraAmount?: number;
  discountEmployeeAmount?: number;
  discountShopAmount?: number;
  surchargeEmployeeAmount?: number;
  surchargeShopAmount?: number;
  staffReturnAmount?: number;
  shopRecoveryAmount?: number;
  settlementOverriddenByAdminId?: number;
  settlementOverrideAt?: string;
  promotionId?: string | number;
  promotionIds?: number[];
  promotionName?: string;
  commissionAmount?: number;
  expectedReturn?: number;
  returnStatus?: string;
  payment: '未付款' | '已付款' | '部分付款' | '不入帳';
  note?: string;
};

export type StaffMember = {
  id: string;
  apiId?: number;
  name: string;
  birthday?: string;
  category: string;
  categories?: string[];
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
  bio?: string;
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
  isNextDay?: boolean;
  modifiedByAdminId?: number;
  modifiedByAdminName?: string;
};

export type Customer = {
  id: string;
  apiId?: number;
  vipSerial: string;
  grade: 'SSR' | 'SR' | 'R' | 'N';
  name: string;
  birthday?: string;
  birthdayPending?: string;
  lineName: string;
  phone: string;
  phones: string[];
  visits: number;
  spent: number;
  lastVisit: string;
  note: string;
};
