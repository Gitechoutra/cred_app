import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { CardActions, CardFigures, DataSourceBadge, LastUpdated } from '../../components/cards/CardActions';
import ManualCardForm from '../../components/cards/ManualCardForm';
import ThemePicker from '../../components/cards/ThemePicker';
import { CardTile } from '../../components/domain';
import { PageHeader } from '../../components/layout/AppShell';
import { Button, Card, EmptyState, Row, Skeleton } from '../../components/ui';
import { useToast } from '../../context/ToastContext';
import { useFetch } from '../../hooks/useProfile';
import { date, money } from '../../utils/format';

/**
 * A card the holder tracks by hand: its figures, edit, refresh, colours and
 * remove. Every figure is labelled user-entered and unverified, here and
 * wherever the card appears.
 */
export default function ManualCardDetail() {
  const { manualCardId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { data: card, loading, error, setData } = useFetch(
    () => endpoints.cards.manual.get(manualCardId), [manualCardId],
  );
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState(null);

  if (loading && !card) {
    return (
      <div className="px-4 pt-5">
        <PageHeader title="Card" back="/cards" />
        <Skeleton className="h-[156px] w-full rounded-2xl" />
      </div>
    );
  }
  if (error || !card) {
    return (
      <div className="px-4 pt-5">
        <PageHeader title="Card" back="/cards" />
        <EmptyState title="Card not found" description="It may have been removed." />
      </div>
    );
  }

  async function save(body) {
    setBusy(true);
    setServerError(null);
    try {
      const response = await endpoints.cards.manual.update(card.manual_card_id, body);
      setData(response.data);
      setEditing(false);
      toast.success(response.message);
    } catch (err) {
      setServerError({ message: err.message, field: err.details?.field });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl">
      <PageHeader
        title={card.nickname || card.issuer_bank}
        subtitle={card.masked_pan}
        back="/cards"
        action={!editing && <Button size="sm" variant="outline" onClick={() => setEditing(true)}>Edit</Button>}
      />

      <div className="space-y-4 px-4 pt-4">
        {editing ? (
          <Card>
            <ManualCardForm card={card} onSubmit={save} busy={busy} serverError={serverError} submitLabel="Save changes" />
            <Button variant="ghost" full className="mt-2" onClick={() => { setEditing(false); setServerError(null); }}>
              Cancel
            </Button>
          </Card>
        ) : (
          <>
            <CardTile card={card} />
            <Card className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <DataSourceBadge card={card} />
                <LastUpdated card={card} />
              </div>
              <p className="text-xs leading-relaxed text-slate">
                You entered these figures. They are not linked to your bank and are
                not verified by it - edit the card whenever your statement changes.
              </p>
              <CardFigures card={card} />
              <CardActions
                card={card}
                showView={false}
                onChanged={(next) => (next ? setData(next) : navigate('/cards', { replace: true }))}
              />
              <ThemePicker
                card={card}
                onSave={async (theme) => {
                  const response = await endpoints.cards.manual.update(card.manual_card_id, { theme });
                  setData(response.data);
                }}
              />
            </Card>

            <Card className="divide-y divide-line py-1">
              <Row label="Bank" value={card.issuer_bank} />
              <Row label="Card type" value={card.network} />
              <Row label="Last four digits" value={card.last4} mono />
              <Row label="Statement day" value={card.statement_day || '—'} />
              <Row label="Total due" value={card.total_due != null ? money(card.total_due) : '—'} mono />
              <Row label="Added" value={date(card.created_on)} />
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
