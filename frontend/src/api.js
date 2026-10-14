/**
 * ShopMate AI — Backend calls
 *
 * Every call to the FastAPI backend goes through this file, so the rest of
 * the app never has to know about URLs or error formats.
 *
 * The backend address defaults to http://localhost:8000. If yours is
 * different, create frontend/.env with:  VITE_API_URL=http://your-address
 */

const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, code = 'error', status = 0) {
    super(message)
    this.code = code
    this.status = status
  }
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    throw new ApiError(
      `Cannot reach the ShopMate backend at ${API_BASE}. Is it running? (uvicorn app.main:app --reload)`,
      'network',
    )
  }

  let body = null
  try {
    body = await response.json()
  } catch {
    // not JSON — handled below
  }

  if (!response.ok) {
    const detail = body && body.detail
    const message =
      (detail && typeof detail === 'object' && detail.message) ||
      (typeof detail === 'string' && detail) ||
      `The server answered with an error (${response.status}).`
    const code = (detail && typeof detail === 'object' && detail.code) || 'error'
    throw new ApiError(message, code, response.status)
  }
  return body
}

const post = (path, payload) =>
  request(path, { method: 'POST', body: payload === undefined ? undefined : JSON.stringify(payload) })

/** Ask the shopping agent. Returns { aisle, parsedIntent, trace, products, ... } */
export const sendChat = (query) => post('/chat', { query })

/** Mock Cart Mandate (Phase 7). Each returns { mandate, events, storage }. */
export const createMandate = (productId, quantity = 1) => post('/mandates', { product_id: productId, quantity })
export const approveMandate = (mandateId, consent) => post(`/mandates/${mandateId}/approve`, { consent })
export const checkoutMandate = (mandateId) => post(`/mandates/${mandateId}/checkout`)
export const getMandate = (mandateId) => request(`/mandates/${mandateId}`)
export const cancelMandate = (mandateId) => post(`/mandates/${mandateId}/cancel`)