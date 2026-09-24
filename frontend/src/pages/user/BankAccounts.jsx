import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { BankRow } from '../../components/domain';
import { IconBank, IconPlus, PageHeader } from '../../components/layout/AppShell';
import { Button, Card, EmptyState, Row, Sheet, Skeleton } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { date, money } from '../../utils/format';

export default function BankAccounts() {
  const navigate = useNavigate();
  const toast = useToast();

  const { data, loading, refetch } = useFetch(() => endpoints.banks.list(), []);

  const [selected, setSelected] = useState(null);
  const [working, setWorking] = useState(false);

  async function act(action, message) {
    setWorking(true);
    try {
      await action();
      toast.success(message);
      setSelected(null);
      refetch();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setWorking(false);
    }
  }

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader
          title="Bank accounts"
          subtitle={data ? `${data.verified_count} verified` : undefined}
          back="/profile"
          action={
            <button
              type="button"
              onClick={() => navigate('/banks/add')}
              aria-label="Add account"
              className="grid h-9 w-9 place-items-center rounded-full text-ink transition hover:bg-mist"
            >
              <IconPlus className="h-5 w-5" />
            </button>
          }
        />

        <div className="px-4 pt-4">
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-[70px] w-full rounded-2xl" />
              <Skeleton className="h-[70px] w-full rounded-2xl" />
            </div>
          ) : !data?.accounts.length ? (
            <div className="pt-10">
              <EmptyState
                icon={<IconBank className="h-6 w-6" />}
                title="No bank accounts"
                description="Add an account to pay your card bill and EMIs. We verify it belongs to you by sending ₹1 and checking the name your bank holds."
                action={
                  <Button variant="mint" onClick={() => navigate('/banks/add')}>
                    Add account
                  </Button>
                }
              />
            </div>
          ) : (
            <div className="space-y-2">
              {data.accounts.map((account) => (
                <BankRow
                  key={account.bank_account_id}
                  account={account}
                  onClick={() => setSelected(account)}
                />
              ))}

              <button
                type="button"
                onClick={() => navigate('/banks/add')}
                className="flex w-full items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-line py-4 text-sm font-medium text-slate transition hover:border-ink/20 hover:text-ink"
              >
                <IconPlus className="h-4 w-4" />
                Add another account
              </button>
            </div>
          )}
        </div>
      </div>

      <Sheet
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={selected?.bank_name}
        footer={
          selected && (
            <div className="space-y-2">
              {!selected.is_payout_eligible && (
                <Button
                  variant="mint"
                  size="lg"
                  full
                  loading={working}
                  onClick={() =>
                    act(
                      () => endpoints.banks.verify(selected.bank_account_id),
                      'Verification re-run.',
                    )
                  }
                >
                  Retry verification
                </Button>
              )}

              {selected.is_payout_eligible && !selected.is_primary && (
                <Button
                  variant="outline"
                  size="lg"
                  full
                  loading={working}
                  onClick={() =>
                    act(
                      () => endpoints.banks.setPrimary(selected.bank_account_id),
                      'Primary account updated.',
                    )
                  }
                >
                  Make primary
                </Button>
              )}

              <Button
                variant="ghost"
                size="lg"
                full
                loading={working}
                onClick={() =>
                  act(
                    () => endpoints.banks.remove(selected.bank_account_id),
                    'Account removed.',
                  )
                }
              >
                Remove account
              </Button>
            </div>
          )
        }
      >
        {selected && (
          <div className="pb-2">
            <Card className="divide-y divide-line py-1">
              <Row label="Account" value={selected.masked_account} mono />
              <Row label="IFSC" value={selected.ifsc_code} mono />
              {selected.branch_name && <Row label="Branch" value={selected.branch_name} />}
              <Row label="Type" value={selected.account_type} />
              {selected.balance != null && (
                <Row label="Available balance" value={money(selected.balance)} mono />
              )}
              {selected.verified_cbs_name && (
                <Row label="Name at bank" value={selected.verified_cbs_name} />
              )}
              {selected.name_match_score != null && (
                <Row
                  label="Name match"
                  value={`${selected.name_match_score}%`}
                  tone={selected.name_match_score >= 80 ? 'good' : 'alert'}
                  mono
                />
              )}
              {selected.verified_at && (
                <Row label="Verified on" value={date(selected.verified_at)} />
              )}
            </Card>

            {!selected.is_payout_eligible && (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3.5">
                <p className="text-xs leading-relaxed text-amber-900">
                  This account cannot be used yet. The name your bank
                  holds must match your KYC name closely enough for us to confirm
                  the account is yours — a rule we are required to enforce.
                </p>
              </div>
            )}
          </div>
        )}
      </Sheet>
    </div>
  );
}
