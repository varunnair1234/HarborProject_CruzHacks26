'use client'

import { useState, useEffect } from 'react'

// Backend API response types (matching Python backend schemas)
interface DemandSignal {
  source: string
  factor: string
  impact: string
  weight: number
}

interface TouristPulseOutlook {
  date: string
  demand_level: 'low' | 'moderate' | 'high' | 'very_high'
  confidence: number
  drivers: DemandSignal[]
  summary: string
}

interface TouristPulseResponse {
  location: string
  outlook: TouristPulseOutlook[]
  generated_at: string
}

export default function TouristPulse() {
  const [outlook, setOutlook] = useState<TouristPulseOutlook[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [location] = useState('Santa Cruz')

  useEffect(() => {
    loadTouristOutlook()
  }, [])

  const loadTouristOutlook = async () => {
    try {
      setLoading(true)
      setError(null)

      // Call Python backend API
      // Use environment variable for backend URL (set in Render dashboard)
      const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
      const response = await fetch(`${backendUrl}/touristpulse/outlook?location=${encodeURIComponent(location)}&days=30`)

      if (!response.ok) {
        throw new Error(`Backend API error: ${response.status}`)
      }

      const data: TouristPulseResponse = await response.json()
      setOutlook(data.outlook || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tourist outlook')
      console.error('Error loading tourist outlook:', err)
    } finally {
      setLoading(false)
    }
  }

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'very_high':
        return { bg: '#d8b4fe', text: '#6b21a8', border: '#a855f7', label: 'VERY HIGH' }
      case 'high':
        return { bg: '#bbf7d0', text: '#166534', border: '#22c55e', label: 'HIGH' }
      case 'moderate':
        return { bg: '#bfdbfe', text: '#1e40af', border: '#3b82f6', label: 'NORMAL' }
      case 'low':
        return { bg: '#fef3c7', text: '#92400e', border: '#f59e0b', label: 'LOW' }
      default:
        return { bg: '#e5e7eb', text: '#374151', border: '#9ca3af', label: 'UNKNOWN' }
    }
  }

  if (loading) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center' }}>
        <div>Loading tourism predictions from backend...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: '2rem', color: 'red' }}>
        <div>Error: {error}</div>
        <div style={{ marginTop: '1rem', fontSize: '0.9rem' }}>
          Make sure the Python backend is running on port 8000:
          <br />
          <code style={{ background: '#f3f4f6', padding: '0.25rem 0.5rem', borderRadius: '4px' }}>
            cd backend && python -m uvicorn app.main:app --reload
          </code>
        </div>
      </div>
    )
  }

  return (
    <div>
      <h2 style={{ marginBottom: '1rem' }}>30-Day Tourism Forecast for {location}</h2>
      <div style={{ marginBottom: '1rem', fontSize: '0.9rem', color: '#666' }}>
        Generated at: {outlook.length > 0 ? new Date(outlook[0].date).toLocaleString() : 'N/A'}
      </div>
      
      <div style={{ display: 'grid', gap: '1rem' }}>
        {outlook.map((day, idx) => {
          const colors = getLevelColor(day.demand_level)
          const dateObj = new Date(day.date)
          
          return (
            <div
              key={idx}
              style={{
                padding: '1rem',
                border: `2px solid ${colors.border}`,
                borderRadius: '8px',
                backgroundColor: colors.bg,
                color: colors.text,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                <div>
                  <strong>
                    {dateObj.toLocaleDateString('en-US', {
                      weekday: 'short',
                      month: 'short',
                      day: 'numeric',
                    })}
                  </strong>
                  <div style={{ fontSize: '0.9rem', marginTop: '0.25rem' }}>
                    Level: <strong>{colors.label}</strong>
                    {day.confidence && (
                      <span style={{ fontSize: '0.85rem', opacity: 0.8 }}>
                        {' '}({Math.round(day.confidence * 100)}% confidence)
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {day.summary && (
                <div
                  style={{
                    fontSize: '0.85rem',
                    marginTop: '0.5rem',
                    fontStyle: 'italic',
                    opacity: 0.9,
                  }}
                >
                  {day.summary}
                </div>
              )}

              {day.drivers && day.drivers.length > 0 && (
                <div style={{ fontSize: '0.8rem', marginTop: '0.75rem', paddingTop: '0.75rem', borderTop: `1px solid ${colors.border}`, opacity: 0.8 }}>
                  <strong>Drivers:</strong>
                  <ul style={{ marginTop: '0.25rem', paddingLeft: '1.25rem' }}>
                    {day.drivers.map((driver, i) => (
                      <li key={i}>
                        {driver.source}: {driver.factor} ({driver.impact}, weight: {driver.weight.toFixed(2)})
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {outlook.length === 0 && (
        <div style={{ textAlign: 'center', padding: '2rem', color: '#666' }}>
          No outlook data available
        </div>
      )}
    </div>
  )
}
