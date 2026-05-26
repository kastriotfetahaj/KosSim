type Props = {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
};

export default function SearchInput({ value, onChange, placeholder, autoFocus }: Props) {
  return (
    <div className="search">
      <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden>
        <path
          d="M10 18a8 8 0 1 1 5.293-2.293l4 4-1.414 1.414-4-4A7.962 7.962 0 0 1 10 18Zm0-2a6 6 0 1 0 0-12 6 6 0 0 0 0 12Z"
          fill="currentColor"
        />
      </svg>
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? "Search…"}
        autoFocus={autoFocus}
      />
      {value && (
        <button className="search-clear" onClick={() => onChange("")} aria-label="Clear">
          ×
        </button>
      )}
    </div>
  );
}
