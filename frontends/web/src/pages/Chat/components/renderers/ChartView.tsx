import { useEffect, useRef } from 'react';
import type { RichComponent } from '../../types';

/**
 * ChartComponent renderer. Plotly is loaded lazily to keep it out of the
 * initial bundle. The serialized figure lives under `data.data`
 * (`{ data: traces, layout: {...} }`).
 */
export default function ChartView({ component }: { component: RichComponent }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const data = component.data ?? {};

  useEffect(() => {
    let disposed = false;
    const el = containerRef.current;
    if (!el) return;

    void import('plotly.js-dist-min').then((Plotly) => {
      if (disposed) return;
      const figure = data.data ?? {};
      void Plotly.newPlot(el, figure.data ?? [], figure.layout ?? {}, {
        displayModeBar: false,
        responsive: true,
      });
    });

    return () => {
      disposed = true;
      void import('plotly.js-dist-min').then((Plotly) => {
        Plotly.purge(el);
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(data)]);

  return <div ref={containerRef} style={{ width: '100%', minHeight: 320 }} />;
}