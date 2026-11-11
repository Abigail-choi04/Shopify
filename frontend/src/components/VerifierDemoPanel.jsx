/**
 * ShopMate AI — Verifier demo panel
 *
 * Shown only when the shopper ticked "Demo: inject an error". The server deliberately made ONE drafted claim
 * wrong before the checker saw it; this panel shows what it was changed to, what the checker said, and
 * that the model's rewrite produced a clean answer.
 */

function VerifierDemoPanel({ demo }) {
  if (!demo) return null
  return (
    <div className={`verifier-demo ${demo.caught ? 'verifier-demo--caught' : 'verifier-demo--missed'}`} role="note">
      <span className="verifier-demo__title">
        {demo.caught ? '✓ Demo: the checker caught a planted error' : '⚠ Demo: the checker did NOT catch the planted error'}
      </span>
      <p className="verifier-demo__product">Product: {demo.productTitle}</p>
      <div className="verifier-demo__rows">
        <div>
          <span className="verifier-demo__label">The model wrote</span>
          <span className="verifier-demo__text verifier-demo__text--ok">“{demo.originalText}”</span>
        </div>
        <div>
          <span className="verifier-demo__label">We changed it to (wrong on purpose)</span>
          <span className="verifier-demo__text verifier-demo__text--bad">“{demo.alteredText}”</span>
        </div>
        <div>
          <span className="verifier-demo__label">The checker said</span>
          <span className="verifier-demo__text">{demo.verdict ? `Rejected: ${demo.verdict}` : 'It passed the check (this should not happen).'}</span>
        </div>
      </div>
      <p className="verifier-demo__foot">
        {demo.caught && demo.rewritten
          ? 'The agent then asked the model to rewrite its claims and checked them again; the answer below uses the corrected claims.'
          : demo.caught
            ? 'The wrong claim never reached the answer below.'
            : 'The planted claim reached the answer, which is a bug to report.'}
      </p>
    </div>
  )
}

export default VerifierDemoPanel