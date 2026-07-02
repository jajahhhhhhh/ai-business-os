/** Inline mutation error — renders the problem+json detail from useApiAction. */
export function FormError({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700">
      {error}
    </p>
  );
}
