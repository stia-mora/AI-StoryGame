/* MobileAdmin — SectionSecurity(admin-security)。纯机械从 pages/MobileAdmin.jsx 拆出,逐字节等价。 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import { Icon } from '../icons.jsx';
import { LoadingRow, ErrRow, EmptyRow } from './shared.jsx';

/* ══════════════════════════════════════════
   Section: admin-security
══════════════════════════════════════════ */
function SectionSecurity({ nav }) {
  const { t } = useTranslation();
  const [draft, setDraft] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [err, setErr] = React.useState(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true); setErr(null);
      try { const r = await window.api.admin.securityConfig(); if (!cancelled) setDraft(JSON.parse(JSON.stringify(r))); }
      catch (e) { if (!cancelled) setErr(e?.message || t('mobile.admin.load_failed')); }
      finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, []);

  function upd(path, val) {
    setDraft((d) => {
      const next = JSON.parse(JSON.stringify(d));
      const keys = path.split('.');
      let cur = next;
      for (let i = 0; i < keys.length - 1; i++) { if (!cur[keys[i]]) cur[keys[i]] = {}; cur = cur[keys[i]]; }
      cur[keys[keys.length - 1]] = val;
      return next;
    });
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    try { await window.api.admin.saveSecurityConfig(draft); nav.toast(t('mobile.admin.save_success'), 'ok'); }
    catch (e) { nav.toast(t('mobile.admin.save_failed', { msg: e?.message || '' }), 'danger'); }
    finally { setSaving(false); }
  }

  const d = draft || {};

  const numField = (label, path, placeholder) => (
    <div key={path}>
      <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>{label}</div>
      <input type="number" value={String(d[path] ?? '')}
        onChange={(e) => upd(path, Number(e.target.value))}
        placeholder={placeholder}
        style={{ width: '100%', background: 'var(--panel-2)', border: '1px solid var(--line)', borderRadius: 10, padding: '8px 10px', color: 'var(--text)', fontSize: 14, fontFamily: 'inherit', boxSizing: 'border-box' }}
      />
    </div>
  );

  return (
    <>
      <div className="pl-head">
        <button className="pl-headbtn" onClick={() => nav.go('admin')}><Icon name="chevron_left" size={20} /></button>
        <div className="pl-head-title"><strong style={{ fontSize: 15 }}>{t('mobile.admin.section.security')}</strong></div>
      </div>
      <div className="pl-body tabbed">
        <div className="pl-pad">
          {loading ? <LoadingRow /> : err ? <ErrRow msg={err} /> : !draft ? <EmptyRow /> : (
            <>
              <div className="pl-sec">
                <div className="pl-sec-head"><h2>{t('mobile.admin.security.rate_limit_heading')}</h2></div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  {numField(t('mobile.admin.security.max_per_ip'), 'rate_limit_per_ip', '100')}
                  {numField(t('mobile.admin.security.max_per_user'), 'rate_limit_per_user', '50')}
                  {numField(t('mobile.admin.security.window_minutes'), 'rate_window_minutes', '60')}
                </div>
              </div>

              <div className="pl-sec">
                <div className="pl-sec-head"><h2>{t('mobile.admin.security.password_heading')}</h2></div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  {numField(t('mobile.admin.security.min_length'), 'password_min_length', '8')}
                </div>
                <div className="pl-row" style={{ cursor: 'pointer', marginTop: 8 }} onClick={() => upd('password_require_numbers', !d.password_require_numbers)}>
                  <span className={`pl-row-ic ${d.password_require_numbers ? 'ok' : ''}`}><Icon name={d.password_require_numbers ? 'check' : 'close'} size={17} /></span>
                  <span className="pl-row-tx"><strong style={{ fontSize: 13.5 }}>{t('mobile.admin.security.require_digit')}</strong></span>
                  <span style={{ fontSize: 12, color: d.password_require_numbers ? 'var(--ok)' : 'var(--muted)' }}>{d.password_require_numbers ? t('mobile.admin.yes') : t('mobile.admin.no')}</span>
                </div>
              </div>

              <div className="pl-sec">
                <div className="pl-sec-head"><h2>{t('mobile.admin.security.session_heading')}</h2></div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  {numField(t('mobile.admin.security.session_timeout'), 'session_timeout_days', '30')}
                  {numField(t('mobile.admin.security.max_attempts'), 'login_lock_threshold', '5')}
                  {numField(t('mobile.admin.security.lockout_minutes'), 'login_lock_duration_min', '15')}
                </div>
              </div>

              <div className="pl-sec">
                <div className="pl-sec-head"><h2>{t('mobile.admin.security.ip_blocklist_heading')}</h2></div>
                <textarea
                  value={Array.isArray(d.ip_blocklist) ? d.ip_blocklist.join('\n') : (d.ip_blocklist || '')}
                  onChange={(e) => upd('ip_blocklist', e.target.value.split('\n').map((s) => s.trim()).filter(Boolean))}
                  rows={4}
                  placeholder={t('mobile.admin.security.ip_blocklist_placeholder')}
                  style={{ width: '100%', background: 'var(--panel-2)', border: '1px solid var(--line)', borderRadius: 10, padding: '8px 10px', color: 'var(--text)', fontSize: 13, fontFamily: 'var(--font-mono)', resize: 'vertical', boxSizing: 'border-box' }}
                />
              </div>

              <button className="pl-btn-primary" style={{ width: '100%', marginTop: 8 }} onClick={save} disabled={saving}>
                {saving ? t('mobile.admin.saving') : t('mobile.admin.security.save_btn')}
              </button>
            </>
          )}
        </div>
      </div>
    </>
  );
}

export { SectionSecurity };
