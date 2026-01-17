import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Harbor - TouristPulse',
  description: 'Tourism prediction for Santa Cruz',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
