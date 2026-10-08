/**
 * ShopMate AI — Mock Cart Mandate (Phase 7 preview, hardcoded for the demo)
 *
 * Mirrors the project doc's "Mock Payment / Checkout Design": the
 * agent generates a signed-looking JSON mandate (item, price,
 * quantity, timestamp, consent) and the user must explicitly approve
 * it before anything is "purchased". No real payment logic exists —
 * this is intentionally just a UI mock of that step.
 */

import { useState } from 'react'

function CartMandateModal({ product, onApprove, onCancel }) {
  const [consentGiven, setConsentGiven] = useState(false)

  const mandate = {
    item: product.title,
    price: product.price,
    currency: 'INR',
    quantity: 1,
    timestamp: new Date().toISOString(),
    user_consent: consentGiven,
    mandate_type: 'mock_cart_mandate_v1',
  }

  return (
    <div className="modal-overlay">
      <div className="modal">
        <h2>Confirm Purchase Intent</h2>
        <p className="modal__subtitle">
          No real payment will be processed. This mimics an AP2-style cart mandate —
          a signed intent object that requires your explicit consent before any
          purchase action would proceed in a real system.
        </p>

        <pre className="mandate-json">{JSON.stringify(mandate, null, 2)}</pre>

        <label className="modal__consent-label">
          <input
            type="checkbox"
            checked={consentGiven}
            onChange={(e) => setConsentGiven(e.target.checked)}
          />
          I approve this mock purchase mandate
        </label>

        <div className="modal__actions">
          <button className="modal__cancel-btn" onClick={onCancel}>
            Cancel
          </button>
          <button
            className="modal__approve-btn"
            disabled={!consentGiven}
            onClick={() => onApprove(mandate)}
          >
            Approve mandate
          </button>
        </div>
      </div>
    </div>
  )
}

export default CartMandateModal
