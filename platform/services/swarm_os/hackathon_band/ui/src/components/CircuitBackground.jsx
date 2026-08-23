import { useEffect, useRef } from "react";

/** Fondo sutil: circuitos finos + pocas estrellas — no interfiere con la UI. */
export default function CircuitBackground() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let raf = 0;
    let w = 0;
    let h = 0;

    const stars = Array.from({ length: 48 }, () => ({
      x: Math.random(),
      y: Math.random(),
      r: Math.random() * 1.2 + 0.3,
      sp: Math.random() * 0.00008 + 0.00002,
    }));

    const circuits = Array.from({ length: 14 }, (_, i) => ({
      y: (i + 1) / 15,
      speed: 0.00004 + (i % 5) * 0.00001,
      offset: Math.random(),
      nodes: 5 + (i % 4),
    }));

    const resize = () => {
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = w;
      canvas.height = h;
    };

    const drawCircuit = (cy, offset, nodes, t) => {
      const y = cy * h;
      ctx.strokeStyle = "rgba(56, 189, 248, 0.06)";
      ctx.lineWidth = 0.6;
      ctx.beginPath();
      const seg = w / (nodes + 1);
      for (let i = 0; i <= nodes; i++) {
        const x = i * seg + ((t + offset) % 1) * seg * 0.3;
        const bump = Math.sin(t * 6 + i * 0.8) * 3;
        if (i === 0) ctx.moveTo(0, y + bump);
        else ctx.lineTo(x, y + bump);
      }
      ctx.stroke();
      for (let i = 1; i <= nodes; i++) {
        const x = i * seg + ((t + offset) % 1) * seg * 0.3;
        ctx.fillStyle = "rgba(34, 211, 238, 0.12)";
        ctx.beginPath();
        ctx.arc(x, y, 1.5, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const frame = (now) => {
      const t = now * 0.001;
      ctx.clearRect(0, 0, w, h);
      for (const c of circuits) {
        drawCircuit(c.y, c.offset, c.nodes, t * c.speed * 1000 + c.offset * 10);
      }
      for (const s of stars) {
        const sx = s.x * w;
        const sy = (s.y + t * s.sp) % 1 * h;
        ctx.fillStyle = "rgba(228, 228, 231, 0.25)";
        ctx.beginPath();
        ctx.arc(sx, sy, s.r, 0, Math.PI * 2);
        ctx.fill();
      }
      raf = requestAnimationFrame(frame);
    };

    resize();
    window.addEventListener("resize", resize);
    raf = requestAnimationFrame(frame);
    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(raf);
    };
  }, []);

  return <canvas ref={canvasRef} className="circuit-bg" aria-hidden="true" />;
}
