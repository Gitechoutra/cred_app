import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { CardTile } from '../../components/domain';
import { PageHeader } from '../../components/layout/AppShell';
import { Button, Card, EmptyState, Input, Row, Sheet, Skeleton } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { date, money, statusLabel } from '../../utils/format';
import { PayBillModal } from './PayBillModal';

export default function CardDetail() {
  const { cardId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const { data: card, loading, refetch } = useFetch(
    () => endpoints.cards.get(cardId),
    [cardId],
  );

  const [editing, setEditing] = useState(false);
  const [confirmUnlink, setConfirmUnlink] = useState(false);
  const [working, setWorking] = useState(false);
  const [form, setForm] = useState({});
  const [isPayModalOpen, setIsPayModalOpen] = useState(false);

  function openEditor() {
    setForm({
      nickname: card.nickname || '',
      card_limit: card.card_limit ?? '',
      outstanding_amount: card.outstanding_amount ?? '',
      current_due_amount: card.current_due_amount ?? '',
      due_day: card.due_day ?? '',
    });
    setEditing(true);
  }

  async function save() {
    setWorking(true);
    try {
      await endpoints.cards.update(cardId, {
        nickname: form.nickname || undefined,
        card_limit: form.card_limit ? Number(form.card_limit) : undefined,
        outstanding_amount:
          form.outstanding_amount !== '' ? Number(form.outstanding_amount) : undefined,
        current_due_amount:
          form.current_due_amount !== '' ? Number(form.current_due_amount) : undefined,
        due_day: form.due_day ? Number(form.due_day) : undefined,
      });

      toast.success('Card updated.');
      setEditing(false);
      refetch();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setWorking(false);
    }
  }

  async function unlink() {
    setWorking(true);
    try {
      await endpoints.cards.unlink(cardId);
      toast.success('Card removed.');
      navigate('/cards', { replace: true });
    } catch (err) {
      toast.error(err.message);
      setWorking(false);
      setConfirmUnlink(false);
    }
  }

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
          action={
            <button
              type="button"
              onClick={openEditor}
              className="text-sm font-semibold text-mint-700"
            >
              Edit
            </button>
          }
        />

        <div className="space-y-4 px-4 pt-4">
          <CardTile card={card} onClick={openEditor} />

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
                
                <Button variant="mint" full onClick={() => setIsPayModalOpen(true)}>
                  Pay Bill
                </Button>
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
                title="Add your credit limit"
                description="We will show your utilisation and warn you before it hurts your score."
                action={<Button variant="mint" size="sm" onClick={openEditor}>Add limit</Button>}
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

          {card.recent_transfers?.length > 0 && (
            <Card className="py-1">
              <p className="px-1 py-2 text-2xs font-semibold uppercase tracking-wider text-slate">
                Recent transfers
              </p>
              <div className="divide-y divide-line">
                {card.recent_transfers.map((transfer) => (
                  <button
                    key={transfer.transfer_id}
                    type="button"
                    onClick={() => navigate(`/transfer/status/${transfer.transfer_id}`)}
                    className="flex w-full items-center justify-between gap-3 py-3 text-left"
                  >
                    <div className="min-w-0">
                      <p className="money text-sm font-medium text-ink">
                        {money(transfer.amount)}
                      </p>
                      <p className="text-2xs text-slate">{date(transfer.created_on)}</p>
                    </div>
                    <span className="shrink-0 text-2xs font-medium text-slate">
                      {statusLabel(transfer.status)}
                    </span>
                  </button>
                ))}
              </div>
            </Card>
          )}

          <div className="space-y-2 pt-2">
            <Button
              variant="mint"
              size="lg"
              full
              disabled={card.status !== 'ACTIVE'}
              onClick={() => navigate('/transfer')}
            >
              Transfer from this card
            </Button>
            <Button variant="ghost" size="lg" full onClick={() => setConfirmUnlink(true)}>
              Remove card
            </Button>
          </div>
        </div>
      </div>

      {/* ── Edit ────────────────────────────────────────────────────── */}
      <Sheet
        open={editing}
        onClose={() => setEditing(false)}
        title="Edit card details"
        footer={
          <Button variant="mint" size="lg" full loading={working} onClick={save}>
            Save changes
          </Button>
        }
      >
        <div className="space-y-4 pb-2">
          <p className="text-xs leading-relaxed text-slate">
            Automatic statement sync arrives in a later release. Until then these
            figures are yours to keep current.
          </p>

          <Input
            label="Nickname"
            placeholder="Travel card"
            value={form.nickname}
            onChange={(event) => setForm({ ...form, nickname: event.target.value })}
          />
          <Input
            label="Credit limit"
            prefix="₹"
            inputMode="numeric"
            value={form.card_limit}
            onChange={(event) =>
              setForm({ ...form, card_limit: event.target.value.replace(/\D/g, '') })
            }
          />
          <Input
            label="Outstanding amount"
            prefix="₹"
            inputMode="numeric"
            value={form.outstanding_amount}
            onChange={(event) =>
              setForm({ ...form, outstanding_amount: event.target.value.replace(/\D/g, '') })
            }
          />
          <Input
            label="Current bill due"
            prefix="₹"
            inputMode="numeric"
            value={form.current_due_amount}
            onChange={(event) =>
              setForm({ ...form, current_due_amount: event.target.value.replace(/\D/g, '') })
            }
          />
          <Input
            label="Due day of month"
            inputMode="numeric"
            maxLength={2}
            value={form.due_day}
            onChange={(event) =>
              setForm({ ...form, due_day: event.target.value.replace(/\D/g, '') })
            }
          />
        </div>
      </Sheet>

      {/* ── Unlink ──────────────────────────────────────────────────── */}
      <Sheet
        open={confirmUnlink}
        onClose={() => setConfirmUnlink(false)}
        title="Remove this card?"
        footer={
          <div className="flex gap-2">
            <Button variant="outline" size="lg" full onClick={() => setConfirmUnlink(false)}>
              Keep it
            </Button>
            <Button variant="danger" size="lg" full loading={working} onClick={unlink}>
              Remove
            </Button>
          </div>
        }
      >
        <p className="pb-2 text-sm leading-relaxed text-slate">
          We will revoke this card&rsquo;s token with your bank so it can no longer
          be charged through CashU. Your transaction history stays intact.
        </p>
      </Sheet>
      <PayBillModal 
        card={card} 
        isOpen={isPayModalOpen} 
        onClose={() => setIsPayModalOpen(false)} 
        onSuccess={() => {
          setIsPayModalOpen(false);
          refetch();
        }}
      />
    </div>
  );
}
