import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { CardActions, CardFigures, DataSourceBadge, LastUpdated } from '../../components/cards/CardActions';
import { CardTile } from '../../components/domain';
import { IconCard, IconPlus, PageHeader } from '../../components/layout/AppShell';
import { Button, Card, EmptyState, Skeleton } from '../../components/ui';
import { useFetch } from '../../hooks/useProfile';
import { money } from '../../utils/format';

/**
 * Every card in one place: tokenised cards, whose limit CashU set, and cards
 * the holder tracks by hand. The two kinds are labelled on every card and
 * totalled separately - a limit CashU granted and a figure someone typed are
 * different kinds of number, and adding them together would mean nothing.
 */
export default function Cards() {
  const navigate = useNavigate();
  const { data, loading, error, refetch } = useFetch(() => endpoints.cards.list(), []);

  if (loading && !data) {
    return (
      <div className="space-y-4 px-4 pt-5">
        <PageHeader title="Your cards" back="/home" />
        <Skeleton className="h-24 w-full rounded-2xl" />
        <Skeleton className="h-[156px] w-full rounded-2xl" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="px-4 pt-5">
        <PageHeader title="Your cards" back="/home" />
        <Card className="text-center">
          <p className="font-semibold text-ink">Could not load your cards</p>
          <p className="mt-1 text-sm text-slate">{error.message}</p>
          <Button variant="outline" size="sm" className="mt-4" onClick={refetch}>Try again</Button>
        </Card>
      </div>
    );
  }

  const linked = data?.cards || [];
  const manual = data?.manual_cards || [];
  const all = [...linked.map((c) => ({ ...c, kind: 'TOKENISED' })), ...manual];

  return (
    <div className="animate-fade-up pb-6">
      <div className="px-4 pt-5">
        <PageHeader
          title="Your cards"
          subtitle={`${all.length} ${all.length === 1 ? 'card' : 'cards'}`}
          back="/home"
          action={(
            <Button variant="outline" size="sm" onClick={() => navigate('/cards/add')}>
              <IconPlus className="h-4 w-4" />
              Add
            </Button>
          )}
        />
      </div>

      {all.length === 0 ? (
        <div className="px-4 pt-10">
          <EmptyState
            icon={<IconCard className="h-6 w-6" />}
            title="No cards yet"
            description="Link a card for a CashU limit, or add one by hand to track its limit, balance and due date."
            action={<Button variant="mint" onClick={() => navigate('/cards/add')}>Add your first card</Button>}
          />
        </div>
      ) : (
        <div className="space-y-4 px-4">
          <div className="grid gap-3 sm:grid-cols-2">
            {linked.length > 0 && (
              <Summary
                title="Linked cards"
                note="Limits set by CashU"
                limit={data.total_limit}
                outstanding={data.total_outstanding}
              />
            )}
            {manual.length > 0 && (
              <Summary
                title="Tracked by you"
                note="User-entered - Not Bank Verified"
                limit={data.manual_totals.credit_limit}
                outstanding={data.manual_totals.outstanding_balance}
                warn
              />
            )}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {all.map((card, index) => (
              <Card
                key={card.card_id || card.manual_card_id}
                className="animate-fade-up space-y-3"
                style={{ animationDelay: `${Math.min(index, 6) * 50}ms` }}
              >
                <CardTile
                  card={card}
                  onClick={() => navigate(card.kind === 'MANUAL' ? `/cards/manual/${card.manual_card_id}` : `/cards/${card.card_id}`)}
                />
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <DataSourceBadge card={card} />
                  <LastUpdated card={card} />
                </div>
                <CardFigures card={card} />
                <CardActions card={card} onChanged={refetch} />
              </Card>
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

function Summary({ title, note, limit, outstanding, warn = false }) {
  return (
    <section className={warn ? 'rounded-2xl border border-amber-200 bg-amber-50/60 p-4' : 'rounded-2xl border border-line bg-mist/60 p-4'}>
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm font-semibold text-ink">{title}</p>
        <p className={warn ? 'text-2xs font-semibold text-amber-800' : 'text-2xs text-slate'}>{note}</p>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-4">
        <div>
          <p className="text-2xs uppercase tracking-wider text-slate">Total limit</p>
          <p className="money mt-1 text-lg font-bold text-ink">{money(limit)}</p>
        </div>
        <div>
          <p className="text-2xs uppercase tracking-wider text-slate">Outstanding</p>
          <p className="money mt-1 text-lg font-bold text-ink">{money(outstanding)}</p>
        </div>
      </div>
    </section>
  );
}
