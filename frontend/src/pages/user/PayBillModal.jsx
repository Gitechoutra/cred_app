import React, { useState } from 'react';
import { Sheet, Button, Input, cx } from '../../components/ui';
import { endpoints } from '../../api/client';
import { money } from '../../utils/format';
import { useToast } from '../../context/ToastContext';
import { PaymentSuccess } from '../../components/payments/PaymentSuccess';

export function PayBillModal({ card, isOpen, onClose, onSuccess }) {
  const [amount, setAmount] = useState(card?.current_due_amount || '');
  const [method, setMethod] = useState('upi');
  const [isProcessing, setIsProcessing] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const toast = useToast();

  if (!card) return null;

  const handlePay = async () => {
    if (!amount || Number(amount) <= 0) {
      toast.error('Please enter a valid amount.');
      return;
    }
    setIsProcessing(true);
    try {
      await endpoints.cards.payBill(card.card_id, {
        amount: Number(amount),
        payment_method: method
      });
      setShowSuccess(true);
    } catch (err) {
      toast.error(err.message || 'Payment failed.');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleSuccessComplete = () => {
    setShowSuccess(false);
    onSuccess();
  };

  const paymentMethods = [
    { id: 'upi', label: 'UPI', desc: 'Google Pay, PhonePe, Paytm' },
    { id: 'bank', label: 'Net Banking', desc: 'Direct from bank account' },
    { id: 'debit', label: 'Debit Card', desc: 'Any Visa/Mastercard' },
    { id: 'auto_pay', label: 'Auto-Pay', desc: 'Set up mandate' },
  ];

  return (
    <>
      <Sheet open={isOpen} onOpenChange={onClose} title="Pay Credit Card Bill">
        <div className="space-y-6 pb-6">
          
          <div className="space-y-4">
            <Input 
              type="number"
              label="Amount to pay"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              prefix={<span className="text-slate">₹</span>}
              className="text-xl font-medium"
            />
            
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setAmount(card.current_due_amount)}
                className="rounded-full border border-line bg-canvas px-3 py-1.5 text-xs font-medium text-ink transition hover:bg-mist"
              >
                Total Due ({money(card.current_due_amount)})
              </button>
              {card.minimum_due_amount > 0 && (
                <button
                  type="button"
                  onClick={() => setAmount(card.minimum_due_amount)}
                  className="rounded-full border border-line bg-canvas px-3 py-1.5 text-xs font-medium text-ink transition hover:bg-mist"
                >
                  Minimum ({money(card.minimum_due_amount)})
                </button>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-ink">Payment Method</h3>
            <div className="grid gap-2">
              {paymentMethods.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setMethod(m.id)}
                  className={cx(
                    "flex items-center justify-between rounded-xl border p-4 text-left transition",
                    method === m.id 
                      ? "border-mint-500 bg-mint-50/50 shadow-[0_0_0_1px_rgba(0,245,184,1)]" 
                      : "border-line bg-canvas hover:border-mint-300"
                  )}
                >
                  <div>
                    <p className="text-sm font-semibold text-ink">{m.label}</p>
                    <p className="text-xs text-slate">{m.desc}</p>
                  </div>
                  <div className={cx(
                    "flex h-5 w-5 items-center justify-center rounded-full border-2",
                    method === m.id ? "border-mint-500" : "border-line"
                  )}>
                    {method === m.id && <div className="h-2.5 w-2.5 rounded-full bg-mint-500" />}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <Button 
            variant="mint" 
            full 
            loading={isProcessing} 
            onClick={handlePay}
            className="h-12 text-base"
          >
            Pay {money(amount || 0)}
          </Button>
        </div>
      </Sheet>

      {showSuccess && <PaymentSuccess onComplete={handleSuccessComplete} />}
    </>
  );
}
