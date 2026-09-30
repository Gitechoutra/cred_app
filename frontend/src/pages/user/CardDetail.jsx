import { Link, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { CardTile } from '../../components/domain';
import { PageHeader } from '../../components/layout/AppShell';
import { Card, EmptyState, Row, Skeleton } from '../../components/ui';
import { useFetch } from '../../hooks/useProfile';
import { date, money, statusLabel } from '../../utils/format';

export default function CardDetail() {
  const { cardId } = useParams();

  const { data: card, loading } = useFetch(
    () => endpoints.cards.get(cardId),
    [cardId],
  );

  if (loading) {
    return (
      <div className="">
        <PageHeader title="Card" back="/cards" />
        <div className="space-y-4 px-4 pt-4">
          <Skeleton className="h-[156px] w-full rounded-2xl" />
          <Skeleton className="h-40 w-full rounded-2xl" />
        </div>
      </div>
    );
  }

  if (!card) {
    return (
      <div className="">
        <PageHeader title="Card" back="/cards" />
        <EmptyState title="Card not found" description="This card is no longer linked." />
      </div>
    );
  }

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader
          title={card.nickname || card.issuer_bank}
          subtitle={card.masked_pan}
          back="/cards"
        />

        <div className="space-y-4 px-4 pt-4">
          <CardTile card={card} />

          {card.current_due_amount > 0 && (
            <Card className="bg-canvas shadow-[0_4px_24px_rgba(0,0,0,0.06)] border-mint-200">
              <div className="p-1">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <p className="text-2xs font-semibold uppercase tracking-wider text-slate">Total Due</p>
                    <p className="text-2xl font-bold text-ink tracking-tight">{money(card.current_due_amount)}</p>
                  </div>
                  {card.next_due_date && (
                    <div className="text-right">
                      <p className="text-2xs font-semibold uppercase tracking-wider text-slate">Due Date</p>
                      <p className="text-sm font-medium text-ink">{date(card.next_due_date)}</p>
                    </div>
                  )}
                </div>
                
                {card.minimum_due_amount > 0 && (
                  <p className="text-xs text-slate mb-4">
                    Minimum due: <span className="font-medium text-ink">{money(card.minimum_due_amount)}</span>
                  </p>
                )}
                
                {/* Paying an external card's bill is not something this
                    platform has a rail for, so it does not offer a button that
                    cannot work. The due date is tracked here; the payment is
                    made with the issuer. CashU's own credit line is paid from
                    /credit/pay. */}
                <p className="text-2xs leading-relaxed text-slate">
                  Pay this bill with {card.issuer_bank || 'your issuer'} directly.
                  CashU tracks the due date so you do not miss it.
                </p>
              </div>
            </Card>
          )}

          {card.card_limit ? (
            <Card>
              <p className="text-2xs font-semibold uppercase tracking-wider text-slate">
                Limit usage
              </p>

              <div className="mt-3 grid grid-cols-3 gap-3 text-center">
                <div>
                  <p className="money text-base font-bold text-ink">
                    {money(card.available_limit)}
                  </p>
                  <p className="mt-0.5 text-2xs text-slate">Available</p>
                </div>
                <div className="border-x border-line">
                  <p className="money text-base font-bold text-ink">
                    {money(card.outstanding_amount)}
                  </p>
                  <p className="mt-0.5 text-2xs text-slate">Used</p>
                </div>
                <div>
                  <p className="money text-base font-bold text-ink">
                    {money(card.card_limit)}
                  </p>
                  <p className="mt-0.5 text-2xs text-slate">Total</p>
                </div>
              </div>
            </Card>
          ) : (
            <Card className="border-dashed">
              <EmptyState
                title="No limit on record"
                description="This card was linked before limits were set automatically."
                className="py-4"
              />
            </Card>
          )}

          <Card className="divide-y divide-line py-1">
            <Row label="Issuer" value={card.issuer_bank} />
            <Row label="Network" value={card.network} />
            <Row label="Expires" value={`${card.expiry_month}/${card.expiry_year}`} mono />
            <Row label="Status" value={statusLabel(card.status)} />
            {card.next_due_date && (
              <Row label="Next due date" value={date(card.next_due_date)} />
            )}
            {card.current_due_amount != null && (
              <Row label="Current due" value={money(card.current_due_amount)} mono />
            )}
            {card.minimum_due_amount != null && (
              <Row label="Minimum due" value={money(card.minimum_due_amount)} mono />
            )}
            <Row label="Linked on" value={date(card.linked_at)} />
          </Card>

          {/* A linked card cannot be edited or removed, so there has to be
              somewhere to go when it is lost or was entered wrongly. */}
          <p className="pt-1 text-center text-xs text-slate">
            Lost this card, or something here is wrong?{' '}
            <Link to="/support" className="font-semibold text-mint-700 hover:underline">
              Contact support
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
