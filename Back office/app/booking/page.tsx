'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import { PublicBookingAvailability, PublicBookingOptions, resolveStaffPhotoUrl, SpaApi } from '../api-client';
import styles from './booking.module.css';
import flowStyles from './booking-flow.module.css';

type Stage = 'details' | 'review' | 'success';
type IdentityMode = 'loading' | 'line' | 'web';
type BookingMode = 'scheduled' | 'requested';

type LiffClient = {
  init: (config: { liffId: string }) => Promise<void>;
  isLoggedIn: () => boolean;
  login: (config?: { redirectUri?: string }) => void;
  getIDToken: () => string | null;
  getDecodedIDToken: () => { name?: string } | null;
  isInClient: () => boolean;
  closeWindow: () => void;
};

declare global { interface Window { liff?: LiffClient } }

const loadLiff = () => new Promise<LiffClient>((resolve, reject) => {
  if (window.liff) return resolve(window.liff);
  const existing = document.querySelector<HTMLScriptElement>('script[data-equalspa-liff]');
  const script = existing || document.createElement('script');
  script.dataset.equalspaLiff = 'true';
  script.src = 'https://static.line-scdn.net/liff/edge/2/sdk.js';
  script.onload = () => window.liff ? resolve(window.liff) : reject(new Error('LIFF SDK 未載入'));
  script.onerror = () => reject(new Error('LIFF SDK 載入失敗'));
  if (!existing) document.head.appendChild(script);
});

const taipeiInputValue = (leadMinutes = 90) => {
  const block = 30 * 60 * 1000;
  const rounded = Math.ceil((Date.now() + leadMinutes * 60 * 1000) / block) * block;
  const value = new Date(rounded).toLocaleString('sv-SE', {
    timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  });
  return value.replace(' ', 'T');
};

const money = (value: number) => `NT$ ${value.toLocaleString('zh-TW')}`;
const categoryLabel = (value?: string) => value === 'straight' ? '直男師傅' : value === 'bisexual' ? '雙性師傅' : '圈內師傅';

const normalizeStaffName = (value: string) => value.normalize('NFKC').replace(/\s+/g, '').toLocaleLowerCase('zh-TW');

const readBookingIntent = () => {
  const params = new URLSearchParams(window.location.search);
  const hash = window.location.hash.slice(1);
  const hashQuery = hash.includes('?') ? hash.slice(hash.indexOf('?') + 1) : hash.includes('=') ? hash : '';
  const hashParams = new URLSearchParams(hashQuery);
  const value = (key: string) => params.get(key) || hashParams.get(key) || '';
  const requestedId = value('staff_id') || value('requested_staff_id');
  const requestedName = value('staff_name') || value('therapist') || value('therapist_name');
  const source = value('source').toLocaleLowerCase();
  return {
    requestedId,
    requestedName,
    requested: Boolean(requestedId || requestedName || source === 'official' || source === 'official_website'),
  };
};

export default function BookingPage() {
  const api = useMemo(() => new SpaApi(), []);
  const [stage, setStage] = useState<Stage>('details');
  const [options, setOptions] = useState<PublicBookingOptions | null>(null);
  const [availability, setAvailability] = useState<PublicBookingAvailability | null>(null);
  const [serviceId, setServiceId] = useState('');
  const [promotionId, setPromotionId] = useState('');
  const [staffId, setStaffId] = useState('');
  const [startTime, setStartTime] = useState(taipeiInputValue());
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [orderId, setOrderId] = useState('');
  const [idempotencyKey, setIdempotencyKey] = useState('');
  const [idToken, setIdToken] = useState('');
  const [identityMode, setIdentityMode] = useState<IdentityMode>('loading');
  const [identityMessage, setIdentityMessage] = useState('正在確認開啟方式');
  const [insideLine, setInsideLine] = useState(false);
  const [bookingMode, setBookingMode] = useState<BookingMode>('scheduled');

  useEffect(() => {
    api.publicBookingOptions()
      .then((data) => {
        setOptions(data);
        setServiceId(String(data.services[0]?.id || ''));
        const intent = readBookingIntent();
        if (intent.requested) {
          const requested = data.staff.find((item) => String(item.id) === intent.requestedId)
            || data.staff.find((item) => normalizeStaffName(item.name) === normalizeStaffName(intent.requestedName));
          setBookingMode('requested');
          if (requested) {
            setStaffId(String(requested.id));
          } else {
            setError(`找不到「${intent.requestedName || '指定師傅'}」的最新資料，請回官網重新選擇或聯絡真人客服`);
          }
        }
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : '目前無法讀取預約方案'))
      .finally(() => setLoading(false));
  }, [api]);

  useEffect(() => {
    if (!options) return;
    if (!options.line_login_enabled || !options.liff_id) {
      setIdentityMode('web');
      setIdentityMessage('一般瀏覽器模式・以手機辨識客戶');
      return;
    }
    let active = true;
    loadLiff()
      .then(async (liff) => {
        await liff.init({ liffId: options.liff_id as string });
        if (!liff.isLoggedIn()) {
          liff.login({ redirectUri: window.location.href });
          return;
        }
        const token = liff.getIDToken();
        if (!token) throw new Error('未取得 LINE 身分');
        const decoded = liff.getDecodedIDToken();
        if (!active) return;
        setIdToken(token);
        setName((current) => current || decoded?.name || '');
        setInsideLine(liff.isInClient());
        setIdentityMode('line');
        setIdentityMessage('已由 LINE 安全辨識身分');
      })
      .catch(() => {
        if (!active) return;
        setIdentityMode('web');
        setIdentityMessage('LINE 暫時無法驗證・仍可用手機預約');
      });
    return () => { active = false; };
  }, [options]);

  useEffect(() => {
    if (!serviceId || !startTime) return;
    const requestOnly = bookingMode === 'requested';
    if (requestOnly && !staffId) {
      setAvailability(null);
      setChecking(false);
      return;
    }
    let active = true;
    setChecking(true);
    setError('');
    setAvailability(null);
    api.publicBookingAvailability(Number(serviceId), startTime, requestOnly && staffId ? Number(staffId) : undefined, requestOnly)
      .then((data) => {
        if (!active) return;
        setAvailability(data);
        if (!requestOnly) setStaffId((current) => data.staff.some((item) => String(item.id) === current) ? current : '');
      })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : '目前無法確認這個時段'); })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, [api, serviceId, startTime, bookingMode, staffId]);

  const requestOnly = bookingMode === 'requested';
  const service = options?.services.find((item) => String(item.id) === serviceId);
  const promotion = options?.promotions.find((item) => String(item.id) === promotionId);
  const staff = (requestOnly ? options?.staff : availability?.staff)?.find((item) => String(item.id) === staffId);
  const discount = !promotion || !service ? 0 : promotion.calculation_type === 'fixed_discount'
    ? Math.min(service.price, promotion.value)
    : promotion.calculation_type === 'percent_discount'
      ? Math.min(service.price, Math.round(service.price * promotion.value / 100))
      : 0;
  const total = Math.max(0, (service?.price || 0) - discount);

  const review = (event: FormEvent) => {
    event.preventDefault();
    setError('');
    if (requestOnly && !staff) return setError('請先從指定師傅卡片中選擇一位師傅');
    if (!service || !availability) return setError('請先選擇可預約的方案與時段');
    if (!/^09\d{8}$/.test(phone)) return setError('手機號碼必須是 09 開頭的 10 碼數字');
    if (!name.trim()) return setError('請填寫您的稱呼');
    setIdempotencyKey(globalThis.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    setStage('review');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const submit = async () => {
    if (!service || !availability || !idempotencyKey) return;
    setSubmitting(true);
    setError('');
    try {
      const payload = {
        customer_name: name.trim(), phone, service_plan_id: service.id, start_time: startTime,
        staff_id: staff ? staff.id : null, promotion_id: promotion ? promotion.id : null,
        notes: notes.trim() || null, idempotency_key: idempotencyKey, website: '',
        id_token: idToken || null, source: requestOnly ? 'official_website' : 'booking_web',
      };
      if (requestOnly) {
        const result = await api.createPublicBookingRequest(payload);
        setOrderId(result.booking_request.request_id);
      } else {
        const result = await api.createPublicBooking(payload);
        setOrderId(result.appointment.order_id);
      }
      setStage('success');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '預約未能送出');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <main className={styles.shell}><div className={styles.loading}>正在準備預約方案…</div></main>;

  return (
    <main className={styles.shell}>
      <div className={styles.glow} aria-hidden="true" />
      <header className={styles.header}>
        <a href="/" className={styles.brand}><span>EG</span><b>伊果 SPA</b></a>
        <div className={styles.mode} data-mode={identityMode}>{identityMessage}</div>
      </header>

      <section className={styles.hero}>
        <p>RESERVATION</p>
        <h1>{stage === 'success' ? (requestOnly ? '指定需求已送出' : '預約已送出') : stage === 'review' ? '最後確認一次' : '選一段留給自己的時間'}</h1>
        <span>{stage === 'details' ? '先選擇「目前排班師傅」或「指定師傅」，兩種方式的成立規則不同。' : stage === 'review' ? (requestOnly ? '指定師傅只會送出預約通知，必須由客服確認後才會成立。' : '目前尚未建立訂單，按下確認後才會正式送出。') : (requestOnly ? '客服已收到指定需求；師傅尚未被正式預訂。' : '客服與指定師傅已收到這筆預約。')}</span>
      </section>

      <nav className={styles.steps} aria-label="預約進度">
        {['填寫資料', '確認明細', '完成'].map((label, index) => {
          const active = stage === 'details' ? 0 : stage === 'review' ? 1 : 2;
          return <div className={index <= active ? styles.stepActive : styles.step} key={label}><i>{index + 1}</i><span>{label}</span></div>;
        })}
      </nav>

      {error && <div className={styles.error} role="alert">{error}</div>}

      {stage === 'details' && <form className={styles.card} onSubmit={review}>
        <section>
          <div className={styles.sectionTitle}><span>01</span><div><h2>選擇方案</h2><p>價格與時間會以送出當下的後端設定為準</p></div></div>
          <div className={styles.serviceGrid}>
            {options?.services.map((item) => <button type="button" key={item.id} onClick={() => setServiceId(String(item.id))} className={serviceId === String(item.id) ? styles.serviceSelected : styles.service}>
              <span>{item.code}</span><strong>{item.name}</strong><small>{item.duration_minutes} 分鐘・{money(item.price)}</small>
            </button>)}
          </div>
        </section>

        <section>
          <div className={styles.sectionTitle}><span>02</span><div><h2>日期與師傅</h2><p>選擇直接預約目前排班師傅，或指定任一位在職師傅交由客服確認</p></div></div>
          <div className={flowStyles.bookingModeGrid} role="radiogroup" aria-label="師傅選擇方式">
            <button type="button" role="radio" aria-checked={bookingMode === 'scheduled'} className={bookingMode === 'scheduled' ? flowStyles.bookingModeSelected : flowStyles.bookingMode} onClick={() => { setBookingMode('scheduled'); setStaffId(''); setAvailability(null); setError(''); }}>
              <i>01</i><span><strong>目前排班師傅</strong><small>只顯示有正式排班且沒有撞單的師傅，可直接成立預約。</small></span>
            </button>
            <button type="button" role="radio" aria-checked={bookingMode === 'requested'} className={bookingMode === 'requested' ? flowStyles.bookingModeSelected : flowStyles.bookingMode} onClick={() => { setBookingMode('requested'); setStaffId(''); setAvailability(null); setError(''); }}>
              <i>02</i><span><strong>指定師傅</strong><small>瀏覽全部在職師傅；送出後由客服確認，不會立即成立預約。</small></span>
            </button>
          </div>
          <label className={styles.field}>預約開始時間<input type="datetime-local" value={startTime} min={taipeiInputValue(options?.minimum_lead_minutes || 90)} step="1800" onChange={(event) => setStartTime(event.target.value)} required /></label>
          <div className={styles.availabilityLine}>{checking ? '正在確認時間…' : availability ? (requestOnly ? `已選擇 ${staff?.name}・預計結束 ${availability.end_time.slice(11, 16)}・等待客服人工確認` : `${availability.staff.length} 位師傅目前可預約・結束時間 ${availability.end_time.slice(11, 16)}`) : requestOnly ? '請從下方卡片選擇希望指定的師傅' : '這個時段暫無可直接預約的師傅，可改用「指定師傅」送出通知'}</div>
          {requestOnly && <div className={flowStyles.requestedRail} role="listbox" aria-label="全部在職師傅">
            {options?.staff.map((item) => {
              const photo = resolveStaffPhotoUrl(item.photo_url);
              const selected = staffId === String(item.id);
              return <button type="button" role="option" aria-selected={selected} key={item.id} onClick={() => setStaffId(String(item.id))} className={selected ? flowStyles.requestedCardSelected : flowStyles.requestedCard}>
                <span className={flowStyles.requestedPortrait}>{photo ? <img src={photo} alt={`${item.name}師傅`} loading="lazy" /> : <i>{item.name.slice(0, 1)}</i>}</span>
                <span className={flowStyles.requestedInfo}><small>{categoryLabel(item.category)}</small><strong>{item.name}</strong><em>{[item.height && `${item.height} cm`, item.weight && `${item.weight} kg`].filter(Boolean).join('・') || '資料更新中'}</em></span>
                <b>{selected ? '已選擇' : '選擇這位'}</b>
              </button>;
            })}
          </div>}
          {requestOnly && staff && <div className={styles.assignment}>已指定 {staff.name}。不論目前是否排班，都只會先送出通知並保留這位師傅，等待客服確認。</div>}
          {!requestOnly && availability?.can_choose_staff && <div className={styles.staffGrid}>
            <button type="button" onClick={() => setStaffId('')} className={!staffId ? styles.staffSelected : styles.staff}><i>?</i><span><strong>不指定</strong><small>由店長安排</small></span></button>
            {availability.staff.map((item) => <button type="button" key={item.id} onClick={() => setStaffId(String(item.id))} className={staffId === String(item.id) ? styles.staffSelected : styles.staff}><i>{item.name.slice(0, 1)}</i><span><strong>{item.name}</strong><small>{categoryLabel(item.category)}</small></span></button>)}
          </div>}
          {!requestOnly && availability && !availability.can_choose_staff && <div className={styles.assignment}>此方案不指定師傅，將由店長依班表安排。</div>}
        </section>

        <section>
          <div className={styles.sectionTitle}><span>03</span><div><h2>優惠與聯絡資料</h2><p>優惠資格將由現場或客服確認</p></div></div>
          <label className={styles.field}>優惠方案<select value={promotionId} onChange={(event) => setPromotionId(event.target.value)}><option value="">不使用優惠</option>{options?.promotions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <div className={styles.twoColumns}>
            <label className={styles.field}>您的稱呼<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：王先生" maxLength={120} required /></label>
            <label className={styles.field}>手機號碼<input value={phone} onChange={(event) => setPhone(event.target.value.replace(/\D/g, '').slice(0, 10))} placeholder="09xxxxxxxx" inputMode="numeric" pattern="09\d{8}" required /></label>
          </div>
          <label className={styles.field}>備註（選填）<textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} maxLength={1000} placeholder="特殊需求或方便聯絡的方式" /></label>
          <input className={styles.honeypot} name="website" tabIndex={-1} autoComplete="off" aria-hidden="true" />
        </section>
        <div className={styles.total}><span>預估金額<small>{promotion ? `已套用 ${promotion.name}` : '未使用優惠'}</small></span><strong>{money(total)}</strong></div>
        <button className={styles.primary} disabled={!availability || checking || (requestOnly && !staff)}>查看預約明細</button>
      </form>}

      {stage === 'review' && <section className={styles.card}>
        <div className={styles.reviewHeader}><span>{requestOnly ? '預約通知・尚未成立訂單' : '尚未送出'}</span><h2>請確認以下預約內容</h2></div>
        <dl className={styles.receipt}>
          <div><dt>預約時間</dt><dd>{startTime.replace('T', ' ')}–{availability?.end_time.slice(11, 16)}</dd></div>
          <div><dt>服務方案</dt><dd>{service?.name}・{service?.duration_minutes} 分</dd></div>
          <div><dt>師傅選擇</dt><dd>{staff?.name || '不指定，由店長安排'}・{requestOnly ? '待客服確認' : '目前排班'}</dd></div>
          <div><dt>優惠</dt><dd>{promotion?.name || '不使用優惠'}</dd></div>
          <div><dt>客戶</dt><dd>{name}・{phone}</dd></div>
          {notes && <div><dt>備註</dt><dd>{notes}</dd></div>}
        </dl>
        <div className={styles.total}><span>預估金額<small>實際金額以現場確認為準</small></span><strong>{money(total)}</strong></div>
        <div className={styles.actions}><button className={styles.secondary} onClick={() => setStage('details')}>返回修改</button><button className={styles.primary} onClick={submit} disabled={submitting}>{submitting ? '正在送出…' : requestOnly ? '確認送出預約通知' : '確認並送出預約'}</button></div>
      </section>}

      {stage === 'success' && <section className={`${styles.card} ${styles.successCard}`}>
        <div className={styles.checkmark}>✓</div><p>{requestOnly ? 'REQUEST RECEIVED' : 'BOOKING CONFIRMED'}</p><h2>{orderId}</h2><span>{requestOnly ? '這是預約通知編號，不是正式訂單編號。客服確認後才會成立預約；若需調整請聯絡真人客服。' : '請保留此訂單編號。若預約內容需要調整，請透過真人客服聯絡我們。'}</span>
        <a className={styles.primary} href={options?.support_url || 'https://lin.ee/vOq3Xvt'}>聯絡真人客服</a>
        {identityMode === 'line' && insideLine && <button className={styles.secondary} onClick={() => window.liff?.closeWindow()}>關閉預約頁</button>}
        <a className={styles.textLink} href="/booking">再預約一筆</a>
      </section>}

      <footer className={styles.footer}>伊果 SPA・預約資料將安全儲存在營運系統</footer>
    </main>
  );
}
