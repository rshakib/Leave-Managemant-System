import { useState } from 'react'
import { Button, Card, Spinner } from 'react-bootstrap'
import { useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext.jsx'
import { buildLoginUrl } from '../auth/redirectUtils.js'
import { getInitials } from '../utils/initials.js'
import Icon from './Icon.jsx'

const VARIANTS = {
  restricted: {
    title: 'Permission Required',
    message:
      'Your current account does not include access to this page.',
    icon: 'lock',
    iconBg: 'rgba(247, 144, 32, 0.10)',
    iconBorder: 'rgba(247, 144, 32, 0.24)',
    iconColor: '#d97706',
  },
  unavailable: {
    title: 'Access Restricted',
    message:
      'You do not have permission to view this leave request, or it is no longer available.',
    icon: 'lock',
    iconBg: 'rgba(247, 144, 32, 0.10)',
    iconBorder: 'rgba(247, 144, 32, 0.24)',
    iconColor: '#d97706',
  },
  error: {
    title: 'Unable to Load Page',
    message:
      'Something went wrong while loading this page. Please try again.',
    icon: 'alertCircle',
    iconBg: '#fef2f2',
    iconBorder: '#fecaca',
    iconColor: '#dc2626',
  },
}

/**
 * Refined, non-technical empty/restricted state card with account name context
 * and a one-click "Switch Account" flow that preserves the requested URL.
 */
export default function AccessState({
  variant = 'restricted',
  title,
  message,
  onRetry,
}) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [switching, setSwitching] = useState(false)

  const preset = VARIANTS[variant] ?? VARIANTS.restricted
  const heading = title || preset.title
  const body = message || preset.message
  const showSwitch = variant !== 'error' && Boolean(user)

  const handleSwitchAccount = async () => {
    setSwitching(true)
    const loginTarget = buildLoginUrl(location, { switchAccount: true })
    await logout()
    navigate(loginTarget, { replace: true })
  }

  return (
    <div
      className="d-flex align-items-center justify-content-center px-3"
      style={{ minHeight: 'calc(100vh - 150px)' }}
    >
      <Card
        className="w-100 text-center bg-white"
        style={{
          maxWidth: '460px',
          borderRadius: '12px',
          border: '1px solid var(--sol-line)',
          boxShadow: '0 8px 28px rgba(19, 19, 19, 0.05)',
        }}
      >
        <Card.Body className="p-4 p-sm-5">
          <div
            className="d-inline-flex align-items-center justify-content-center mb-3"
            style={{
              width: '52px',
              height: '52px',
              borderRadius: '12px',
              backgroundColor: preset.iconBg,
              border: `1px solid ${preset.iconBorder}`,
              color: preset.iconColor,
            }}
          >
            <Icon name={preset.icon} size={24} />
          </div>

          <h2 className="h4 fw-semibold mb-2" style={{ color: 'var(--sol-ink)' }}>
            {heading}
          </h2>
          <p
            className="mb-4 mx-auto"
            style={{
              color: 'var(--sol-body)',
              fontSize: '0.92rem',
              lineHeight: 1.55,
              maxWidth: '360px',
            }}
          >
            {body}
          </p>

          {user && (
            <div
              className="d-inline-flex align-items-center gap-2 px-3 py-1 rounded-pill mb-4"
              style={{
                backgroundColor: 'var(--sol-soft)',
                border: '1px solid var(--sol-line)',
                fontSize: '0.82rem',
                color: 'var(--sol-body)',
              }}
            >
              <span
                className="d-inline-flex align-items-center justify-content-center rounded-circle fw-semibold flex-shrink-0"
                style={{
                  width: '20px',
                  height: '20px',
                  backgroundColor: 'var(--sol-ink)',
                  color: '#ffffff',
                  fontSize: '0.65rem',
                }}
              >
                {getInitials(user.full_name)}
              </span>
              <span className="text-truncate">
                Signed in as{' '}
                <strong style={{ color: 'var(--sol-ink)' }}>{user.full_name}</strong>
              </span>
            </div>
          )}

          <div className="d-flex flex-wrap justify-content-center gap-2">
            <Button
              variant="outline-secondary"
              className="px-3 py-2 d-inline-flex align-items-center justify-content-center gap-2"
              style={{
                fontSize: '0.9rem',
                fontWeight: 500,
                borderRadius: '8px',
                minWidth: '140px',
              }}
              onClick={() => navigate('/')}
            >
              <Icon name="home" size={16} />
              Go to Home
            </Button>

            {showSwitch && (
              <Button
                variant="primary"
                className="px-3 py-2 d-inline-flex align-items-center justify-content-center gap-2"
                style={{
                  fontSize: '0.9rem',
                  fontWeight: 500,
                  borderRadius: '8px',
                  minWidth: '155px',
                }}
                onClick={handleSwitchAccount}
                disabled={switching}
              >
                {switching ? (
                  <>
                    <Spinner size="sm" animation="border" />
                    Signing out…
                  </>
                ) : (
                  <>
                    <Icon name="logout" size={16} />
                    Switch Account
                  </>
                )}
              </Button>
            )}

            {variant === 'error' && onRetry && (
              <Button
                variant="primary"
                className="px-3 py-2 d-inline-flex align-items-center justify-content-center gap-2"
                style={{
                  fontSize: '0.9rem',
                  fontWeight: 500,
                  borderRadius: '8px',
                  minWidth: '140px',
                }}
                onClick={onRetry}
              >
                <Icon name="refresh" size={16} />
                Try Again
              </Button>
            )}
          </div>
        </Card.Body>
      </Card>
    </div>
  )
}
