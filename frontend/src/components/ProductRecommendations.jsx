/**
 * ShopMate AI — Ranked Recommendations (hardcoded demo data)
 *
 * Shows the ranked products plus a category-adaptive comparison
 * table (the comparisonAttributes list changes per scenario — e.g.
 * ANC/battery for headphones vs. cushioning/breathability for shoes,
 * vs. RAM/storage for laptops). Each card cites its sourceToolCallId,
 * mirroring the grounding requirement from the project doc.
 */

function ProductRecommendations({ scenario, onSelectProduct }) {
  const { products, comparisonAttributes } = scenario

  return (
    <div className="recommendations">
      <h2 className="section-label">Recommendations</h2>

      <div className="product-grid">
        {products.map((product) => (
          <div
            key={product.id}
            className={`product-card ${product.isTopPick ? 'product-card--top-pick' : ''}`}
          >
            {product.isTopPick && <span className="product-card__badge">Best Pick</span>}
            <div className="product-card__icon">{product.icon}</div>
            <h3 className="product-card__title">{product.title}</h3>
            <p className="product-card__price">₹{product.price.toLocaleString('en-IN')}</p>
            <p className="product-card__rating">
              ⭐ {product.rating} ({product.ratingCount.toLocaleString('en-IN')} reviews)
            </p>
            <p className="product-card__reasoning">{product.reasoning}</p>
            <p className="product-card__source">source_tool_call_id: {product.sourceToolCallId}</p>
            <button className="product-card__select-btn" onClick={() => onSelectProduct(product)}>
              Select this
            </button>
          </div>
        ))}
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
                  <td key={attr}>{product.attributes[attr]}</td>
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
