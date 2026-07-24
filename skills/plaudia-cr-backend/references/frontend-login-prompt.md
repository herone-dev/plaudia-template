# Frontend login prompts — Plaudia (23/07/2026)

Ces prompts Lovable ont ete donnes a Martin pour le frontend multi-user.

## Prompt 1 — Login sans inscription + mot de passe oublie

LoginPage.tsx : connexion uniquement, lien "Mot de passe oublie ?" qui appelle `supabase.auth.resetPasswordForEmail()`. Pas de formulaire d'inscription, pas de toggle.

## Prompt 2 — resetPassword dans AuthContext

Ajouter `resetPassword` dans AuthState et AuthProvider. Appelle `heroneSupabase.auth.resetPasswordForEmail(email, { redirectTo: origin + "/update-password" })`.

## Prompt 3 — Page de mise a jour du mot de passe

`UpdatePasswordPage.tsx` (route `/update-password`) : formulaire nouveau mot de passe + confirmation. Appelle `heroneSupabase.auth.updateUser({ password })`.

## Prompt 4 — Nettoyer les variables d'environnement

Supprimer de l'env Lovable : VITE_CF_CLIENT_ID, VITE_CF_CLIENT_SECRET, VITE_PLAUDIA_SHARED_KEY.
Verifier presence : VITE_PLAUDIA_BACKEND_URL, VITE_HERONE_SUPABASE_URL, VITE_HERONE_SUPABASE_PUBLISHABLE_KEY.