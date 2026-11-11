/**
 * ShopMate AI — Compare two products
 *
 * Asks the backend (POST /compare) for a side-by-side of two products from the current results.
 * The server builds it from the listings' own checked facts: a fact the listing doesn't state shows as
 * "Not listed" and never decides a winner. No language model is involved.
 */

import { useEffect, useState } from 'react'
import { compareProducts } from '../api'

function CompareModal({ idA, idB, onClose }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    compareProducts(idA, idB)
      .then((response) => {
        if (!cancelled) setData(response)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Could not compare these products.')
      })
    return () => {
      cancelled = true
    }
  }, [idA, idB])

  return (
    <div className="modal-overlay">
      <div className="modal modal--wide compare-modal">
        <h2 className="compare-modal__heading">Side by side</h2>

        {!data && !error && <p className="mandate-status">Comparing…</p>}
        {error && (
          <div className="status-box status-box--error" role="alert">
            <p>{error}</p>
          </div>
        )}

        {data && (
          <>
            <div className="compare-table-wrap">
              <table className="compare-table">
                <thead>
                  <tr>
                    <th />
                    <th>{data.a.title}</th>
                    <th>{data.b.title}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr key={row.label}>
                      <th scope="row">{row.label}</th>
                      <td className={row.winner === 'a' ? 'compare-table__win' : ''}>
                        {row.winner === 'a' && <span aria-label="better">★ </span>}
                        {row.a}
                      </td>
                      <td className={row.winner === 'b' ? 'compare-table__win' : ''}>
                        {row.winner === 'b' && <span aria-label="better">★ </span>}
                        {row.b}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="compare-modal__tally">
              First product better on {data.aWins} row{data.aWins === 1 ? '' : 's'} · second product on {data.bWins} · {data.ties} tied
            </p>
            <ul className="compare-modal__summary">
              {data.summary.map((sentence, index) => (
                <li key={index}>{sentence}</li>
              ))}
            </ul>
            <p className="compare-modal__foot">
              Built directly from the listings{data.dataSource ? ` (${data.dataSource})` : ''}; no AI model wrote this. ★ marks the
              better value where “better” is clear; facts a listing doesn’t state are not compared.
            </p>
          </>
        )}

        <div className="modal__actions">
          <button className="modal__cancel-btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

export default CompareModal