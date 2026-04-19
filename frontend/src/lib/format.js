export const fmtMoney = (n, currency = "USD", decimals = 0) => {
  if (n === null || n === undefined || isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: decimals,
    minimumFractionDigits: decimals,
  }).format(n);
};

export const fmtNum = (n, decimals = 2) => {
  if (n === null || n === undefined || isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: decimals,
    minimumFractionDigits: decimals,
  }).format(n);
};

export const fmtCompact = (n) => {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(n);
};

export const fmtBps = (bps) => `${(bps / 100).toFixed(2)}%`;

export const fmtDate = (d, withTime = false) => {
  if (!d) return "—";
  const dt = typeof d === "string" ? new Date(d) : d;
  const opts = withTime
    ? { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }
    : { year: "numeric", month: "short", day: "2-digit" };
  return new Intl.DateTimeFormat("en-GB", opts).format(dt);
};

export const fmtDateTime = (d) => fmtDate(d, true);

export const truncateAddr = (a, n = 6) => {
  if (!a) return "—";
  return a.length > n * 2 + 3 ? `${a.slice(0, n)}…${a.slice(-n)}` : a;
};

export const relativeTime = (d) => {
  if (!d) return "—";
  const diff = (Date.now() - new Date(d).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

export const stellarExplorer = (hash) =>
  hash ? `https://stellar.expert/explorer/public/tx/${hash}` : "#";
