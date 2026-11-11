import { useState, useRef } from 'react'
import './App.css'
import './extras.css'
import './agent-notes.css'
import './features.css'
import { sendChat } from './api'
import { EXAMPLE_QUERIES } from './data/examples'
import ReasoningTrace from './components/ReasoningTrace'
import ProductRecommendations from './components/ProductRecommendations'
import CartMandateModal from './components/CartMandateModal'
import ChangeComparison from './components/ChangeComparison'
import VerifierDemoPanel from './components/VerifierDemoPanel'

// Delay between revealing each trace step once the answer has arrived.
// The agent's work is already finished by then; this just makes it readable.
const STEP_REVEAL_DELAY_MS = 220

function App() {
  const [query, setQuery] = useState('')
  const [stage, setStage] = useState('idle') // idle | loading | thinking | results | error
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [visibleSteps, setVisibleSteps] = useState(0)
  const [selectedProduct, setSelectedProduct] = useState(null)
  // Clarifying questions: the request the agent asked about, and the shopper's reply being typed.
  const [askedQuery, setAskedQuery] = useState('')
  const [clarifyAnswer, setClarifyAnswer] = useState('')
  // Demo: deliberately corrupt one claim so the checker can be seen rejecting it (costs one extra model call).
  const [demoTamper, setDemoTamper] = useState(false)
  const timeoutsRef = useRef([])
  const runIdRef = useRef(0)
  const lastRequestRef = useRef({ text: '', allowClarification: true }) // what "Try again" re-sends

  const clearPendingTimeouts = () => {
    timeoutsRef.current.forEach(clearTimeout)
    timeoutsRef.current = []
  }

  const revealTrace = (steps, runId) => {
    if (steps.length === 0) {
      setStage('results')
      return
    }
    steps.forEach((_, index) => {
      const timeoutId = setTimeout(() => {
        if (runIdRef.current !== runId) return
        setVisibleSteps(index + 1)
        if (index === steps.length - 1) {
          const finalId = setTimeout(() => {
            if (runIdRef.current === runId) setStage('results')
          }, STEP_REVEAL_DELAY_MS)
          timeoutsRef.current.push(finalId)
        }
      }, STEP_REVEAL_DELAY_MS * (index + 1))
      timeoutsRef.current.push(timeoutId)
    })
  }

  const runPipeline = async (submittedQuery, { allowClarification = true } = {}) => {
    const text = submittedQuery.trim()
    if (!text) return
    lastRequestRef.current = { text, allowClarification }

    clearPendingTimeouts()
    const runId = runIdRef.current + 1
    runIdRef.current = runId

    setStage('loading')
    setError('')
    setResult(null)
    setVisibleSteps(0)
    setSelectedProduct(null)
    setClarifyAnswer('')

    try {
      const data = await sendChat(text, { allowClarification, demoTamper })
      if (runIdRef.current !== runId) return // a newer search replaced this one
      setAskedQuery(data.clarification ? text : '')
      setResult(data)
      setStage('thinking')
      revealTrace(data.trace, runId)
    } catch (err) {
      if (runIdRef.current !== runId) return
      setError(err.message || 'Something went wrong.')
      setStage('error')
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    runPipeline(query)
  }

  const handleExampleClick = (exampleQuery) => {
    setQuery(exampleQuery)
    runPipeline(exampleQuery)
  }

  // The shopper answered the agent's question: send the original request plus the answer,
  // and tell the agent not to ask again (it searches with whatever it now knows).
  const handleClarifyAnswer = (e) => {
    e.preventDefault()
    const answer = clarifyAnswer.trim()
    if (!answer) return
    const combined = `${askedQuery} — ${answer}`
    setQuery(combined)
    runPipeline(combined, { allowClarification: false })
  }

  const handleClarifySkip = () => {
    runPipeline(askedQuery, { allowClarification: false })
  }

  const handleReset = () => {
    clearPendingTimeouts()
    runIdRef.current += 1
    setStage('idle')
    setResult(null)
    setError('')
    setVisibleSteps(0)
    setSelectedProduct(null)
    setQuery('')
    setAskedQuery('')
    setClarifyAnswer('')
  }

  const busy = stage === 'loading' || stage === 'thinking'

  return (
    <div className="app">
      <header className="app__header">
        <span className="app__header-eyebrow">Automated Fulfillment · Order Desk</span>
        <h1>Shop<span>Mate</span> AI</h1>
        <p className="app__tagline">// your agentic shopping assistant — plan, compare, decide</p>
      </header>

      <form className="query-form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Tell me what you want to buy..."
          className="query-form__input"
        />
        <button type="submit" className="query-form__submit-btn" disabled={busy}>
          {busy ? 'Working...' : 'Find It'}
        </button>
      </form>

      <label className="demo-toggle">
        <input type="checkbox" checked={demoTamper} onChange={(e) => setDemoTamper(e.target.checked)} disabled={busy} />
        Demo: plant one wrong claim to show the checker catching it (uses one extra model call)
      </label>

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

      {stage === 'loading' && (
        <div className="status-box status-box--loading" role="status">
          <span className="status-box__spinner" aria-hidden="true" />
          The agent is searching, checking specs and verifying its claims… this can take 10–20 seconds.
        </div>
      )}

      {stage === 'error' && (
        <div className="status-box status-box--error" role="alert">
          <strong>Couldn’t complete that search.</strong>
          <p>{error}</p>
          <button
            className="reset-btn"
            onClick={() => runPipeline(lastRequestRef.current.text || query, lastRequestRef.current)}
          >
            Try again
          </button>
        </div>
      )}

      {result && (stage === 'thinking' || stage === 'results') && (
        <div className="pipeline-output">
          <div className="work-order">
            <span className="work-order__aisle">Aisle: {result.aisle}</span>
            <ul className="work-order__grid">
              <li>
                <strong>Category</strong>
                {result.parsedIntent.category}
              </li>
              <li>
                <strong>Budget</strong>
                {result.parsedIntent.budget}
              </li>
              {result.parsedIntent.mustHaves.length > 0 && (
                <li>
                  <strong>Must-haves</strong>
                  {result.parsedIntent.mustHaves.join(', ')}
                </li>
              )}
            </ul>
            {result.dataSource && <span className="work-order__source">Data: {result.dataSource}</span>}
          </div>

          <h2 className="section-label">Reasoning trace</h2>
          <ReasoningTrace steps={result.trace} visibleCount={visibleSteps} />

          {stage === 'results' && result.clarification && (
            <div className="clarify-card">
              <span className="clarify-card__label">The agent needs one detail first</span>
              <p className="clarify-card__question">{result.clarification}</p>
              <form className="clarify-card__form" onSubmit={handleClarifyAnswer}>
                <input
                  type="text"
                  value={clarifyAnswer}
                  onChange={(e) => setClarifyAnswer(e.target.value)}
                  placeholder="e.g. earphones, or a smartwatch"
                  className="query-form__input"
                  aria-label="Your answer"
                  autoFocus
                />
                <button type="submit" className="query-form__submit-btn" disabled={!clarifyAnswer.trim()}>
                  Answer
                </button>
              </form>
              <button type="button" className="clarify-card__skip" onClick={handleClarifySkip}>
                Skip the question and search anyway
              </button>
            </div>
          )}

          {stage === 'results' && !result.clarification && (
            <>
              <ChangeComparison parsedIntent={result.parsedIntent} relaxations={result.relaxations} />
              <VerifierDemoPanel demo={result.demoTamper} />
              <ProductRecommendations result={result} onSelectProduct={setSelectedProduct} />
            </>
          )}

          {stage === 'results' && (
            <button className="reset-btn" onClick={handleReset}>
              Start a new search
            </button>
          )}
        </div>
      )}

      {selectedProduct && (
        <CartMandateModal product={selectedProduct} onClose={() => setSelectedProduct(null)} />
      )}
    </div>
  )
}

export default App