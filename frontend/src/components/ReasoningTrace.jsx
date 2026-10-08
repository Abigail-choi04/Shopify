/**
 * ShopMate AI — Reasoning Trace (Phase 8 preview, hardcoded for the demo)
 *
 * Renders the ReAct-style Thought -> Action -> Observation steps from
 * the project doc's "Transparent Reasoning" section. `visibleCount`
 * controls how many steps are shown, so App.jsx can reveal them one
 * at a time for the "agent is thinking" effect.
 */

const STEP_LABELS = {
  thought: { label: 'Thought', icon: '💭' },
  action: { label: 'Action', icon: '⚙️' },
  observation: { label: 'Observation', icon: '👁️' },
}

function ReasoningTrace({ steps, visibleCount }) {
  return (
    <div className="reasoning-trace">
      {steps.slice(0, visibleCount).map((step, index) => {
        const meta = STEP_LABELS[step.type]
        return (
          <div key={index} className={`trace-step trace-step--${step.type}`}>
            <span className="trace-step__icon">{meta.icon}</span>
            <div className="trace-step__body">
              <span className="trace-step__label">{meta.label}</span>
              <p className="trace-step__text">{step.text}</p>
              {step.toolCallId && (
                <span className="trace-step__tool-id">source_tool_call_id: {step.toolCallId}</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default ReasoningTrace
