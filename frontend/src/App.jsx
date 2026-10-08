import { useState, useRef } from 'react'
import './App.css'
import { pickScenario, EXAMPLE_QUERIES } from './data/scenarios'
import ReasoningTrace from './components/ReasoningTrace'
import ProductRecommendations from './components/ProductRecommendations'
import CartMandateModal from './components/CartMandateModal'

// How long each trace step stays hidden before revealing the next one.
// Purely cosmetic — simulates the agent "thinking" step by step.
const STEP_REVEAL_DELAY_MS = 650

function App() {
  const [query, setQuery] = useState('')
  const [stage, setStage] = useState('idle') // idle | thinking | results
  const [scenario, setScenario] = useState(null)
  const [visibleSteps, setVisibleSteps] = useState(0)
  const [selectedProduct, setSelectedProduct] = useState(null)
  const [orderConfirmed, setOrderConfirmed] = useState(false)
  const timeoutsRef = useRef([])

  const clearPendingTimeouts = () => {
    timeoutsRef.current.forEach(clearTimeout)
    timeoutsRef.current = []
  }

  const runPipeline = (submittedQuery) => {
    if (!submittedQuery.trim()) return

    clearPendingTimeouts()
    const matchedScenario = pickScenario(submittedQuery)

    setScenario(matchedScenario)
    setStage('thinking')
    setVisibleSteps(0)
    setSelectedProduct(null)
    setOrderConfirmed(false)

    matchedScenario.trace.forEach((_, index) => {
      const timeoutId = setTimeout(() => {
        setVisibleSteps(index + 1)
        if (index === matchedScenario.trace.length - 1) {
          setTimeout(() => setStage('results'), STEP_REVEAL_DELAY_MS)
        }
      }, STEP_REVEAL_DELAY_MS * (index + 1))
      timeoutsRef.current.push(timeoutId)
    })
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    runPipeline(query)
  }

  const handleExampleClick = (exampleQuery) => {
    setQuery(exampleQuery)
    runPipeline(exampleQuery)
  }

  const handleReset = () => {
    clearPendingTimeouts()
    setStage('idle')
    setScenario(null)
    setVisibleSteps(0)
    setSelectedProduct(null)
    setOrderConfirmed(false)
    setQuery('')
  }

  return (
    <div className="app">
      <header className="app__header">
        <span className="app__header-eyebrow">Automated Fulfillment · Demo Build</span>
        <h1>Shop<span>Mate</span> AI</h1>
        <p className="app__tagline">// agentic shopping assistant — hardcoded demo, no live backend</p>
      </header>

      <form className="query-form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Tell me what you want to buy..."
          className="query-form__input"
        />
        <button type="submit" className="query-form__submit-btn" disabled={stage === 'thinking'}>
          {stage === 'thinking' ? 'Working...' : 'Find It'}
        </button>
      </form>

      {stage === 'idle' && (
        <div className="example-queries">
          <span className="example-queries__label">Or pull a request slip from the queue</span>
          <div className="example-queries__grid">
            {EXAMPLE_QUERIES.map((example) => (
              <button
                key={example.text}
                className="example-queries__chip"
                onClick={() => handleExampleClick(example.text)}
              >
                <span className="example-queries__chip-icon">{example.icon}</span>
                {example.text}
              </button>
            ))}
          </div>
        </div>
      )}

      {scenario && stage !== 'idle' && (
        <div className="pipeline-output">
          <div className="work-order">
            <span className="work-order__aisle">Aisle: {scenario.aisle}</span>
            <ul className="work-order__grid">
              <li>
                <strong>Category</strong>
                {scenario.parsedIntent.category}
              </li>
              <li>
                <strong>Budget</strong>
                {scenario.parsedIntent.budget}
              </li>
              {scenario.parsedIntent.mustHaves.length > 0 && (
                <li>
                  <strong>Must-haves</strong>
                  {scenario.parsedIntent.mustHaves.join(', ')}
                </li>
              )}
            </ul>
          </div>

          <h2 className="section-label">Reasoning trace</h2>
          <ReasoningTrace steps={scenario.trace} visibleCount={visibleSteps} />

          {stage === 'results' && (
            <>
              <ProductRecommendations scenario={scenario} onSelectProduct={setSelectedProduct} />
              <button className="reset-btn" onClick={handleReset}>
                Start a new search
              </button>
            </>
          )}
        </div>
      )}

      {selectedProduct && !orderConfirmed && (
        <CartMandateModal
          product={selectedProduct}
          onCancel={() => setSelectedProduct(null)}
          onApprove={() => {
            setOrderConfirmed(true)
          }}
        />
      )}

      {orderConfirmed && selectedProduct && (
        <div className="modal-overlay">
          <div className="modal">
            <span className="confirm-stamp">✓ Dispatched</span>
            <h2>Mock order placed</h2>
            <p>
              <strong>{selectedProduct.title}</strong> — ₹{selectedProduct.price.toLocaleString('en-IN')}
            </p>
            <p className="modal__subtitle">
              No real payment was processed. This confirms the mandate flow works end to end.
            </p>
            <button
              className="modal__approve-btn"
              onClick={() => {
                setSelectedProduct(null)
                setOrderConfirmed(false)
              }}
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
