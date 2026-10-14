/**
 * ShopMate AI — Cart Mandate screen (Phase 7, MOCK — no real payment)
 *
 * Walks the shopper through the real server-side flow:
 *   1. the server drafts a cart for the chosen product (its own price, not ours)
 *   2. the shopper ticks consent and approves -> the server signs the cart
 *   3. "Complete mock checkout" -> the server verifies the signature and price
 *      and returns a pretend order number
 * Every refusal from the server (price changed, expired, ...) is shown in plain words,
 * and the audit log of what happened is listed at the bottom.
 */

import { useEffect, useRef, useState } from 'react'
import { approveMandate, cancelMandate, checkoutMandate, createMandate, getMandate } from '../api'

function inr(value) {
  return `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

function timeLeft(expiresAt, now) {
  const seconds = Math.max(0, Math.floor((new Date(expiresAt).getTime() - now) / 1000))
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`
}

function CartMandateModal({ product, onClose }) {
  const [data, setData] = useState(null) // { mandate, events, storage }
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [consent, setConsent] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const startedRef = useRef(false)

  // Create the draft once when the screen opens.
  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    createMandate(product.id, 1)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setBusy(false))
  }, [product.id])

  // Tick every second for the countdown.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const run = async (action) => {
    setBusy(true)
    setError('')
    try {
      setData(await action())
    } catch (err) {
      setError(err.message)
      // Show what the server now says (e.g. it may have rejected the mandate).
      if (mandate) {
        try {
          setData(await getMandate(mandate.id))
        } catch {
          // keep the last known state
        }
      }
    } finally {
      setBusy(false)
    }
  }

  const mandate = data && data.mandate
  const status = mandate ? mandate.status : null
  const finished = status === 'completed' || status === 'cancelled' || status === 'rejected' || status === 'expired'
  const secondsLeft = mandate ? Math.floor((new Date(mandate.expires_at).getTime() - now) / 1000) : 1
  const expiredLocally = mandate && !finished && secondsLeft <= 0

  const handleCancel = async () => {
    if (mandate && !finished) {
      try {
        await cancelMandate(mandate.id)
      } catch {
        // closing anyway; the server expires the mandate by itself
      }
    }
    onClose()
  }

  const shownMandate = mandate
    ? {
        id: mandate.id,
        status: mandate.status,
        item: mandate.title,
        merchant: mandate.merchant,
        unit_price_inr: mandate.unit_price_inr,
        quantity: mandate.quantity,
        total_inr: mandate.total_inr,
        currency: mandate.currency,
        user_consent: mandate.user_consent,
        expires_at: mandate.expires_at,
        signature: mandate.signature ? `${mandate.signature.slice(0, 20)}…` : null,
        order_id: mandate.order_id,
        mandate_type: mandate.mandate_type,
      }
    : null

  return (
    <div className="modal-overlay">
      <div className="modal modal--wide">
        {status === 'completed' ? (
          <>
            <span className="confirm-stamp">✓ Dispatched</span>
            <h2>Mock order placed</h2>
            <p>
              <strong>{mandate.title}</strong> — {inr(mandate.total_inr)}
            </p>
            <p className="modal__subtitle">
              Order <strong>{mandate.order_id}</strong>. No real payment was taken and nothing was ordered from the
              seller. The server checked the signature and the price before accepting this.
            </p>
          </>
        ) : (
          <>
            <h2>Confirm Purchase Intent</h2>
            <p className="modal__subtitle">
              No real payment will be processed. This is an AP2-style cart mandate: the server records exactly what you
              approve, signs it, and refuses checkout if anything changes.
            </p>
          </>
        )}

        {busy && !mandate && <p className="mandate-status">Preparing your cart on the server…</p>}

        {mandate && (
          <>
            <div className="mandate-summary">
              <span>{mandate.title}</span>
              <span>
                {mandate.quantity} × {inr(mandate.unit_price_inr)} = <strong>{inr(mandate.total_inr)}</strong>
              </span>
              {mandate.price_note && <span className="mandate-summary__note">{mandate.price_note}</span>}
              {!finished && (
                <span className="mandate-summary__timer">
                  {expiredLocally ? 'Expired' : `Valid for ${timeLeft(mandate.expires_at, now)}`}
                </span>
              )}
            </div>

            <pre className="mandate-json">{JSON.stringify(shownMandate, null, 2)}</pre>
          </>
        )}

        {status === 'draft' && !expiredLocally && (
          <label className="modal__consent-label">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            I approve this mock purchase mandate
          </label>
        )}

        {status && finished && status !== 'completed' && (
          <p className="mandate-status mandate-status--bad">
            This mandate is {status}
            {mandate.status_reason ? `: ${mandate.status_reason}` : '.'}
          </p>
        )}

        {error && <p className="mandate-status mandate-status--bad">{error}</p>}

        <div className="modal__actions">
          {status === 'completed' || (finished && status !== 'completed') ? (
            <button className="modal__approve-btn" onClick={onClose}>
              Done
            </button>
          ) : (
            <>
              <button className="modal__cancel-btn" onClick={handleCancel}>
                Cancel
              </button>
              {status === 'draft' && (
                <button
                  className="modal__approve-btn"
                  disabled={!consent || busy || expiredLocally}
                  onClick={() => run(() => approveMandate(mandate.id, true))}
                >
                  {busy ? 'Signing…' : 'Approve mandate'}
                </button>
              )}
              {status === 'approved' && (
                <button
                  className="modal__approve-btn"
                  disabled={busy || expiredLocally}
                  onClick={() => run(() => checkoutMandate(mandate.id))}
                >
                  {busy ? 'Checking…' : 'Complete mock checkout'}
                </button>
              )}
            </>
          )}
        </div>

        {data && data.events.length > 0 && (
          <details className="audit-log">
            <summary>Audit log ({data.events.length}) · stored in {data.storage}</summary>
            <ul>
              {data.events.map((event, index) => (
                <li key={index}>
                  <span>{new Date(event.at).toLocaleTimeString()}</span> <strong>{event.event}</strong>
                  {event.detail ? ` — ${event.detail}` : ''}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  )
}

export default CartMandateModal