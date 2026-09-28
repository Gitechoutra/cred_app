import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { CardTile } from '../../components/domain';
import { IconCard, IconPlus, PageHeader } from '../../components/layout/AppShell';
import { Button, EmptyState, Skeleton } from '../../components/ui';
import { useFetch } from '../../hooks/useProfile';
import { money } from '../../utils/format';

export default function Cards() {
  const navigate = useNavigate();
  const { data, loading } = useFetch(() => endpoints.cards.list(), []);

  if (loading) {
    return (
      <div className="space-y-4 px-4 pt-5">
        <PageHeader title="Your cards" back="/home" />
        <Skeleton className="h-24 w-full rounded-2xl" />
        <Skeleton className="h-[156px] w-full rounded-2xl" />
        <Skeleton className="h-[156px] w-full rounded-2xl" />
      </div>
    );
  }

  const cards = data?.cards || [];

  return (
    <div className="animate-fade-up pb-6">
      {/* The shared header, so Back looks and behaves as on every other page:
          a chevron on the left that returns to the real previous screen. The
          text button this replaces used navigate(-1), which leaves the app when
          Cards was opened from a link. */}
      <div className="px-4 pt-5">
        <PageHeader
          title="Your cards"
          subtitle={`${cards.length} ${cards.length === 1 ? 'card' : 'cards'} linked`}
          back="/home"
          action={
            <Button variant="outline" size="sm" onClick={() => navigate('/cards/add')}>
              <IconPlus className="h-4 w-4" />
              Add
            </Button>
          }
        />
      </div>

      {cards.length === 0 ? (
        <div className="px-4 pt-10">
          <EmptyState
            icon={<IconCard className="h-6 w-6" />}
            title="No cards yet"
            description="Link a credit card to track your limits, due dates and utilisation in one place."
            action={
              <Button variant="mint" onClick={() => navigate('/cards/add')}>
                Add your first card
              </Button>
            }
          />
        </div>
      ) : (
        <div className="space-y-4 px-4">
          <section className="rounded-2xl border border-line bg-mist/60 p-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-2xs uppercase tracking-wider text-slate">Total limit</p>
                <p className="money mt-1 text-lg font-bold text-ink">
                  {money(data.total_limit)}
                </p>
              </div>
              <div>
                <p className="text-2xs uppercase tracking-wider text-slate">Outstanding</p>
                <p className="money mt-1 text-lg font-bold text-ink">
                  {money(data.total_outstanding)}
                </p>
              </div>
            </div>
          </section>

          <div className="space-y-3">
            {cards.map((card) => (
              <CardTile
                key={card.card_id}
                card={card}
                onClick={() => navigate(`/cards/${card.card_id}`)}
              />
            ))}
          </div>

          <button
            type="button"
            onClick={() => navigate('/cards/add')}
            className="flex w-full items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-line py-5 text-sm font-medium text-slate transition hover:border-ink/20 hover:text-ink"
          >
            <IconPlus className="h-4 w-4" />
            Add another card
          </button>
        </div>
      )}
    </div>
  );
}
