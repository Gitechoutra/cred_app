import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { endpoints } from '../../api/client';
import { TransactionRow } from '../../components/domain';
import { PageHeader, IconReceipt } from '../../components/layout/AppShell';
import { Card, EmptyState, Skeleton, Tabs } from '../../components/ui';
import { useFetch } from '../../hooks/useProfile';
import { date, money } from '../../utils/format';

const FILTERS = [
  { value: '', label: 'All' },
  { value: 'EMI_MANUAL_PAY', label: 'EMIs' },
];

export default function Transactions() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('');

  const { data, loading } = useFetch(
    () => endpoints.transactions.list(filter ? `?type=${filter}` : ''),
    [filter],
  );
  const { data: summary } = useFetch(() => endpoints.transactions.summary(), []);

  const transactions = data || [];

  // Grouped by day so a long history reads as a timeline rather than a wall.
  const grouped = useMemo(() => {
    const buckets = new Map();

    transactions.forEach((transaction) => {
      const key = new Date(transaction.created_on).toDateString();
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(transaction);
    });

    return Array.from(buckets.entries());
  }, [transactions]);

  return (
    <div>
      <div className="mx-auto w-full max-w-3xl">
        <PageHeader title="Transactions" back="/home" />

        <div className="px-4 pt-4">
          {summary && (
            <section className="mb-4 rounded-2xl border border-line bg-mist/60 p-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-2xs uppercase tracking-wider text-slate">
                    Total transacted
                  </p>
                  <p className="money mt-1 text-lg font-bold text-ink">
                    {money(summary.total_transacted)}
                  </p>
                </div>
                <div>
                  <p className="text-2xs uppercase tracking-wider text-slate">Fees paid</p>
                  <p className="money mt-1 text-lg font-bold text-ink">
                    {money(summary.total_fees_paid)}
                  </p>
                </div>
              </div>
            </section>
          )}

          <Tabs tabs={FILTERS} active={filter} onChange={setFilter} className="mb-4" />

          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-14 w-full rounded-xl" />
              ))}
            </div>
          ) : transactions.length === 0 ? (
            <div className="pt-10">
              <EmptyState
                icon={<IconReceipt className="h-6 w-6" />}
                title="No transactions yet"
                description="Your card spends and EMI payments will appear here with full receipts."
              />
            </div>
          ) : (
            <div className="space-y-5">
              {grouped.map(([day, items]) => (
                <section key={day}>
                  <p className="mb-1 px-1 text-2xs font-semibold uppercase tracking-wider text-slate">
                    {date(items[0].created_on)}
                  </p>

                  <Card className="divide-y divide-line py-0">
                    {items.map((transaction) => (
                      <TransactionRow
                        key={transaction.transaction_id}
                        transaction={transaction}
                        onClick={() => navigate(`/transactions/${transaction.transaction_id}`)}
                      />
                    ))}
                  </Card>
                </section>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
