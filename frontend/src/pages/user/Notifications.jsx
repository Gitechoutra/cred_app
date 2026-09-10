import { useState } from 'react';

import { endpoints } from '../../api/client';
import { PageHeader, IconBell, IconLock } from '../../components/layout/AppShell';
import {
  Badge, Button, Card, EmptyState, Section, Skeleton, Tabs, Toggle, cx,
} from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { dateTime, statusTone } from '../../utils/format';

export default function Notifications() {
  const toast = useToast();
  const [tab, setTab] = useState('feed');

  const { data: feed, loading, refetch } = useFetch(() => endpoints.notifications.list(), []);
  const { data: prefs, refetch: refetchPrefs } = useFetch(
    () => endpoints.notifications.preferences(),
    [],
  );

  async function markAllRead() {
    try {
      await endpoints.notifications.markAllRead();
      refetch();
    } catch (err) {
      toast.error(err.message);
    }
  }

  async function updatePref(field, value) {
    try {
      await endpoints.notifications.updatePreferences({ [field]: value });
      refetchPrefs();
    } catch (err) {
      toast.error(err.message);
    }
  }

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader
          title="Notifications"
          back="/home"
          action={
            tab === 'feed' && feed?.length > 0 ? (
              <button
                type="button"
                onClick={markAllRead}
                className="text-xs font-semibold text-mint-700"
              >
                Mark all read
              </button>
            ) : null
          }
        />

        <div className="px-4 pt-4">
          <Tabs
            tabs={[
              { value: 'feed', label: 'All' },
              { value: 'settings', label: 'Settings' },
            ]}
            active={tab}
            onChange={setTab}
            className="mb-4"
          />

          {tab === 'feed' ? (
            loading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }, (_, i) => (
                  <Skeleton key={i} className="h-20 w-full rounded-2xl" />
                ))}
              </div>
            ) : !feed?.length ? (
              <div className="pt-10">
                <EmptyState
                  icon={<IconBell className="h-6 w-6" />}
                  title="Nothing yet"
                  description="Payment confirmations, due-date reminders and security alerts will appear here."
                />
              </div>
            ) : (
              <div className="space-y-2">
                {feed.map((item) => (
                  <button
                    key={item.notification_id}
                    type="button"
                    onClick={async () => {
                      if (!item.is_read) {
                        await endpoints.notifications.markRead(item.notification_id);
                        refetch();
                      }
                    }}
                    className={cx(
                      'w-full rounded-2xl border p-3.5 text-left transition',
                      item.is_read ? 'border-line bg-canvas' : 'border-mint-200 bg-mint-50',
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm font-semibold text-ink">{item.title}</p>
                      {!item.is_read && (
                        <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-mint" />
                      )}
                    </div>

                    <p className="mt-1 text-xs leading-relaxed text-slate">{item.body}</p>

                    <div className="mt-2 flex items-center gap-2">
                      <span className="text-2xs text-slate-light">
                        {dateTime(item.created_on)}
                      </span>
                      {['CRITICAL', 'HIGH'].includes(item.priority) && (
                        <Badge tone={item.priority === 'CRITICAL' ? 'alert' : 'warn'}>
                          {item.priority}
                        </Badge>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )
          ) : (
            prefs && (
              <div className="space-y-5">
                <Section title="Channels">
                  <Card className="divide-y divide-line py-0">
                    <Toggle
                      label="In-app"
                      description="Show in your notification feed"
                      checked={prefs.in_app_enabled}
                      onChange={(v) => updatePref('in_app_enabled', v)}
                    />
                    <Toggle
                      label="SMS"
                      description="Text messages to your registered number"
                      checked={prefs.sms_enabled}
                      onChange={(v) => updatePref('sms_enabled', v)}
                    />
                    <Toggle
                      label="Email"
                      description="Receipts and statements"
                      checked={prefs.email_enabled}
                      onChange={(v) => updatePref('email_enabled', v)}
                    />
                    <Toggle
                      label="WhatsApp"
                      description="Urgent reminders on WhatsApp"
                      checked={prefs.whatsapp_enabled}
                      onChange={(v) => updatePref('whatsapp_enabled', v)}
                    />
                  </Card>
                </Section>

                <Section title="What we send">
                  <Card className="divide-y divide-line py-0">
                    <Toggle
                      label="EMI reminders"
                      description="7 days and 1 day before a due date"
                      checked={prefs.emi_reminders_enabled}
                      onChange={(v) => updatePref('emi_reminders_enabled', v)}
                    />
                    <Toggle
                      label="Offers and updates"
                      description="Occasional product news"
                      checked={prefs.marketing_enabled}
                      onChange={(v) => updatePref('marketing_enabled', v)}
                    />
                  </Card>
                </Section>

                {/* Stated plainly rather than shown as a dead toggle. */}
                <Section title="Always on">
                  <Card className="space-y-3">
                    {prefs.always_on.map((item) => (
                      <div key={item.event} className="flex items-start gap-3">
                        <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-mist text-slate">
                          <IconLock className="h-3.5 w-3.5" />
                        </span>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-ink">{item.label}</p>
                          <p className="text-2xs leading-relaxed text-slate">{item.reason}</p>
                        </div>
                      </div>
                    ))}
                  </Card>
                </Section>
              </div>
            )
          )}
        </div>
      </div>
    </div>
  );
}
