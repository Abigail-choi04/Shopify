/**
 * ShopMate AI — "You asked / The agent searched" (replanning, made visible)
 *
 * When nothing met every requirement, the agent loosens the request and searches again. This panel
 * puts the two side by side so the shopper (and the audience) can see exactly what was given up:
 * the budget that was raised, or the requirement that was dropped.
 *
 * Everything shown is computed from the response: `parsedIntent` is what the shopper asked for, and each
 * entry in `relaxations` is one change that was applied.
 */

function inr(value) {
  return `₹${Math.round(value).toLocaleString('en-IN')}`
}

function ChangeComparison({ parsedIntent, relaxations }) {
  if (!relaxations || relaxations.length === 0) return null

  const raised = relaxations.filter((r) => r.kind === 'raise_budget' && r.newBudget != null)
  const searchedBudget = raised.length > 0 ? inr(raised[raised.length - 1].newBudget) : null
  const dropped = relaxations.filter((r) => r.kind === 'drop_requirement' && r.requirement).map((r) => r.requirement)
  const keptMustHaves = parsedIntent.mustHaves.filter((m) => !dropped.includes(m))
  const unlocked = Math.max(...relaxations.map((r) => r.productsUnlocked || 0))

  return (
    <div className="change-compare" role="note">
      <span className="change-compare__title">What the agent changed to find matches</span>
      <div className="change-compare__grid">
        <div className="change-compare__col">
          <span className="change-compare__heading">You asked for</span>
          <dl>
            <dt>Category</dt>
            <dd>{parsedIntent.category}</dd>
            <dt>Budget</dt>
            <dd className={searchedBudget ? 'change-compare__old' : ''}>{parsedIntent.budget}</dd>
            <dt>Must-haves</dt>
            <dd>
              {parsedIntent.mustHaves.length === 0
                ? '—'
                : parsedIntent.mustHaves.map((m) => (
                    <span key={m} className={dropped.includes(m) ? 'change-compare__old' : ''}>
                      {m}
                      {', '}
                    </span>
                  ))}
            </dd>
          </dl>
        </div>
        <div className="change-compare__arrow" aria-hidden="true">
          →
        </div>
        <div className="change-compare__col change-compare__col--new">
          <span className="change-compare__heading">The agent searched for</span>
          <dl>
            <dt>Category</dt>
            <dd>{parsedIntent.category}</dd>
            <dt>Budget</dt>
            <dd className={searchedBudget ? 'change-compare__new' : ''}>{searchedBudget || parsedIntent.budget}</dd>
            <dt>Must-haves</dt>
            <dd>{keptMustHaves.length === 0 ? '—' : keptMustHaves.join(', ')}</dd>
          </dl>
        </div>
      </div>

      <ul className="change-compare__list">
        {relaxations.map((relaxation, index) => (
          <li key={index}>
            {relaxation.message}
            <span className="relax-note__who">
              {relaxation.chosenBy === 'model'
                ? 'Chosen by the agent from the options the catalog allowed'
                : 'Chosen by the fixed fallback rule'}
            </span>
          </li>
        ))}
      </ul>
      <p className="change-compare__foot">
        Category and any brand you named are never changed.
        {unlocked > 0 && ` This change brought back ${unlocked} matching product${unlocked === 1 ? '' : 's'}.`}
        {' '}Claims below are still checked against your original budget.
      </p>
    </div>
  )
}

export default ChangeComparison