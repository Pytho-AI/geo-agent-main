// Standalone stub of pytho-app's contextLib.useAppContext. The iframe
// version reads userId + email from URL params instead of pytho-app's
// Amplify Cognito context.

export function useAppContext() {
  if (typeof window === 'undefined') return { user: null, isAuthenticated: false }
  const params = new URLSearchParams(window.location.search)
  const userId = params.get('user_id') || params.get('userId') || ''
  const email = params.get('email') || params.get('by') || ''
  return {
    user: userId
      ? {
          attributes: { sub: userId, email: email || userId },
          username: email || userId,
        }
      : null,
    isAuthenticated: !!userId,
  }
}
