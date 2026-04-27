#!/bin/sh
# Runtime NEXT_PUBLIC_API_URL injection.
#
# Next.js bakes NEXT_PUBLIC_* values into static JS bundles at build time.
# This script replaces the build-time placeholder with the real value supplied
# via the NEXT_PUBLIC_API_URL environment variable before the server starts,
# making it possible to ship one image and configure it per-deployment.
#
# If NEXT_PUBLIC_API_URL is not set the placeholder is replaced with "auto",
# preserving the existing same-host auto-resolution behaviour.

PLACEHOLDER="__NEXT_PUBLIC_API_URL__"
REPLACEMENT="${NEXT_PUBLIC_API_URL:-auto}"

if [ "${REPLACEMENT}" != "auto" ]; then
  echo "Injecting NEXT_PUBLIC_API_URL=${REPLACEMENT} into bundle..."
else
  echo "NEXT_PUBLIC_API_URL not set — using auto-resolution."
fi

# Replace in all compiled JS chunks (static + server).
find /app/.next -type f -name "*.js" | while IFS= read -r f; do
  # Only process files that actually contain the placeholder (fast path).
  if grep -qF "${PLACEHOLDER}" "${f}"; then
    sed -i "s|${PLACEHOLDER}|${REPLACEMENT}|g" "${f}"
  fi
done

exec "$@"
