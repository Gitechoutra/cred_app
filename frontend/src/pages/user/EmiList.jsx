import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { EmiRow } from '../../components/domain';
import { IconEmi, IconPlus } from '../../components/layout/AppShell';
import { Button, EmptyState, Section, Skeleton } from '../../components/ui';
import { useFetch } from '../../hooks/useProfile';
import { money } from '../../utils/format';

export default function EmiList() {
  const navigate = useNavigate();
  const { data, loading } = useFetch(() => endpoints.emi.list(), []);

  if (loading) {
    return (
      <div className="space-y-3 px-4 pt-5">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-24 w-full rounded-2xl" />
        <Skeleton className="h-20 w-full rounded-2xl" />
        <Skeleton className="h-20 w-full rounded-2xl" />
      </div>
    );
  }

  const obligations = data?.obligations || [];
  const active = obligations.filter((emi) => emi.is_active);
  const closed = obligations.filter((emi) => !emi.is_active);

  return (
    <div className="animate-fade-up pb-6">
      <header className="flex items-center justify-between px-4 pt-5 pb-3">
        <div>
          <h1 className="text-xl font-bold text-ink">Your EMIs</h1>
          <p className="text-xs text-slate">
            {active.length} active {active.length === 1 ? 'loan' : 'loans'}
          </p>
        </div>

        <Button variant="outline" size="sm" onClick={() => navigate('/emi/add')}>
          <IconPlus className="h-4 w-4" />
          Add
        </Button>
      </header>

      {obligations.length === 0 ? (
        <div className="px-4 pt-10">
          <EmptyState
            icon={<IconEmi className="h-6 w-6" />}
            title="No EMIs tracked"
            description="Add your Bajaj Finserv, HDB or IDFC loan to see every due date in one calendar and pay without opening their app."
            action={
              <Button variant="mint" onClick={() => navigate('/emi/add')}>
                Add your first EMI
              </Button>
            }
          />
        </div>
      ) : (
        <div className="space-y-5 px-4">
          <section className="rounded-2xl bg-ink p-4 text-white">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-2xs text-white/55">Monthly commitment</p>
                <p className="money mt-1 text-xl font-bold">
                  {money(data.total_monthly_emi)}
                </p>
              </div>
              <div>
                <p className="text-2xs text-white/55">Total outstanding</p>
                <p className="money mt-1 text-xl font-bold text-mint">
                  {money(data.total_outstanding)}
                </p>
              </div>
            </div>

            {data.overdue_count > 0 && (
              <p className="mt-3 border-t border-white/10 pt-3 text-xs text-alert">
                {data.overdue_count} payment{data.overdue_count > 1 ? 's are' : ' is'} overdue
              </p>
            )}
          </section>

          {active.length > 0 && (
            <Section title="Active">
              <div className="space-y-2">
                {active.map((emi) => (
                  <EmiRow key={emi.emi_id} emi={emi} onClick={() => navigate(`/emi/${emi.emi_id}`)} />
                ))}
              </div>
            </Section>
          )}

          {closed.length > 0 && (
            <Section title="Closed">
              <div className="space-y-2 opacity-60">
                {closed.map((emi) => (
                  <EmiRow key={emi.emi_id} emi={emi} onClick={() => navigate(`/emi/${emi.emi_id}`)} />
                ))}
              </div>
            </Section>
          )}

          <button
            type="button"
            onClick={() => navigate('/emi/add')}
            className="flex w-full items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-line py-4 text-sm font-medium text-slate transition hover:border-ink/20 hover:text-ink"
          >
            <IconPlus className="h-4 w-4" />
            Add another loan
          </button>
        </div>
      )}
    </div>
  );
}
