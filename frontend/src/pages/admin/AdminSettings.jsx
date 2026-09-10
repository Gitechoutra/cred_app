import { useMemo, useState } from 'react';

import { endpoints } from '../../api/client';
import { Badge, Button, Card, Input, Sheet, Skeleton, Toggle, cx } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { titleCase } from '../../utils/format';
import { AdminHeader } from './AdminLayout';

/**
 * Platform settings and feature flags (PRD 16.1).
 *
 * These are live commercial and regulatory levers - the convenience fee, the
 * transfer ceilings, the pre-debit notice window. Every change is bounded by
 * the min/max on the row and written to the admin activity log.
 *
 * The CREDIT_TO_BANK_TRANSFER flag exists because PRD open decision 1 leaves
 * that feature's legal model unresolved: it must be switchable off from here,
 * without a deploy, the moment compliance says so.
 */
export default function AdminSettings() {
  const toast = useToast();

  const { data: settings, loading, refetch } = useFetch(() => endpoints.admin.settings(), []);
  const { data: flags, refetch: refetchFlags } = useFetch(() => endpoints.admin.flags(), []);

  const [editing, setEditing] = useState(null);
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);

  const grouped = useMemo(() => {
    const buckets = new Map();
    (settings || []).forEach((setting) => {
      const key = setting.category || 'OTHER';
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(setting);
    });
    return Array.from(buckets.entries());
  }, [settings]);

  async function save() {
    setBusy(true);
    try {
      await endpoints.admin.updateSetting(editing.setting_key, value);
      toast.success(`${editing.display_name} updated.`);
      setEditing(null);
      refetch();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleFlag(flag, enabled) {
    try {
      await endpoints.admin.updateFlag(flag.flag_key, { is_enabled: enabled });
      toast.success(`${flag.display_name} ${enabled ? 'enabled' : 'disabled'}.`);
      refetchFlags();
    } catch (err) {
      toast.error(err.message);
      refetchFlags();
    }
  }

  return (
    <div>
      <AdminHeader
        title="Settings"
        subtitle="Live platform configuration. Every change is audited."
      />

      {/* ── Feature flags ───────────────────────────────────────────── */}
      <section className="mb-6">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate">
          Feature flags
        </h2>

        <Card className="divide-y divide-line py-0">
          {(flags || []).map((flag) => (
            <Toggle
              key={flag.flag_key}
              label={flag.display_name || flag.flag_key}
              description={flag.description}
              checked={flag.is_enabled}
              onChange={(enabled) => toggleFlag(flag, enabled)}
            />
          ))}

          {!flags && <Skeleton className="my-3 h-32 w-full" />}
        </Card>
      </section>

      {/* ── Settings by category ────────────────────────────────────── */}
      {loading ? (
        <Skeleton className="h-96 w-full rounded-2xl" />
      ) : (
        <div className="space-y-6">
          {grouped.map(([category, items]) => (
            <section key={category}>
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate">
                {titleCase(category)}
              </h2>

              <Card className="divide-y divide-line py-0">
                {items.map((setting) => (
                  <button
                    key={setting.setting_key}
                    type="button"
                    disabled={!setting.is_editable}
                    onClick={() => {
                      setEditing(setting);
                      setValue(setting.setting_value);
                    }}
                    className={cx(
                      'flex w-full items-center gap-4 py-3.5 text-left transition',
                      setting.is_editable ? 'hover:opacity-80' : 'cursor-default opacity-60',
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-sm font-medium text-ink">
                          {setting.display_name || setting.setting_key}
                        </p>
                        {!setting.is_editable && <Badge tone="neutral">Locked</Badge>}
                      </div>
                      {setting.description && (
                        <p className="mt-0.5 text-xs leading-relaxed text-slate">
                          {setting.description}
                        </p>
                      )}
                    </div>

                    <div className="shrink-0 text-right">
                      <p className="money text-sm font-semibold text-ink">
                        {setting.setting_value}
                      </p>
                      {setting.setting_value !== setting.default_value && (
                        <p className="text-2xs text-slate">
                          default {setting.default_value}
                        </p>
                      )}
                    </div>
                  </button>
                ))}
              </Card>
            </section>
          ))}
        </div>
      )}

      <Sheet
        open={Boolean(editing)}
        onClose={() => setEditing(null)}
        title={editing?.display_name || editing?.setting_key}
        footer={
          <Button variant="mint" size="lg" full loading={busy} onClick={save}>
            Save change
          </Button>
        }
      >
        {editing && (
          <div className="space-y-4 pb-2">
            {editing.description && (
              <p className="text-sm leading-relaxed text-slate">{editing.description}</p>
            )}

            <Input
              label="Value"
              value={value}
              autoFocus
              onChange={(event) => setValue(event.target.value)}
              hint={
                editing.min_value || editing.max_value
                  ? `Allowed range: ${editing.min_value ?? '—'} to ${editing.max_value ?? '—'}`
                  : `Default: ${editing.default_value}`
              }
            />

            <div className="rounded-lg bg-mist px-3 py-2.5">
              <p className="money text-2xs text-slate">
                Key: {editing.setting_key}
              </p>
              <p className="mt-1 text-2xs leading-relaxed text-slate">
                This takes effect immediately for every member, and is recorded in
                the admin activity log against your user id.
              </p>
            </div>
          </div>
        )}
      </Sheet>
    </div>
  );
}
