// Tiny inline SVG icon set — keeps the scoreboard / admin pages
// dependency-free and themable via `currentColor`.

type IconProps = { size?: number; className?: string; title?: string };

const wrap = (path: JSX.Element) => ({ size = 14, className, title }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="currentColor"
    aria-hidden={title ? undefined : true}
    role={title ? "img" : undefined}
    className={className}
  >
    {title ? <title>{title}</title> : null}
    {path}
  </svg>
);

export const TrophyIcon = wrap(
  <path d="M7 4h10v2h3v4a4 4 0 0 1-4 4h-.6A5 5 0 0 1 13 16.9V19h3v2H8v-2h3v-2.1A5 5 0 0 1 7.6 14H7a4 4 0 0 1-4-4V6h4V4Zm-2 4v2a2 2 0 0 0 2 2V8H5Zm14 0v4a2 2 0 0 0 2-2V8h-2Z" />,
);

export const StarIcon = wrap(
  <path d="M12 2l2.9 6.6 7.1.6-5.4 4.7 1.7 7-6.3-3.8L5.7 21l1.7-7L2 9.2l7.1-.6L12 2Z" />,
);

export const WrenchIcon = wrap(
  <path d="M21.7 6.3a1 1 0 0 0-1.6-.3L17 9.2 14.8 7l3.2-3.2a1 1 0 0 0-.3-1.6 6 6 0 0 0-7.6 7.6L2.6 17.3a2 2 0 0 0 0 2.8L4 21.4a2 2 0 0 0 2.8 0l7.5-7.5a6 6 0 0 0 7.4-7.6Z" />,
);

export const SwordIcon = wrap(
  <path d="M14.5 2l7.5 7.5-5 5-2.5-2.5-7.5 7.5H4v-3l7.5-7.5L9 6.5l5-5 .5.5Zm-9 17h.6L13 11.6l-1.1-1.1L4.4 18v.6L5.5 19Z" />,
);

export const ShieldIcon = wrap(
  <path d="M12 2l9 4v6c0 5-3.8 9.6-9 10-5.2-.4-9-5-9-10V6l9-4Zm0 2.2L5 7v5c0 4 3 7.7 7 8.1 4-.4 7-4.1 7-8.1V7l-7-2.8Z" />,
);

export const TargetIcon = wrap(
  <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2Zm0 4a6 6 0 1 1-6 6 6 6 0 0 1 6-6Zm0 3a3 3 0 1 0 3 3 3 3 0 0 0-3-3Z" />,
);

export const ArrowUpIcon = wrap(
  <path d="M12 5l7 7h-4v7h-6v-7H5l7-7Z" />,
);

export const ArrowDownIcon = wrap(
  <path d="M12 19l-7-7h4V5h6v7h4l-7 7Z" />,
);

export const PauseIcon = wrap(
  <path d="M7 4h4v16H7zM13 4h4v16h-4z" />,
);

export const PlayIcon = wrap(
  <path d="M6 4l14 8L6 20V4Z" />,
);

export const FlagInIcon = wrap(
  <path d="M11 3h2v6h3l-4 5-4-5h3V3ZM3 17h18v4H3v-4Z" />,
);

export const FlagOutIcon = wrap(
  <path d="M13 14h-2V8H8l4-5 4 5h-3v6ZM3 17h18v4H3v-4Z" />,
);

export const BoltIcon = wrap(
  <path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z" />,
);

export const CheckIcon = wrap(
  <path d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2Z" />,
);

export const XIcon = wrap(
  <path d="M18.3 5.7 12 12l6.3 6.3-1.4 1.4L10.6 13.4 4.3 19.7l-1.4-1.4L9.2 12 2.9 5.7l1.4-1.4L10.6 10.6l6.3-6.3 1.4 1.4Z" />,
);

export const DashIcon = wrap(
  <path d="M5 11h14v2H5z" />,
);
