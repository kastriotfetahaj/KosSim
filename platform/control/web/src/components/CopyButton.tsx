import { useState } from "react";

export default function CopyButton({ text, label = "copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const handle = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* ignore */
    }
  };
  return (
    <button className="copy-btn" onClick={handle} title={`Copy ${label}`}>
      {copied ? "✓ copied" : "copy"}
    </button>
  );
}
