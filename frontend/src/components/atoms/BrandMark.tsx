export function BrandMark() {
  return (
    <div className="flex items-center gap-2.5">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/axiacraft-logo.png"
        alt="AxiaCraft ProductFoundry"
        className="h-14 w-auto object-contain"
      />
      <span className="text-sm font-semibold leading-tight tracking-tight text-[color:var(--text)]">
        Product<br />Foundry
      </span>
    </div>
  );
}
