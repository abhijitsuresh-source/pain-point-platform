import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'

export async function GET() {
  const supabase = await createClient()
  const { data } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: {
      redirectTo: `https://pain-point-platform.vercel.app/auth/callback`,
    },
  })

  if (data.url) redirect(data.url)
}