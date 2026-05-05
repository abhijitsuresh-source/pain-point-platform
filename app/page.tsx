import { createClient } from '@/lib/supabase/server'

export default async function Home() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <h1 className="text-2xl font-bold mb-8">Pain Point Platform</h1>
      {user ? (
        <div className="text-center">
          <p className="text-green-600 mb-4">✅ Logged in as: {user.email}</p>
          <a href="/auth/signout" className="bg-red-500 text-white px-4 py-2 rounded">
            Sign Out
          </a>
        </div>
      ) : (
        <a href="/auth/signin" className="bg-blue-500 text-white px-4 py-2 rounded">
          Sign in with Google
        </a>
      )}
    </main>
  )
}