export function BrandMark() {
  return (
    <div className="flex items-center gap-3">
      <div className="grid h-10 w-10 place-items-center rounded-lg bg-gradient-to-br from-orange-600 to-orange-700 text-xs font-semibold text-white shadow-sm">
        <span className="font-heading tracking-[0.2em]">RC</span>
      </div>
      <div className="leading-tight">
        <div className="font-heading text-sm uppercase tracking-[0.26em] text-strong">
          RADICAL
        </div>
        <div className="text-[11px] font-medium text-quiet">
          Claw
        </div>
      </div>
    </div>
  );
}
