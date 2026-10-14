/**
 * ShopMate AI — Ranked Recommendations
 *
 * Shows the real products returned by POST /chat: the ranked cards, how each
 * of the shopper's must-haves fared (confirmed from the listing / couldn't
 * confirm), a link to the listing, the verification summary, and a
 * category-adaptive comparison table.
 *
 * Products found through the web fallback ("serpapi-...") have a link only:
 * the server cannot re-check their price, so they cannot go into a mock cart.
 */

import { useState } from 'react'

const REQUIREMENT_LABELS = {
  met: { icon: '✓', className: 'req--met' },
  unknown: { icon: '?', className: 'req--unknown' },
  conflict: { icon: '!', className: 'req--unknown' },
  unsupported: { icon: '?', className: 'req--unknown' },
}

function formatPrice(value) {
  return `₹${Math.round(value).toLocaleString('en-IN')}`
}

function ProductImage({ src, alt }) {
  const [failed, setFailed] = useState(false)
  if (!src || failed) return null
  return (
    <img
      className="product-card__image"
      src={src}
      alt={alt}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  )
}

function VerificationBanner({ verification }) {
  if (!verification) return null
  const { claimsChecked, claimsVerified, claimsDropped, retried, dropped } = verification
  const allGood = claimsDropped === 0
  return (
    <div className={`verification ${allGood ? 'verification--ok' : 'verification--warn'}`}>
      <strong>
        {allGood ? '✓' : '⚠'} {claimsVerified} of {claimsChecked} statements checked against the data
      </strong>
      <span>
        {allGood
          ? retried
            ? ' — the first draft had errors, so it was rewritten and re-checked.'
            : ' — every statement below matched the product data.'
          : ` — ${claimsDropped} statement(s) could not be verified and were removed.`}
      </span>
      {!allGood && (
        <details>
          <summary>What was removed</summary>
          <ul>
            {dropped.map((item, index) => (
              <li key={index}>
                “{item.text}” — {item.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function ProductRecommendations({ result, onSelectProduct }) {
  const { products, comparisonAttributes, verification } = result

  if (products.length === 0) {
    return (
      <div className="recommendations">
        <h2 className="section-label">Recommendations</h2>
        <div className="status-box status-box--empty">
          <strong>No matching products.</strong>
          <p>The reasoning trace above explains why. Try relaxing the budget or a requirement.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="recommendations">
      <h2 className="section-label">Recommendations</h2>
      <VerificationBanner verification={verification} />

      <div className="product-grid">
        {products.map((product) => {
          const canBuy = !product.id.startsWith('serpapi-')
          return (
            <div
              key={product.id}
              className={`product-card ${product.isTopPick ? 'product-card--top-pick' : ''}`}
            >
              {product.isTopPick && <span className="product-card__badge">Best Pick</span>}
              <ProductImage src={product.imageUrl} alt={product.title} />
              <div className="product-card__icon">{product.icon}</div>
              <h3 className="product-card__title">{product.title}</h3>
              <p className="product-card__price">
                {formatPrice(product.price)}
                {product.priceIsApproximate && <span className="product-card__approx"> approx.</span>}
              </p>
              {product.priceNote && <p className="product-card__note">{product.priceNote}</p>}
              <p className="product-card__rating">
                {product.rating != null
                  ? `⭐ ${product.rating}${product.ratingCount != null ? ` (${product.ratingCount.toLocaleString('en-IN')} reviews)` : ''}`
                  : 'No rating yet'}
              </p>
              <p className="product-card__reasoning">{product.reasoning}</p>

              {product.requirements.length > 0 && (
                <ul className="req-list">
                  {product.requirements.map((req) => {
                    const meta = REQUIREMENT_LABELS[req.status] || REQUIREMENT_LABELS.unknown
                    return (
                      <li key={req.requirement} className={meta.className}>
                        <span className="req__icon">{meta.icon}</span>
                        {req.status === 'met' && req.evidence
                          ? req.evidence
                          : `${req.requirement} — couldn’t confirm`}
                      </li>
                    )
                  })}
                </ul>
              )}

              <p className="product-card__source">
                {product.source ? `${product.source} · ` : ''}source_tool_call_id: {product.sourceToolCallId}
              </p>
              {product.url && (
                <a className="product-card__link" href={product.url} target="_blank" rel="noreferrer">
                  View listing ↗
                </a>
              )}
              {canBuy ? (
                <button className="product-card__select-btn" onClick={() => onSelectProduct(product)}>
                  Select this
                </button>
              ) : (
                <p className="product-card__note">Web listing — open it to buy directly.</p>
              )}
            </div>
          )
        })}
      </div>

      <h3 className="comparison-heading">Side-by-side comparison</h3>
      <div className="comparison-table-wrap">
        <table className="comparison-table">
          <thead>
            <tr>
              <th>Product</th>
              {comparisonAttributes.map((attr) => (
                <th key={attr}>{attr}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {products.map((product) => (
              <tr key={product.id} className={product.isTopPick ? 'comparison-table__top-pick-row' : ''}>
                <td>{product.title}</td>
                {comparisonAttributes.map((attr) => (
                  <td key={attr}>{product.attributes[attr] ?? '—'}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default ProductRecommendations