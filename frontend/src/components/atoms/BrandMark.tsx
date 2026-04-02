import Image from "next/image";

export function BrandMark() {
  return (
    <Image
      src="/axiacraft-logo.png"
      alt="AxiaCraft ProductFoundry"
      width={2018}
      height={1042}
      className="h-10 w-auto"
      priority
    />
  );
}
