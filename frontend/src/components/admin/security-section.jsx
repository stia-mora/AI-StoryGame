/* Admin — AdminSecurityPage — 安全配置。从 pages/admin.jsx 纯机械拆出,JSX / props / fetch 路径零变化。 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import CSContainer from '@cloudscape-design/components/container';
import CSHeader from '@cloudscape-design/components/header';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSButton from '@cloudscape-design/components/button';
import CSBox from '@cloudscape-design/components/box';
import CSAlert from '@cloudscape-design/components/alert';
import CSInput from '@cloudscape-design/components/input';
import CSToggle from '@cloudscape-design/components/toggle';
import CSColumnLayout from '@cloudscape-design/components/column-layout';
import CSFormField from '@cloudscape-design/components/form-field';
import CSTextarea from '@cloudscape-design/components/textarea';

/* ─────────────────────────────────────────────────────────────────
   页面 7：AdminSecurityPage — 安全配置
   ───────────────────────────────────────────────────────────────── */
export function AdminSecurityPage() {
  const { t } = useTranslation();
  const [config, setConfig] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [err, setErr] = React.useState(null);
  const [saving, setSaving] = React.useState(false);
  const [draft, setDraft] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        const res = await window.api.admin.securityConfig();
        if (!cancelled) {
          setConfig(res);
          setDraft(JSON.parse(JSON.stringify(res)));
        }
      } catch (e) {
        if (!cancelled) setErr(e?.message || t('admin_page.common.load_fail'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  function upd(path, val) {
    setDraft((d) => {
      if (!d) return d;
      const next = JSON.parse(JSON.stringify(d));
      const keys = path.split('.');
      let cur = next;
      for (let i = 0; i < keys.length - 1; i++) {
        if (!cur[keys[i]]) cur[keys[i]] = {};
        cur = cur[keys[i]];
      }
      cur[keys[keys.length - 1]] = val;
      return next;
    });
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    try {
      await window.api.admin.saveSecurityConfig(draft);
      setConfig(draft);
      window.toast?.(t('admin_page.security.save_ok'), { kind: 'ok' });
    } catch (e) {
      window.toast?.(t('admin_page.security.save_fail') + ': ' + (e?.message || ''), { kind: 'danger' });
    } finally {
      setSaving(false);
    }
  }

  const d = draft || {};

  return (
    <CSSpaceBetween size="l">
      {err && <CSAlert type="error" header={t('admin_page.common.load_fail')}>{err}</CSAlert>}
      {loading
        ? <CSBox key="loading" color="inherit">{t('admin_page.common.loading')}</CSBox>
        : !draft
          ? <CSBox key="empty" textAlign="center" color="inherit">{t('admin_page.security.empty')}</CSBox>
          : null}
      {!loading && draft && (
        <CSContainer key="rate-limit" header={<CSHeader variant="h2">{t('admin_page.security.rate_limit_title')}</CSHeader>}>
          <CSAlert type="info">{t('admin_page.security.rate_limit_notice')}</CSAlert>
          <CSSpaceBetween size="m">
            <CSColumnLayout columns={3} variant="text-grid">
              <CSFormField label={t('admin_page.security.field_max_per_ip')}>
                <CSInput
                  type="number"
                  value={String(d.rate_limit_per_ip ?? '')}
                  onChange={({ detail }) => upd('rate_limit_per_ip', Number(detail.value))}
                />
              </CSFormField>
              <CSFormField label={t('admin_page.security.field_max_per_user')}>
                <CSInput
                  type="number"
                  value={String(d.rate_limit_per_user ?? '')}
                  onChange={({ detail }) => upd('rate_limit_per_user', Number(detail.value))}
                />
              </CSFormField>
              <CSFormField label={t('admin_page.security.field_window_min')}>
                <CSInput
                  type="number"
                  value={String(d.rate_window_minutes ?? '')}
                  onChange={({ detail }) => upd('rate_window_minutes', Number(detail.value))}
                />
              </CSFormField>
            </CSColumnLayout>
          </CSSpaceBetween>
        </CSContainer>
      )}
      {!loading && draft && (
        <CSContainer key="password" header={<CSHeader variant="h2">{t('admin_page.security.password_title')}</CSHeader>}>
          <CSSpaceBetween size="m">
            <CSColumnLayout columns={2} variant="text-grid">
              <CSFormField label={t('admin_page.security.field_min_length')}>
                <CSInput
                  type="number"
                  value={String(d.password_min_length ?? '')}
                  onChange={({ detail }) => upd('password_min_length', Number(detail.value))}
                />
              </CSFormField>
              <CSFormField label={t('admin_page.security.field_require_digit')}>
                <CSToggle
                  checked={!!d.password_require_numbers}
                  onChange={({ detail }) => upd('password_require_numbers', detail.checked)}
                >
                  {d.password_require_numbers ? t('admin_page.security.digit_yes') : t('admin_page.security.digit_no')}
                </CSToggle>
              </CSFormField>
            </CSColumnLayout>
          </CSSpaceBetween>
        </CSContainer>
      )}
      {!loading && draft && (
        <CSContainer key="session" header={<CSHeader variant="h2">{t('admin_page.security.session_title')}</CSHeader>}>
          <CSFormField label={t('admin_page.security.field_session_timeout')}>
            <CSInput
              type="number"
              value={String(d.session_timeout_days ?? '')}
              onChange={({ detail }) => upd('session_timeout_days', Number(detail.value))}
              style={{ maxWidth: 200 }}
            />
          </CSFormField>
        </CSContainer>
      )}
      {!loading && draft && (
        <CSContainer key="lockout" header={<CSHeader variant="h2">{t('admin_page.security.lockout_title')}</CSHeader>}>
          <CSColumnLayout columns={2} variant="text-grid">
            <CSFormField label={t('admin_page.security.field_max_attempts')}>
              <CSInput
                type="number"
                value={String(d.login_lock_threshold ?? '')}
                onChange={({ detail }) => upd('login_lock_threshold', Number(detail.value))}
              />
            </CSFormField>
            <CSFormField label={t('admin_page.security.field_lockout_minutes')}>
              <CSInput
                type="number"
                value={String(d.login_lock_duration_min ?? '')}
                onChange={({ detail }) => upd('login_lock_duration_min', Number(detail.value))}
              />
            </CSFormField>
          </CSColumnLayout>
        </CSContainer>
      )}
      {!loading && draft && (
        <CSContainer key="ip-blocklist" header={<CSHeader variant="h2">{t('admin_page.security.ip_blocklist_title')}</CSHeader>}>
          <CSFormField label={t('admin_page.security.field_ip_blocklist')}>
            <CSTextarea
              value={Array.isArray(d.ip_blocklist) ? d.ip_blocklist.join('\n') : (d.ip_blocklist || '')}
              onChange={({ detail }) => upd('ip_blocklist', detail.value.split('\n').map((s) => s.trim()).filter(Boolean))}
              rows={6}
              placeholder="192.168.1.1&#10;10.0.0.0/8"
            />
          </CSFormField>
        </CSContainer>
      )}
      {!loading && draft && (
        <CSBox key="save-btn" float="right">
          <CSButton variant="primary" loading={saving} onClick={save}>{t('admin_page.security.save_btn')}</CSButton>
        </CSBox>
      )}
    </CSSpaceBetween>
  );
}
