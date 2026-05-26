import React from 'react';

export function Header({
  children,
  actions = [],
}: {
  children: React.ReactNode;
  actions?: React.ReactNode[];
}) {
  return (
    <div className="flex justify-between items-center gap-2 border-b border-sleek-details w-full bg-sleek-fill">
      <span className="flex items-center px-3">{children}</span>
      <div className="flex ml-auto h-full">
        {actions.map((action, index) => (
          <div
            key={index}
            className="flex items-center border-l border-sleek-details hover:bg-sleek-details-subtle active:bg-sleek-details h-full py-1"
          >
            {action}
          </div>
        ))}
      </div>
    </div>
  );
}
