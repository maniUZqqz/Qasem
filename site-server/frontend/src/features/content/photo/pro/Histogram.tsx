import { useEffect, useRef } from "react";

export type HistData = { r: Uint32Array; g: Uint32Array; b: Uint32Array; l: Uint32Array; clipLo: number; clipHi: number };

/** هیستوگرامِ زندهٔ RGB + روشنایی، با نشانِ سوختگیِ تیره/روشن */
export default function Histogram({ data }: { data: HistData | null }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = c.clientWidth || 300;
    const H = c.clientHeight || 70;
    if (c.width !== Math.round(W * dpr)) {
      c.width = Math.round(W * dpr);
      c.height = Math.round(H * dpr);
    }
    const x = c.getContext("2d")!;
    x.setTransform(dpr, 0, 0, dpr, 0, 0);
    x.clearRect(0, 0, W, H);
    if (!data) return;
    let max = 1;
    for (const arr of [data.r, data.g, data.b]) for (let i = 2; i < 254; i++) max = Math.max(max, arr[i]);
    const plot = (arr: Uint32Array, color: string, fill: boolean) => {
      x.beginPath();
      x.moveTo(0, H);
      for (let i = 0; i < 256; i++) x.lineTo((i / 255) * W, H - Math.min(1, arr[i] / max) * (H - 2));
      x.lineTo(W, H);
      x.closePath();
      if (fill) {
        x.fillStyle = color;
        x.fill();
      } else {
        x.strokeStyle = color;
        x.lineWidth = 1;
        x.stroke();
      }
    };
    x.globalCompositeOperation = "lighter";
    plot(data.r, "rgba(248,70,70,.55)", true);
    plot(data.g, "rgba(60,220,110,.55)", true);
    plot(data.b, "rgba(70,130,255,.55)", true);
    x.globalCompositeOperation = "source-over";
    let lmax = 1;
    for (let i = 2; i < 254; i++) lmax = Math.max(lmax, data.l[i]);
    x.beginPath();
    for (let i = 0; i < 256; i++) {
      const px = (i / 255) * W;
      const py = H - Math.min(1, data.l[i] / lmax) * (H - 2);
      if (i) x.lineTo(px, py);
      else x.moveTo(px, py);
    }
    x.strokeStyle = "rgba(255,255,255,.85)";
    x.lineWidth = 1.2;
    x.stroke();
  }, [data]);

  return (
    <div className="pro-hist" data-testid="histogram">
      <canvas ref={ref} className="pro-hist-cv" />
      {data && data.clipLo > 0.005 && <i className="pro-clip lo" title="سیاهِ سوخته" />}
      {data && data.clipHi > 0.005 && <i className="pro-clip hi" title="سفیدِ سوخته" />}
    </div>
  );
}
